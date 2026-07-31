import numpy as np

from tools.sionna_smoke_test.placement import RoomContainment


def _room():
    metadata = {
        "normalized_plane_equations": {
            "floor": [0, 0, 1, 0],
            "ceiling": [0, 0, 1, -2],
            "walls": [
                [1, 0, 0, 0],
                [1, 0, 0, -2],
                [0, 1, 0, 0],
                [0, 1, 0, -2],
            ],
        },
        "interior_point": [1, 1, 1],
        "bounds": {"min": [0, 0, 0], "max": [2, 2, 2]},
    }
    return RoomContainment.from_metadata(metadata)


def test_inside_outside_ceiling_floor_and_near_wall_points():
    room = _room()
    assert room.inspect_point(np.asarray([1, 1, 1]), 0.2)["safe_with_clearance"]
    assert not room.inspect_point(np.asarray([3, 1, 1]), 0.2)["inside_room"]
    assert not room.inspect_point(np.asarray([1, 1, 3]), 0.2)["inside_room"]
    assert not room.inspect_point(np.asarray([1, 1, -1]), 0.2)["inside_room"]
    near_wall = room.inspect_point(np.asarray([0.05, 1, 1]), 0.2)
    assert near_wall["inside_room"]
    assert not near_wall["safe_with_clearance"]


def test_fallback_candidates_are_inside_and_deterministic():
    room = _room()
    first = next(room.fallback_candidates(1.0, 0.2))
    second = next(room.fallback_candidates(1.0, 0.2))
    np.testing.assert_allclose(first, second)
    assert room.inspect_point(first, 0.2)["safe_with_clearance"]


def test_concave_footprint_uses_polygon_instead_of_convex_halfspaces():
    metadata = {
        "normalized_plane_equations": {
            "floor": [0, 0, 1, 0],
            "ceiling": [0, 0, 1, -2],
            "walls": [
                [0, 1, 0, 0],
                [1, 0, 0, -4],
                [0, 1, 0, -4],
                [1, 0, 0, -2],
                [0, 1, 0, -2],
                [1, 0, 0, 0],
            ],
        },
        "interior_point": [3, 1, 1],
        "bounds": {"min": [0, 0, 0], "max": [4, 4, 2]},
        "bottom_corners": [
            [0, 0, 0],
            [4, 0, 0],
            [4, 4, 0],
            [2, 4, 0],
            [2, 2, 0],
            [0, 2, 0],
        ],
    }
    room = RoomContainment.from_metadata(metadata)

    assert room.footprint_is_concave
    assert room.inspect_point(np.asarray([1, 1, 1]), 0.2)["safe_with_clearance"]
    assert room.inspect_point(np.asarray([3, 3, 1]), 0.2)["safe_with_clearance"]
    notch = room.inspect_point(np.asarray([1, 3, 1]), 0.2)
    assert not notch["inside_room"]
    assert notch["minimum_wall_clearance_m"] < 0.0
