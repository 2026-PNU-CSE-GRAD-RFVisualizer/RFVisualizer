import numpy as np
import pytest

from tools.proxy_mesh_editor.envelope.builder import EnvelopeBuildError, build_room_envelope
from tools.proxy_mesh_editor.envelope.validator import validate_envelope

from tools.proxy_mesh_editor.tests._envelope_test_utils import (
    make_envelope_candidates,
    make_envelope_config,
    rotation_matrix,
)


RECTANGLE = [[-2.0, -4.0], [2.0, -4.0], [2.0, 4.0], [-2.0, 4.0]]


def _build(vertices, rotation=None):
    candidates = make_envelope_candidates(vertices, rotation=rotation)
    config = make_envelope_config(candidates)
    mesh = build_room_envelope(candidates, config)
    topology, geometry, _ = validate_envelope(
        mesh, config["room_envelope"]["validation"]
    )
    return mesh, topology, geometry


def test_rectangular_room_is_closed_and_has_expected_volume():
    mesh, topology, geometry = _build(RECTANGLE)
    assert len(mesh.vertices) == 8
    assert topology["boundary_edge_count"] == 0
    assert topology["non_manifold_edge_count"] == 0
    assert topology["connected_component_count"] == 1
    assert topology["absolute_volume"] == pytest.approx(96.0)
    assert topology["inward_or_ambiguous_face_count"] == 0
    assert geometry["geometry_success"]


def test_rotated_room_does_not_depend_on_world_up_axis():
    mesh, topology, _ = _build(RECTANGLE, rotation=rotation_matrix())
    assert len(mesh.vertices) == 8
    assert topology["closed_manifold_success"]
    assert topology["absolute_volume"] == pytest.approx(96.0, rel=1e-9)


def test_convex_pentagon_room_has_two_vertices_per_wall():
    angles = np.linspace(0.0, 2.0 * np.pi, 6)[:-1]
    pentagon = np.column_stack([3.0 * np.cos(angles), 3.0 * np.sin(angles)])
    mesh, topology, _ = _build(pentagon)
    assert len(mesh.vertices) == 10
    assert topology["closed_manifold_success"]


def test_concave_l_shaped_room_is_closed():
    polygon = [[0.0, 0.0], [3.0, 0.0], [3.0, 1.0], [1.0, 1.0], [1.0, 3.0], [0.0, 3.0]]
    mesh, topology, geometry = _build(polygon)
    assert len(mesh.vertices) == 12
    assert topology["closed_manifold_success"]
    assert geometry["self_intersection_count"] == 0


def test_floor_ceiling_tilt_and_wrong_height_are_rejected():
    candidates = make_envelope_candidates(RECTANGLE)
    config = make_envelope_config(candidates)
    candidates.ceiling.plane_equation = np.asarray([0.5, 0.0, 1.0, -3.0])
    with pytest.raises(EnvelopeBuildError, match="기울기"):
        build_room_envelope(candidates, config)

    candidates = make_envelope_candidates(RECTANGLE)
    config = make_envelope_config(candidates)
    candidates.ceiling.centroid = candidates.floor.centroid - np.asarray([0.0, 0.0, 1.0])
    with pytest.raises(EnvelopeBuildError, match="floor 위"):
        build_room_envelope(candidates, config)


def test_self_intersecting_wall_loop_is_rejected():
    candidates = make_envelope_candidates(
        [[0.0, 0.0], [2.0, 2.0], [0.0, 2.0], [2.0, 0.0]]
    )
    config = make_envelope_config(candidates)
    with pytest.raises(EnvelopeBuildError, match="self-intersection"):
        build_room_envelope(candidates, config)


def test_adjacent_parallel_wall_planes_are_rejected():
    candidates = make_envelope_candidates(RECTANGLE)
    config = make_envelope_config(candidates)
    candidates.walls[1].plane_equation = np.asarray([0.0, -1.0, 0.0, 3.0])
    with pytest.raises(EnvelopeBuildError, match="각도"):
        build_room_envelope(candidates, config)
