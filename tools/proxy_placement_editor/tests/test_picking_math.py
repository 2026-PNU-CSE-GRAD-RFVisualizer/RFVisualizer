import numpy as np

from tools.proxy_placement_editor.picking import (
    nearest_obstacle_hit,
    ray_plane_intersection,
    ray_triangle_intersection,
)


def test_ray_plane_intersection():
    hit = ray_plane_intersection(
        np.array([0, 0, 1.0]), np.array([0, 0, -1.0]), np.array([0, 0, 1.0, 0])
    )
    assert np.allclose(hit, [0, 0, 0])


def test_ray_triangle_and_nearest_obstacle_selection_ignores_room_layer():
    vertices = np.array([[-1, -1, 0], [1, -1, 0], [0, 1, 0]], dtype=float)
    faces = np.array([[0, 1, 2]])
    hit = ray_triangle_intersection(
        np.array([0, 0, 2]), np.array([0, 0, -1]), vertices[faces[0]]
    )
    assert np.isclose(hit[0], 2.0)
    near = nearest_obstacle_hit(
        np.array([0, 0, 2]),
        np.array([0, 0, -1]),
        [("far", vertices - [0, 0, 1], faces), ("near", vertices, faces)],
    )
    assert near["object_id"] == "near"


def test_parallel_or_behind_ray_has_no_hit():
    assert (
        ray_plane_intersection(
            np.zeros(3), np.array([1, 0, 0]), np.array([0, 0, 1, -1])
        )
        is None
    )
