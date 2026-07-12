import pytest

from tools.sionna_scenario.obstacle_schema import parse_obstacle
from tools.sionna_scenario.obstacle_validator import (
    ObstacleValidationError,
    inspect_obstacle,
    point_inside_mesh,
    segment_intersects_aabb,
    segment_intersects_mesh,
    segment_mesh_intersections,
    validate_los_intersection,
    validate_obstacle,
)
from tools.sionna_scenario.primitive_builder import build_obstacle_mesh
from tools.sionna_smoke_test.placement import RoomContainment


def _room():
    return RoomContainment.from_metadata(
        {
            "normalized_plane_equations": {
                "floor": [0, 0, 1, 0],
                "ceiling": [0, 0, 1, -4],
                "walls": [
                    [1, 0, 0, 0],
                    [1, 0, 0, -6],
                    [0, 1, 0, 0],
                    [0, 1, 0, -6],
                ],
            },
            "interior_point": [3, 3, 2],
            "bounds": {"min": [0, 0, 0], "max": [6, 6, 4]},
        }
    )


def _box(center=(3, 3, 2), size=(0.2, 2, 2)):
    spec = parse_obstacle(
        {
            "id": "blocker",
            "enabled": True,
            "semantic_class": "validation_blocker",
            "purpose": "validation_only",
            "physical_object": False,
            "confidence": "synthetic",
            "geometry": {
                "type": "box",
                "anchor": "center",
                "position_m": list(center),
                "size_m": list(size),
            },
            "material": {"category": "wood"},
        }
    )
    return build_obstacle_mesh(spec)


def test_segment_triangle_and_aabb_intersection_are_exact_for_blocker():
    mesh = _box()
    start, end = [1, 3, 2], [5, 3, 2]
    assert segment_intersects_aabb(start, end, mesh.bounds_min, mesh.bounds_max)
    assert segment_intersects_mesh(start, end, mesh)
    hits = segment_mesh_intersections(start, end, mesh)
    assert len(hits) == 2
    assert hits[0]["point_m"][0] == pytest.approx(2.9)
    assert hits[1]["point_m"][0] == pytest.approx(3.1)
    assert not segment_intersects_mesh([1, 5, 2], [5, 5, 2], mesh)


def test_point_inside_mesh_includes_surface_and_excludes_devices_outside():
    mesh = _box()
    assert point_inside_mesh([3, 3, 2], mesh)
    assert point_inside_mesh([2.9, 3, 2], mesh)
    assert not point_inside_mesh([1, 3, 2], mesh)


def test_valid_blocker_is_contained_and_required_los_intersects():
    report = validate_obstacle(
        _box(),
        _room(),
        transmitter=[1, 3, 2],
        receiver=[5, 3, 2],
        require_los_intersection=True,
    )
    assert report["success"]
    assert report["containment"]["fully_inside"]
    assert report["los"]["any_intersection"]
    assert report["checks"]["devices_outside_obstacle"]


@pytest.mark.parametrize(
    "center,size,failed_check",
    [
        ((0.1, 3, 2), (1, 1, 1), "inside_walls"),
        ((-2, 3, 2), (1, 1, 1), "inside_walls"),
        ((3, 3, 0.1), (1, 1, 1), "on_or_above_floor"),
        ((3, 3, 3.9), (1, 1, 1), "on_or_below_ceiling"),
    ],
)
def test_wall_outside_floor_and_ceiling_failures_are_distinguished(center, size, failed_check):
    report = inspect_obstacle(_box(center, size), _room())
    assert not report["success"]
    assert not report["checks"][failed_check]
    with pytest.raises(ObstacleValidationError) as captured:
        validate_obstacle(_box(center, size), _room())
    assert captured.value.report["checks"][failed_check] is False


def test_missing_required_los_and_device_inside_are_failures():
    mesh = _box()
    no_hit = inspect_obstacle(
        mesh,
        _room(),
        transmitter=[1, 5, 2],
        receiver=[5, 5, 2],
        require_los_intersection=True,
    )
    assert not no_hit["checks"]["required_los_intersection"]
    endpoint_inside = inspect_obstacle(
        mesh,
        _room(),
        transmitter=[3, 3, 2],
        receiver=[5, 3, 2],
        require_los_intersection=True,
    )
    assert not endpoint_inside["checks"]["devices_outside_obstacle"]


def test_standalone_los_validation_requires_intersection_and_external_endpoints():
    mesh = _box()
    result = validate_los_intersection(mesh, [1, 3, 2], [5, 3, 2])
    assert result["success"]
    with pytest.raises(ObstacleValidationError):
        validate_los_intersection(mesh, [1, 5, 2], [5, 5, 2])
    with pytest.raises(ObstacleValidationError):
        validate_los_intersection(mesh, [3, 3, 2], [5, 3, 2])
