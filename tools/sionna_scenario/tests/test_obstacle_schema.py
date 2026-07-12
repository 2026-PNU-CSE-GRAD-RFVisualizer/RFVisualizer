from pathlib import Path

import pytest

from tools.sionna_scenario.obstacle_schema import (
    ObstacleSchemaError,
    load_obstacles,
    obstacles_from_document,
    parse_obstacle,
    parse_obstacles,
)


def _box(**updates):
    value = {
        "id": "blocker_000",
        "enabled": True,
        "semantic_class": "validation_blocker",
        "purpose": "validation_only",
        "physical_object": False,
        "confidence": "synthetic",
        "geometry": {
            "type": "box",
            "anchor": {"mode": "floor_at_xy"},
            "position_m": {"x": -5.0, "y": -5.0},
            "size_m": {"x": 0.15, "y": 2.5, "z": 2.0},
            "rotation_deg": {"roll": 0.0, "pitch": 0.0, "yaw": 0.0},
            "floor_clearance_m": 0.05,
        },
        "material": {"source": "sionna_preset", "category": "wood"},
        "export": {"object_name": "blocker_000", "group_name": "validation"},
    }
    value.update(updates)
    return value


def test_box_schema_normalises_vectors_and_validation_markers():
    obstacle = parse_obstacle(_box())
    assert obstacle.id == "blocker_000"
    assert obstacle.geometry.position_m == (-5.0, -5.0)
    assert obstacle.geometry.size_m == (0.15, 2.5, 2.0)
    assert obstacle.geometry.anchor.mode == "floor_at_xy"
    assert obstacle.geometry.floor_clearance_m == 0.05
    assert obstacle.purpose == "validation_only"
    assert not obstacle.physical_object
    assert obstacle.confidence == "synthetic"


def test_thin_panel_named_dimensions_use_thickness_width_height_axes():
    value = _box()
    value["geometry"] = {
        "type": "thin_panel",
        "anchor": "bottom_center",
        "position_m": [1, 2, 3],
        "width_m": 4,
        "height_m": 2,
        "thickness_m": 0.1,
    }
    panel = parse_obstacle(value)
    assert panel.geometry.size_m == (0.1, 4.0, 2.0)
    assert panel.geometry.thickness_m == 0.1
    assert panel.geometry.width_m == 4.0
    assert panel.geometry.height_m == 2.0


def test_disabled_draft_accepts_null_geometry_but_enabled_draft_rejects_it():
    value = _box(enabled=False, purpose="classroom_proxy", physical_object=True, confidence="unset")
    value["geometry"] = {
        "type": "box",
        "anchor": {"mode": "floor_at_xy"},
        "position_m": None,
        "size_m": None,
        "rotation_deg": None,
    }
    draft = parse_obstacle(value)
    assert not draft.enabled
    assert draft.geometry.position_m is None
    assert draft.geometry.size_m is None
    value["enabled"] = True
    with pytest.raises(ObstacleSchemaError, match="활성 box"):
        parse_obstacle(value)


@pytest.mark.parametrize("mode", ["center", "bottom_center"])
def test_non_floor_anchors_require_xyz(mode):
    value = _box()
    value["geometry"]["anchor"] = {"mode": mode}
    value["geometry"]["position_m"] = [1, 2]
    with pytest.raises(ObstacleSchemaError, match="x/y/z"):
        parse_obstacle(value)


def test_explicit_transform_requires_affine_matrix_and_rejects_ambiguous_position():
    value = _box()
    geometry = value["geometry"]
    geometry["anchor"] = {"mode": "explicit_transform"}
    geometry["position_m"] = None
    geometry["transform"] = [
        [1, 0, 0, 4],
        [0, 1, 0, 5],
        [0, 0, 1, 6],
        [0, 0, 0, 1],
    ]
    obstacle = parse_obstacle(value)
    assert obstacle.geometry.transform[0][3] == 4.0
    geometry["position_m"] = [0, 0, 0]
    with pytest.raises(ObstacleSchemaError, match="position_m"):
        parse_obstacle(value)


def test_mesh_path_is_resolved_from_scenario_directory(tmp_path: Path):
    value = _box()
    value["geometry"] = {
        "type": "mesh",
        "anchor": {"mode": "explicit_transform"},
        "path": "assets/object.obj",
        "transform": [
            [1, 0, 0, 0],
            [0, 1, 0, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ],
    }
    obstacle = parse_obstacle(value, base_dir=tmp_path)
    assert obstacle.geometry.path == (tmp_path / "assets/object.obj").resolve()


def test_mesh_transform_without_redundant_anchor_implies_explicit_transform(tmp_path: Path):
    value = _box()
    value["geometry"] = {
        "type": "mesh",
        "path": "object.obj",
        "transform": [
            [1, 0, 0, 1],
            [0, 1, 0, 2],
            [0, 0, 1, 3],
            [0, 0, 0, 1],
        ],
    }
    obstacle = parse_obstacle(value, base_dir=tmp_path)
    assert obstacle.geometry.anchor.mode == "explicit_transform"
    assert obstacle.geometry.position_m is None


def test_validation_only_labels_and_duplicate_ids_or_export_names_are_strict():
    invalid = _box(physical_object=True)
    with pytest.raises(ObstacleSchemaError, match="physical_object=false"):
        parse_obstacle(invalid)
    duplicate = _box()
    other = _box(id="blocker_001")
    with pytest.raises(ObstacleSchemaError, match="object_name"):
        parse_obstacles([duplicate, other])
    other["export"]["object_name"] = "blocker_001"
    other["id"] = "blocker_000"
    with pytest.raises(ObstacleSchemaError, match="id"):
        parse_obstacles([duplicate, other])


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "../../outside"),
        ("object_name", "wall/escaped"),
        ("group_name", "bad\nxml"),
    ],
)
def test_filesystem_and_scene_names_reject_path_or_control_characters(field, value):
    obstacle = _box()
    if field == "id":
        obstacle["id"] = value
    else:
        obstacle["export"][field] = value
    with pytest.raises(ObstacleSchemaError, match="경로 문자"):
        parse_obstacle(obstacle)


def test_load_scenario_obstacles_and_empty_document(tmp_path: Path):
    yaml_path = tmp_path / "scenario.yaml"
    yaml_path.write_text(
        """scenario:
  id: empty
  obstacles: []
""",
        encoding="utf-8",
    )
    assert load_obstacles(yaml_path) == []
    assert obstacles_from_document({"scenario": {"obstacles": []}}) == []
