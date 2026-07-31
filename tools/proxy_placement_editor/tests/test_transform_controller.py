import numpy as np
import pytest

from tools.proxy_placement_editor.transform_controller import (
    TransformError,
    resize_obstacle,
    rotate_point_about_pivot,
    rotate_obstacle,
    rotate_obstacle_in_space,
    scale_point_about_pivot,
    translate_obstacle,
)


def obstacle():
    return {
        "geometry": {
            "anchor": {"mode": "center"},
            "position_m": [1.0, 2.0, 3.0],
            "size_m": [1.0, 2.0, 3.0],
            "rotation_deg": [0.0, 0.0, 0.0],
        }
    }


def test_translate_axis_constraint_and_snap():
    value = translate_obstacle(
        obstacle(), [0.13, 2.0, 3.0], axis="x", snap_increment_m=0.05, snap_enabled=True
    )
    assert np.allclose(list(value["geometry"]["position_m"].values()), [1.15, 2.0, 3.0])


def test_yaw_rotation_and_angle_snap():
    value = rotate_obstacle(obstacle(), 12.0, snap_increment_deg=5.0, snap_enabled=True)
    assert value["geometry"]["rotation_deg"]["yaw"] == 10.0


def test_uniform_and_axis_scale():
    uniform = resize_obstacle(obstacle(), 2.0)
    assert uniform["geometry"]["size_m"] == {"x": 2.0, "y": 4.0, "z": 6.0}
    axis = resize_obstacle(obstacle(), 2.0, axis="y")
    assert axis["geometry"]["size_m"] == {"x": 1.0, "y": 4.0, "z": 3.0}


def test_non_positive_scale_is_rejected():
    with pytest.raises(TransformError):
        resize_obstacle(obstacle(), 0.0)


def test_floor_at_xy_z_translation_changes_clearance_not_position_dimension():
    value = obstacle()
    value["geometry"]["anchor"] = {
        "mode": "floor_at_xy",
        "floor_contact_policy": {
            "type": "minimum_bottom_vertex_clearance",
            "clearance_m": 0.02,
        },
    }
    value["geometry"]["position_m"] = [1.0, 2.0]
    result = translate_obstacle(value, [0.0, 0.0, 0.1])
    assert result["geometry"]["position_m"] == {"x": 1.0, "y": 2.0}
    assert np.isclose(
        result["geometry"]["anchor"]["floor_contact_policy"]["clearance_m"], 0.12
    )


def test_world_and_local_rotation_composition_are_distinct_and_valid():
    value = obstacle()
    value["geometry"]["rotation_deg"] = [0.0, 0.0, 90.0]
    world = rotate_obstacle_in_space(value, 90.0, axis="x", space="world")
    local = rotate_obstacle_in_space(value, 90.0, axis="x", space="local")
    world_rotation = list(world["geometry"]["rotation_deg"].values())
    local_rotation = list(local["geometry"]["rotation_deg"].values())
    assert not np.allclose(world_rotation, local_rotation)
    assert np.all(np.isfinite(world_rotation))
    assert np.all(np.isfinite(local_rotation))


def test_group_rotation_and_scale_move_centers_around_shared_pivot():
    rotated = rotate_point_about_pivot(
        [2.0, 1.0, 0.5], [1.0, 1.0, 0.5], "z", 90.0
    )
    scaled = scale_point_about_pivot(
        [2.0, 1.0, 0.5], [1.0, 1.0, 0.5], "x", 2.5
    )

    np.testing.assert_allclose(rotated, [1.0, 2.0, 0.5], atol=1.0e-12)
    np.testing.assert_allclose(scaled, [3.5, 1.0, 0.5], atol=1.0e-12)
