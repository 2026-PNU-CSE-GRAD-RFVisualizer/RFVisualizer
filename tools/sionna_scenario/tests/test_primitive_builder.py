from pathlib import Path

import numpy as np
import pytest

from tools.sionna_scenario.obstacle_schema import parse_obstacle
from tools.sionna_scenario.primitive_builder import (
    PrimitiveBuildError,
    build_obstacle_mesh,
    create_box_mesh,
    create_thin_panel_mesh,
    load_external_mesh,
)
from tools.sionna_smoke_test.placement import RoomContainment


def _obstacle(geometry):
    return parse_obstacle(
        {
            "id": "object_000",
            "enabled": True,
            "semantic_class": "test_object",
            "purpose": "test",
            "physical_object": False,
            "confidence": "synthetic",
            "geometry": geometry,
            "material": {"category": "wood"},
        }
    )


def _sloped_room():
    # floor z = 0.1*x + 0.2*y, ceiling z = 5
    metadata = {
        "normalized_plane_equations": {
            "floor": [-0.1, -0.2, 1.0, 0.0],
            "ceiling": [0.0, 0.0, 1.0, -5.0],
            "walls": [
                [1, 0, 0, 0],
                [1, 0, 0, -10],
                [0, 1, 0, 0],
                [0, 1, 0, -10],
            ],
        },
        "interior_point": [5, 5, 3],
        "bounds": {"min": [0, 0, 0], "max": [10, 10, 5]},
    }
    return RoomContainment.from_metadata(metadata)


def test_box_has_expected_counts_bounds_winding_area_and_positive_volume():
    mesh = create_box_mesh([2, 3, 4])
    statistics = mesh.statistics()
    assert mesh.vertex_count == 8
    assert mesh.triangle_count == 12
    np.testing.assert_allclose(mesh.bounds_min, [-1, -1.5, -2])
    np.testing.assert_allclose(mesh.bounds_max, [1, 1.5, 2])
    assert statistics["surface_area"] == pytest.approx(52.0)
    assert statistics["signed_volume"] == pytest.approx(24.0)
    assert statistics["strictly_outward_face_count"] == 12
    assert statistics["closed_manifold"]


def test_center_bottom_center_and_yaw_rotation_transforms():
    center = _obstacle(
        {
            "type": "box",
            "anchor": "center",
            "position_m": [10, 20, 30],
            "size_m": [2, 4, 6],
            "rotation_deg": [0, 0, 90],
        }
    )
    centered = build_obstacle_mesh(center)
    np.testing.assert_allclose((centered.bounds_min + centered.bounds_max) / 2, [10, 20, 30], atol=1e-12)
    np.testing.assert_allclose(centered.bounds_max - centered.bounds_min, [4, 2, 6], atol=1e-12)

    bottom = _obstacle(
        {
            "type": "box",
            "anchor": "bottom_center",
            "position_m": [1, 2, 3],
            "size_m": [2, 4, 6],
        }
    )
    bottom_mesh = build_obstacle_mesh(bottom)
    assert bottom_mesh.bounds_min[2] == pytest.approx(3.0)
    np.testing.assert_allclose((bottom_mesh.bounds_min[:2] + bottom_mesh.bounds_max[:2]) / 2, [1, 2])


def test_floor_at_xy_uses_sloped_floor_height_and_clearance():
    obstacle = _obstacle(
        {
            "type": "box",
            "anchor": "floor_at_xy",
            "position_m": {"x": 2.0, "y": 3.0},
            "size_m": [0.5, 0.5, 1.0],
            "floor_clearance_m": 0.25,
        }
    )
    mesh = build_obstacle_mesh(obstacle, room=_sloped_room())
    # z_floor(2, 3) = 0.8, and the primitive bottom is the anchor.
    assert mesh.bounds_min[2] == pytest.approx(1.05)
    assert mesh.transform[2, 3] == pytest.approx(1.55)


def test_thin_panel_axis_convention_and_volume():
    panel = create_thin_panel_mesh(width_m=2.5, height_m=2.0, thickness_m=0.15)
    np.testing.assert_allclose(panel.bounds_max - panel.bounds_min, [0.15, 2.5, 2.0])
    assert panel.geometry_type == "thin_panel"
    assert panel.statistics()["signed_volume"] == pytest.approx(0.75)


def test_explicit_transform_and_reflection_keep_positive_winding():
    obstacle = _obstacle(
        {
            "type": "box",
            "anchor": "explicit_transform",
            "size_m": [1, 2, 3],
            "transform": [
                [-1, 0, 0, 4],
                [0, 1, 0, 5],
                [0, 0, 1, 6],
                [0, 0, 0, 1],
            ],
        }
    )
    mesh = build_obstacle_mesh(obstacle)
    assert mesh.statistics()["signed_volume"] == pytest.approx(6.0)
    np.testing.assert_allclose((mesh.bounds_min + mesh.bounds_max) / 2, [4, 5, 6])


def test_external_obj_interface_triangulates_and_applies_transform(tmp_path: Path):
    source = tmp_path / "box.obj"
    source.write_text(
        """v -1 -1 0
v 1 -1 0
v 1 1 0
v -1 1 0
v -1 -1 1
v 1 -1 1
v 1 1 1
v -1 1 1
f 1 3 2
f 1 4 3
f 5 6 7
f 5 7 8
f 1 2 6
f 1 6 5
f 2 3 7
f 2 7 6
f 3 4 8
f 3 8 7
f 4 1 5
f 4 5 8
""",
        encoding="utf-8",
    )
    local = load_external_mesh(source)
    assert local.vertex_count == 8
    assert local.triangle_count == 12
    obstacle = _obstacle(
        {
            "type": "mesh",
            "path": str(source),
            "anchor": "explicit_transform",
            "transform": [
                [1, 0, 0, 3],
                [0, 1, 0, 4],
                [0, 0, 1, 5],
                [0, 0, 0, 1],
            ],
        }
    )
    world = build_obstacle_mesh(obstacle)
    np.testing.assert_allclose(world.bounds_min, [2, 3, 5])
    np.testing.assert_allclose(world.bounds_max, [4, 5, 6])


def test_disabled_obstacle_and_unknown_external_format_fail_clearly(tmp_path: Path):
    value = {
        "id": "draft",
        "enabled": False,
        "semantic_class": "desk",
        "purpose": "classroom_proxy",
        "physical_object": True,
        "confidence": "unset",
        "geometry": {"type": "box", "position_m": None, "size_m": None},
        "material": {"category": "wood"},
    }
    with pytest.raises(PrimitiveBuildError, match="비활성"):
        build_obstacle_mesh(parse_obstacle(value))
    source = tmp_path / "mesh.stl"
    source.write_text("solid", encoding="utf-8")
    with pytest.raises(PrimitiveBuildError, match="OBJ 또는 ASCII PLY"):
        load_external_mesh(source)
