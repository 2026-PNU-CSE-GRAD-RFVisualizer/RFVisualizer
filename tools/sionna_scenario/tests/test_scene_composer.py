from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml

import tools.sionna_scenario.scenario_builder as scenario_builder
from tools.sionna_scenario.scene_composer import (
    SceneCompositionError,
    annotate_runtime_objects,
    compose_scene,
)
from tools.sionna_smoke_test.metric_scene_loader import MeshObject, MetricScene


def _cube_scene(tmp_path: Path):
    vertices = np.asarray(
        [
            [0, 0, 0],
            [2, 0, 0],
            [2, 2, 0],
            [0, 2, 0],
            [0, 0, 2],
            [2, 0, 2],
            [2, 2, 2],
            [0, 2, 2],
        ],
        dtype=float,
    )
    parts = [
        ("floor_000", "floor", [[0, 2, 1], [0, 3, 2]]),
        ("ceiling_000", "ceiling", [[4, 5, 6], [4, 6, 7]]),
        ("wall_000", "wall", [[0, 1, 5], [0, 5, 4]]),
        ("wall_001", "wall", [[1, 2, 6], [1, 6, 5]]),
        ("wall_002", "wall", [[2, 3, 7], [2, 7, 6]]),
        ("wall_003", "wall", [[3, 0, 4], [3, 4, 7]]),
    ]
    objects = [
        MeshObject(name, semantic, semantic, np.asarray(faces, dtype=int))
        for name, semantic, faces in parts
    ]
    identity = np.eye(4).tolist()
    return MetricScene(
        vertices=vertices,
        faces=np.vstack([value.faces for value in objects]),
        objects=objects,
        metric_metadata={},
        calibration={
            "transform": {
                "T_metric_from_scene": identity,
                "T_scene_from_metric": identity,
            }
        },
        paths={"metric_obj": tmp_path / "room_envelope_metric.obj"},
    )


def _settings():
    return {
        "status": "provisional",
        "confidence": "low",
        "physically_validated": False,
        "scene": {"name": "unit_room"},
        "materials": {
            "floor": {"preset": "concrete"},
            "ceiling": {"preset": "concrete"},
            "walls": {"preset": "concrete"},
        },
    }


def _obstacle(object_name="blocker_panel_000"):
    vertices = np.asarray(
        [
            [0.9, 0.5, 0.0],
            [1.1, 0.5, 0.0],
            [1.1, 1.5, 0.0],
            [0.9, 1.5, 0.0],
            [0.9, 0.5, 1.5],
            [1.1, 0.5, 1.5],
            [1.1, 1.5, 1.5],
            [0.9, 1.5, 1.5],
        ],
        dtype=float,
    )
    faces = np.asarray(
        [
            [0, 2, 1],
            [0, 3, 2],
            [4, 5, 6],
            [4, 6, 7],
            [0, 1, 5],
            [0, 5, 4],
            [1, 2, 6],
            [1, 6, 5],
            [2, 3, 7],
            [2, 7, 6],
            [3, 0, 4],
            [3, 4, 7],
        ],
        dtype=int,
    )
    material = {
        "obstacle_id": "blocker_panel_000",
        "category": "wood",
        "actual_sionna_material_name": "itu_wood_blocker_panel_000",
        "itu_type": "wood",
        "thickness_m": 0.1,
        "scattering_coefficient": 0.0,
        "source": "sionna_preset",
        "fallback_used": False,
    }
    return {
        "id": "blocker_panel_000",
        "object_name": object_name,
        "group_name": "obstacle_validation",
        "semantic_class": "validation_blocker",
        "purpose": "validation_only",
        "physical_object": False,
        "confidence": "synthetic",
        "geometry_type": "box",
        "vertices": vertices,
        "faces": faces,
        "local_to_metric": np.eye(4),
        "local_to_scene": np.eye(4),
        "material": material,
        "validation": {"success": True},
        "source_config": {"id": "blocker_panel_000"},
    }


def _materials(record):
    return {
        "schema_version": "1.0",
        "status": "provisional",
        "physically_validated": False,
        "strict_resolution": True,
        "fallback_policy": "none",
        "materials": [record["material"]],
        "object_mapping": [
            {
                "object_name": record["id"],
                "category": "wood",
                "radio_material": record["material"][
                    "actual_sionna_material_name"
                ],
            }
        ],
    }


def _scenario():
    return {
        "id": "synthetic",
        "synthetic_validation": True,
        "base_scene": {"phase2a_config": "phase2a.yaml"},
        "obstacles": [
            {"id": "blocker_panel_000", "enabled": True},
            {"id": "desk_disabled", "enabled": False},
        ],
    }


def test_composition_keeps_room_and_obstacle_shapes_materials_and_files_independent(
    tmp_path: Path,
):
    record = _obstacle()
    manifest = compose_scene(
        _cube_scene(tmp_path),
        _settings(),
        _scenario(),
        [record],
        _materials(record),
        tmp_path / "built",
    )

    assert manifest["room_object_count"] == 6
    assert manifest["obstacle_object_count"] == 1
    assert manifest["total_object_count"] == 7
    assert manifest["object_layers_independent"] is True
    assert manifest["merge_shapes"] is False
    assert manifest["base_scene"]["room_envelope_modified"] is False
    assert manifest["enabled_obstacles"] == ["blocker_panel_000"]
    assert manifest["disabled_obstacles"] == ["desk_disabled"]
    assert {value["layer"] for value in manifest["objects"]} == {
        "room_envelope",
        "proxy_obstacle",
    }

    xml = Path(manifest["scene_xml"]).read_text(encoding="utf-8")
    assert xml.count('<shape type="ply"') == 7
    assert 'id="mesh-floor_000"' in xml
    assert 'id="mesh-blocker_panel_000"' in xml
    assert '<ref id="itu_wood_blocker_panel_000" name="bsdf"/>' in xml
    assert (tmp_path / "built" / "scene" / "meshes" / "floor_000.ply").is_file()
    assert (
        tmp_path / "built" / "scene" / "meshes" / "blocker_panel_000.ply"
    ).is_file()
    obj = (tmp_path / "built" / "obstacles_combined.obj").read_text(
        encoding="utf-8"
    )
    assert "o blocker_panel_000" in obj
    assert "g obstacle_validation" in obj
    assert "usemtl itu_wood_blocker_panel_000" in obj
    assert manifest["coordinate_bridge_validation"]["success"] is True
    assert (
        manifest["coordinate_bridge_validation"]["transform_maximum_error"]
        <= 1.0e-8
    )


def test_empty_scenario_does_not_claim_synthetic_objects(tmp_path: Path):
    scenario = {
        "id": "empty",
        "synthetic_validation": False,
        "base_scene": {"phase2a_config": "phase2a.yaml"},
        "obstacles": [],
    }
    materials = {
        "materials": [],
        "object_mapping": [],
        "strict_resolution": True,
        "fallback_policy": "none",
    }
    manifest = compose_scene(
        _cube_scene(tmp_path),
        _settings(),
        scenario,
        [],
        materials,
        tmp_path / "empty",
    )
    assert not any("Synthetic" in warning for warning in manifest["warnings"])
    obj = (tmp_path / "empty" / "obstacles_combined.obj").read_text(
        encoding="utf-8"
    )
    assert "SYNTHETIC" not in obj


def test_room_and_obstacle_object_name_collision_is_rejected(tmp_path: Path):
    record = _obstacle(object_name="floor_000")
    with pytest.raises(SceneCompositionError, match="충돌"):
        compose_scene(
            _cube_scene(tmp_path),
            _settings(),
            _scenario(),
            [record],
            _materials(record),
            tmp_path / "collision",
        )


def test_combined_obj_uses_export_object_name_not_logical_id(tmp_path: Path):
    record = _obstacle(object_name="render_shape_000")
    compose_scene(
        _cube_scene(tmp_path),
        _settings(),
        _scenario(),
        [record],
        _materials(record),
        tmp_path / "renamed",
    )
    text = (tmp_path / "renamed" / "obstacles_combined.obj").read_text(
        encoding="utf-8"
    )
    assert "# obstacle_id: blocker_panel_000" in text
    assert "o render_shape_000" in text


def test_runtime_object_ids_are_annotated_for_every_independent_shape(tmp_path: Path):
    manifest = {
        "objects": [
            {"object_name": "floor_000"},
            {"object_name": "blocker_panel_000"},
        ]
    }
    scene = SimpleNamespace(
        objects={
            "floor_000": SimpleNamespace(object_id=1),
            "blocker_panel_000": SimpleNamespace(object_id=7),
        }
    )
    result = annotate_runtime_objects(manifest, scene, tmp_path)

    assert [value["runtime_object_id"] for value in result["objects"]] == [1, 7]
    assert result["runtime_object_id_validation"]["success"] is True


def test_build_scenario_writes_public_resolved_yaml_and_updates_manifest(
    monkeypatch, tmp_path: Path
):
    captured = {}

    def fake_compose(metric_scene, settings, scenario, records, materials, output):
        captured["records"] = records
        captured["output"] = Path(output)
        return {"scenario_id": scenario["id"], "files": {}}

    preview = tmp_path / "built" / "scenario_preview.png"
    monkeypatch.setattr(scenario_builder, "compose_scene", fake_compose)
    monkeypatch.setattr(
        scenario_builder,
        "export_scenario_preview",
        lambda metric_scene, records, positions, output: str(preview),
    )
    prepared = SimpleNamespace(
        metric_scene=object(),
        settings={"status": "provisional"},
        scenario={"id": "unit_scenario"},
        obstacle_records=[{"id": "blocker"}],
        materials={"materials": []},
        positions=[{"name": "tx", "resolved_position_m": [1, 2, 3]}],
        placement_warnings=["unit warning"],
        document={
            "_source_path": "/private/scenario.yaml",
            "scenario": {
                "id": "unit_scenario",
                "_phase2a_config_path": "/private/phase2a.yaml",
                "obstacles": [],
            },
        },
    )

    manifest = scenario_builder.build_scenario(prepared, tmp_path / "built")
    resolved = yaml.safe_load(
        (tmp_path / "built" / "resolved_scenario.yaml").read_text(encoding="utf-8")
    )

    assert captured["records"] == [{"id": "blocker"}]
    assert captured["output"] == (tmp_path / "built").resolve()
    assert resolved["scenario"]["resolved_positions"] == prepared.positions
    assert resolved["scenario"]["placement_warnings"] == ["unit warning"]
    assert "_phase2a_config_path" not in resolved["scenario"]
    assert manifest["files"]["scenario_preview_png"] == str(preview)
    assert Path(manifest["files"]["resolved_scenario_yaml"]).is_file()
