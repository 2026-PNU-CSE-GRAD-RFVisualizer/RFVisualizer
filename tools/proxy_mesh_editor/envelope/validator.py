"""Room Envelope의 기하와 닫힌 다양체 위상을 검사한다."""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from typing import Any, Dict, List, Tuple

import numpy as np

from .builder import EnvelopeMesh
from .polygon import find_self_intersections


class EnvelopeValidationError(ValueError):
    """생성 메시가 Room Envelope 성공 조건을 만족하지 않을 때 발생한다."""


def _triangle_normals_and_areas(
    vertices: np.ndarray, faces: np.ndarray
) -> Tuple[np.ndarray, np.ndarray]:
    first = vertices[faces[:, 0]]
    second = vertices[faces[:, 1]]
    third = vertices[faces[:, 2]]
    cross = np.cross(second - first, third - first)
    lengths = np.linalg.norm(cross, axis=1)
    normals = np.zeros_like(cross)
    valid = lengths > 1e-20
    normals[valid] = cross[valid] / lengths[valid, None]
    return normals, 0.5 * lengths


def _connected_face_components(faces: np.ndarray) -> int:
    edge_to_faces: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    for face_index, face in enumerate(faces):
        for start, end in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            edge_to_faces[tuple(sorted((int(start), int(end))))].append(face_index)
    adjacency: Dict[int, set] = defaultdict(set)
    for attached in edge_to_faces.values():
        for first in attached:
            adjacency[first].update(value for value in attached if value != first)
    remaining = set(range(len(faces)))
    components = 0
    while remaining:
        components += 1
        queue = deque([remaining.pop()])
        while queue:
            current = queue.popleft()
            for neighbor in adjacency[current]:
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    queue.append(neighbor)
    return components


def analyze_topology(mesh: EnvelopeMesh, tolerance: float) -> Dict[str, Any]:
    vertices = np.asarray(mesh.vertices, dtype=float)
    faces = np.asarray(mesh.faces, dtype=int)
    normals, areas = _triangle_normals_and_areas(vertices, faces)
    degenerate = np.flatnonzero(areas <= tolerance * tolerance)

    canonical_faces = [tuple(sorted(int(value) for value in face)) for face in faces]
    duplicate_face_count = int(sum(count - 1 for count in Counter(canonical_faces).values() if count > 1))
    duplicate_vertex_pairs = []
    for first in range(len(vertices)):
        for second in range(first + 1, len(vertices)):
            if float(np.linalg.norm(vertices[first] - vertices[second])) <= tolerance:
                duplicate_vertex_pairs.append([first, second])

    edge_counts: Counter = Counter()
    for face in faces:
        for start, end in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            edge_counts[tuple(sorted((int(start), int(end))))] += 1
    boundary_edges = [list(edge) for edge, count in edge_counts.items() if count == 1]
    non_manifold_edges = [
        {"edge": list(edge), "triangle_count": int(count)}
        for edge, count in edge_counts.items()
        if count > 2
    ]

    signed_volume = float(
        np.sum(
            np.einsum(
                "ij,ij->i",
                vertices[faces[:, 0]],
                np.cross(vertices[faces[:, 1]], vertices[faces[:, 2]]),
            )
        )
        / 6.0
    )
    centroids = np.mean(vertices[faces], axis=1)
    outward_dots = np.einsum("ij,ij->i", normals, mesh.interior_point - centroids)
    inward_faces = np.flatnonzero(outward_dots >= -tolerance)
    report = {
        "vertex_count": int(len(vertices)),
        "triangle_count": int(len(faces)),
        "edge_count": int(len(edge_counts)),
        "degenerate_triangle_count": int(len(degenerate)),
        "degenerate_triangle_indices": degenerate.tolist(),
        "duplicate_face_count": duplicate_face_count,
        "duplicate_vertex_count": int(len(duplicate_vertex_pairs)),
        "duplicate_vertex_pairs": duplicate_vertex_pairs,
        "boundary_edge_count": int(len(boundary_edges)),
        "boundary_edges": boundary_edges,
        "non_manifold_edge_count": int(len(non_manifold_edges)),
        "non_manifold_edges": non_manifold_edges,
        "connected_component_count": int(_connected_face_components(faces)),
        "signed_volume": signed_volume,
        "absolute_volume": abs(signed_volume),
        "surface_area": float(np.sum(areas)),
        "euler_characteristic": int(len(vertices) - len(edge_counts) + len(faces)),
        "inward_or_ambiguous_face_count": int(len(inward_faces)),
        "inward_or_ambiguous_face_indices": inward_faces.tolist(),
    }
    report["closed_manifold_success"] = bool(
        report["boundary_edge_count"] == 0
        and report["non_manifold_edge_count"] == 0
        and report["connected_component_count"] == 1
        and report["degenerate_triangle_count"] == 0
        and report["duplicate_face_count"] == 0
        and report["duplicate_vertex_count"] == 0
        and report["absolute_volume"] > tolerance**3
        and report["inward_or_ambiguous_face_count"] == 0
    )
    return report


def analyze_geometry(mesh: EnvelopeMesh, tolerance: float) -> Dict[str, Any]:
    floor = mesh.normalized_floor_equation
    ceiling = mesh.normalized_ceiling_equation
    bottom_residuals = np.abs(mesh.bottom_corners @ floor[:3] + floor[3])
    top_residuals = np.abs(mesh.top_corners @ ceiling[:3] + ceiling[3])
    wall_residuals = []
    wall_edge_lengths = []
    wall_edge_lengths_by_wall = []
    count = len(mesh.wall_candidates)
    for index, model in enumerate(mesh.normalized_wall_equations):
        following = (index + 1) % count
        quad = np.asarray(
            [
                mesh.bottom_corners[index],
                mesh.bottom_corners[following],
                mesh.top_corners[following],
                mesh.top_corners[index],
            ]
        )
        wall_residuals.append(float(np.max(np.abs(quad @ model[:3] + model[3]))))
        lengths = [
            float(np.linalg.norm(quad[(edge + 1) % 4] - quad[edge]))
            for edge in range(4)
        ]
        wall_edge_lengths.extend(lengths)
        wall_edge_lengths_by_wall.append(lengths)
    bottom_intersections = find_self_intersections(mesh.polygon_2d, tolerance)
    top_intersections = find_self_intersections(mesh.top_polygon_2d, tolerance)
    intersections = bottom_intersections + top_intersections
    finite = bool(
        np.all(np.isfinite(mesh.vertices))
        and np.all(np.isfinite(mesh.faces))
        and np.all(np.isfinite(mesh.interior_point))
    )
    report = {
        "finite_geometry": finite,
        "maximum_bottom_floor_residual": float(np.max(bottom_residuals)),
        "maximum_top_ceiling_residual": float(np.max(top_residuals)),
        "maximum_wall_plane_residual": float(max(wall_residuals)),
        "wall_plane_residuals": wall_residuals,
        "minimum_wall_edge_length": float(min(wall_edge_lengths)),
        "wall_edge_lengths": wall_edge_lengths,
        "wall_edge_lengths_by_wall": wall_edge_lengths_by_wall,
        "bottom_top_vertex_count_match": bool(
            len(mesh.bottom_corners) == len(mesh.top_corners)
        ),
        "self_intersection_count": int(len(intersections)),
        "self_intersections": [list(value) for value in intersections],
        "bottom_self_intersection_count": int(len(bottom_intersections)),
        "top_self_intersection_count": int(len(top_intersections)),
        "height_statistics": mesh.height_statistics,
        "candidate_rectangle_diagnostics": mesh.candidate_rectangle_diagnostics,
    }
    report["geometry_success"] = bool(
        finite
        and report["maximum_bottom_floor_residual"] <= tolerance
        and report["maximum_top_ceiling_residual"] <= tolerance
        and report["maximum_wall_plane_residual"] <= tolerance
        and report["minimum_wall_edge_length"] > tolerance
        and report["bottom_top_vertex_count_match"]
        and report["self_intersection_count"] == 0
        and mesh.height_statistics["minimum"]
        > mesh.height_statistics["required_minimum"]
    )
    return report


def validate_envelope(
    mesh: EnvelopeMesh, validation_settings: Dict[str, Any]
) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    tolerance = float(validation_settings["vertex_merge_tolerance"])
    topology = analyze_topology(mesh, tolerance)
    geometry = analyze_geometry(
        mesh, float(validation_settings["plane_residual_tolerance"])
    )
    errors = []
    if not geometry["geometry_success"]:
        errors.append("기하 검증 실패")
    if validation_settings["require_closed_manifold"] and not topology[
        "closed_manifold_success"
    ]:
        errors.append("닫힌 단일 manifold 위상 검증 실패")
    if errors:
        raise EnvelopeValidationError(
            "Room Envelope 검증에 실패했습니다: {}".format(", ".join(errors))
        )
    return topology, geometry, list(mesh.validation_warnings)
