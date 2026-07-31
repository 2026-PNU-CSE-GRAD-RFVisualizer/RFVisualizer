from types import SimpleNamespace

import pytest

import tools.sionna_scenario.material_resolver as resolver
from tools.sionna_scenario.material_resolver import (
    MaterialResolutionError,
    inspect_scene_materials,
    material_xml,
    resolve_material_request,
    resolve_obstacle_materials,
)


def _obstacle(category="wood", obstacle_id="object_000", **material_updates):
    material = {
        "source": "sionna_preset",
        "category": category,
        "thickness_m": 0.12,
        "scattering_coefficient": 0.25,
    }
    material.update(material_updates)
    return {"id": obstacle_id, "enabled": True, "material": material}


@pytest.mark.parametrize("category", ["concrete", "wood", "metal", "glass"])
def test_supported_categories_resolve_to_installed_itu_type_without_fallback(
    monkeypatch, category
):
    monkeypatch.setattr(
        resolver,
        "installed_itu_types",
        lambda: {"concrete", "wood", "metal", "glass"},
    )
    result = resolve_material_request(_obstacle(category=category))

    assert result["category"] == category
    assert result["itu_type"] == category
    assert result["actual_sionna_material_name"] == "radio_itu_{}_object_000".format(
        category
    )
    assert result["availability_verified_against_installed_sionna"] is True
    assert result["fallback_used"] is False
    assert result["warning"] is None


def test_resolved_material_name_avoids_sionna_automatic_itu_rewrite(monkeypatch):
    # Given: an obstacle with a non-zero diffuse-scattering coefficient.
    monkeypatch.setattr(resolver, "installed_itu_types", lambda: None)

    # When: its Sionna material name is resolved.
    result = resolve_material_request(
        _obstacle("concrete", "wall", scattering_coefficient=0.2)
    )

    # Then: the ID does not trigger Sionna's `itu_` XML rewrite, which drops
    # custom scattering properties in Sionna RT 1.2.2.
    assert not result["actual_sionna_material_name"].startswith(("itu_", "itu-"))


def test_unknown_category_or_missing_installed_itu_type_fails_strictly(monkeypatch):
    monkeypatch.setattr(resolver, "installed_itu_types", lambda: {"concrete"})
    with pytest.raises(MaterialResolutionError, match="지원하지 않는"):
        resolve_material_request(_obstacle(category="cardboard"))
    with pytest.raises(MaterialResolutionError, match="wood"):
        resolve_material_request(_obstacle(category="wood"))


def test_conflicting_category_and_preset_are_not_silently_accepted(monkeypatch):
    monkeypatch.setattr(
        resolver, "installed_itu_types", lambda: {"wood", "metal"}
    )
    with pytest.raises(MaterialResolutionError, match="충돌"):
        resolve_material_request(_obstacle(category="wood", preset="metal"))


@pytest.mark.parametrize(
    "updates,match",
    [
        ({"thickness_m": 0.0}, "thickness"),
        ({"thickness_m": float("inf")}, "thickness"),
        ({"scattering_coefficient": -0.01}, "scattering"),
        ({"scattering_coefficient": 1.01}, "scattering"),
        ({"source": "custom"}, "sionna_preset"),
    ],
)
def test_material_numeric_bounds_and_source_are_validated(monkeypatch, updates, match):
    monkeypatch.setattr(resolver, "installed_itu_types", lambda: None)
    with pytest.raises(MaterialResolutionError, match=match):
        resolve_material_request(_obstacle(**updates))


def test_material_collection_maps_objects_and_xml_keeps_requested_rf_values(
    monkeypatch,
):
    monkeypatch.setattr(resolver, "installed_itu_types", lambda: None)
    obstacles = [
        _obstacle("wood", "desk"),
        _obstacle("metal", "panel", thickness_m=0.03, scattering_coefficient=0.4),
        {**_obstacle("glass", "disabled"), "enabled": False},
    ]
    result = resolve_obstacle_materials(obstacles)

    assert result["strict_resolution"] is True
    assert result["fallback_policy"] == "none"
    assert [value["object_name"] for value in result["object_mapping"]] == [
        "desk",
        "panel",
    ]
    xml = material_xml(result["materials"][1])
    assert 'type="itu-radio-material"' in xml
    assert 'value="metal"' in xml
    assert 'name="thickness" value="0.03"' in xml
    assert 'name="scattering_coefficient" value="0.4"' in xml


def test_material_mapping_uses_export_object_name(monkeypatch):
    monkeypatch.setattr(resolver, "installed_itu_types", lambda: None)
    obstacle = _obstacle("wood", "logical_id")
    obstacle["export"] = {"object_name": "render_shape_000"}
    result = resolve_obstacle_materials([obstacle])
    assert result["object_mapping"][0]["object_name"] == "render_shape_000"


class _Scalar:
    def __init__(self, value):
        self._value = value

    def numpy(self):
        return [self._value]


def test_runtime_material_inspection_records_evaluated_values_and_usage(monkeypatch):
    monkeypatch.setattr(resolver, "installed_itu_types", lambda: None)
    requested = resolve_obstacle_materials([_obstacle("wood", "blocker")])
    name = requested["materials"][0]["actual_sionna_material_name"]
    material = SimpleNamespace(
        itu_type="wood",
        relative_permittivity=_Scalar(2.8),
        conductivity=_Scalar(0.12),
        thickness=_Scalar(0.1),
        scattering_coefficient=_Scalar(0.0),
        is_used=True,
    )
    scene = SimpleNamespace(radio_materials={name: material})
    result = inspect_scene_materials(
        scene, {"objects": [{"object_name": "blocker"}]}, requested
    )

    actual = result["materials"][0]
    assert actual["category"] == "wood"
    assert actual["relative_permittivity"] == pytest.approx(2.8)
    assert actual["conductivity_s_per_m"] == pytest.approx(0.12)
    assert actual["is_used"] is True

    material.itu_type = "metal"
    with pytest.raises(MaterialResolutionError, match="요청 'wood'"):
        inspect_scene_materials(scene, {"objects": []}, requested)
