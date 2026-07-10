"""선택된 무한 평면으로 공유 꼭짓점 Room Envelope를 생성한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np

from ..models import PlaneCandidate
from .candidate_loader import EnvelopeCandidates
from .intersections import (
    acute_plane_angle_degrees,
    compute_ordered_corners,
    normalize_plane_equation,
)
from .polygon import (
    PolygonError,
    ear_clip_triangulation,
    edge_lengths,
    find_self_intersections,
    plane_basis,
    point_in_polygon,
    polygon_centroid,
    project_to_basis,
    signed_area,
)


class EnvelopeBuildError(ValueError):
    """선택 평면이 닫힌 방 외곽을 만들지 못할 때 발생한다."""


@dataclass
class EnvelopeMesh:
    vertices: np.ndarray
    faces: np.ndarray
    face_objects: List[str]
    face_semantics: List[str]
    bottom_corners: np.ndarray
    top_corners: np.ndarray
    polygon_2d: np.ndarray
    top_polygon_2d: np.ndarray
    polygon_signed_area: float
    polygon_winding: str
    polygon_edge_lengths: np.ndarray
    interior_point: np.ndarray
    floor_candidate: PlaneCandidate
    ceiling_candidate: PlaneCandidate
    wall_candidates: List[PlaneCandidate]
    normalized_floor_equation: np.ndarray
    normalized_ceiling_equation: np.ndarray
    normalized_wall_equations: List[np.ndarray]
    input_wall_ids: List[str]
    normalized_wall_ids: List[str]
    intersection_diagnostics: List[Dict[str, Any]]
    candidate_rectangle_diagnostics: List[Dict[str, Any]]
    height_statistics: Dict[str, float]
    orientation_flip_count: int
    validation_warnings: List[str]


def _scene_extent(candidates: EnvelopeCandidates) -> float:
    scene = candidates.plane_document.get("scene", {})
    value = scene.get("estimated_extent")
    if value is None:
        value = scene.get("bounds", {}).get("diagonal")
    if value is None or not np.isfinite(float(value)) or float(value) <= 0.0:
        raise EnvelopeBuildError("일반 후보 문서에서 유효한 장면 크기를 찾지 못했습니다.")
    return float(value)


def _surface_centroid(vertices: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    weighted = np.zeros(3, dtype=float)
    total_area = 0.0
    for triangle in triangles:
        points = vertices[np.asarray(triangle, dtype=int)]
        area = 0.5 * float(np.linalg.norm(np.cross(points[1] - points[0], points[2] - points[0])))
        weighted += area * np.mean(points, axis=0)
        total_area += area
    if total_area <= 1e-12:
        raise EnvelopeBuildError("바닥 또는 천장 면적이 0에 가깝습니다.")
    return weighted / total_area


def _oriented_room_planes(
    floor_equation: np.ndarray,
    ceiling_equation: np.ndarray,
    up_vector: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    floor = normalize_plane_equation(floor_equation)
    ceiling = normalize_plane_equation(ceiling_equation)
    if float(np.dot(floor[:3], up_vector)) < 0.0:
        floor = -floor
    if float(np.dot(ceiling[:3], up_vector)) > 0.0:
        ceiling = -ceiling
    return floor, ceiling


def _resolve_interior_point(
    configured: Any,
    bottom: np.ndarray,
    top: np.ndarray,
    polygon_2d: np.ndarray,
    triangles: np.ndarray,
    origin: np.ndarray,
    basis_u: np.ndarray,
    basis_v: np.ndarray,
    floor_equation: np.ndarray,
    ceiling_equation: np.ndarray,
    up_vector: np.ndarray,
    tolerance: float,
) -> Tuple[np.ndarray, List[str]]:
    warnings: List[str] = []
    if configured is not None:
        interior = np.asarray(configured, dtype=float)
    else:
        centroid_2d = polygon_centroid(polygon_2d)
        if point_in_polygon(centroid_2d, polygon_2d, tolerance):
            bottom_centroid = _surface_centroid(bottom, triangles)
            top_centroid = _surface_centroid(top, triangles)
            interior = 0.5 * (bottom_centroid + top_centroid)
        else:
            first_triangle = triangles[0]
            bottom_centroid = np.mean(bottom[first_triangle], axis=0)
            top_centroid = np.mean(top[first_triangle], axis=0)
            interior = 0.5 * (bottom_centroid + top_centroid)
            warnings.append(
                "다각형 면적 중심이 외부에 있어 첫 내부 삼각형 중심으로 interior_point를 추정했습니다."
            )

    projected = project_to_basis(interior[None, :], origin, basis_u, basis_v)[0]
    if not point_in_polygon(projected, polygon_2d, tolerance):
        raise EnvelopeBuildError("interior_point가 바닥 다각형 내부에 있지 않습니다.")
    floor_inward, ceiling_inward = _oriented_room_planes(
        floor_equation, ceiling_equation, up_vector
    )
    floor_side = float(np.dot(floor_inward[:3], interior) + floor_inward[3])
    ceiling_side = float(np.dot(ceiling_inward[:3], interior) + ceiling_inward[3])
    if floor_side <= tolerance or ceiling_side <= tolerance:
        raise EnvelopeBuildError("interior_point가 floor와 ceiling 사이에 있지 않습니다.")
    return interior, warnings


def _orient_faces_outward(
    vertices: np.ndarray, faces: np.ndarray, interior_point: np.ndarray
) -> Tuple[np.ndarray, int]:
    oriented = np.asarray(faces, dtype=int).copy()
    flips = 0
    for index, face in enumerate(oriented):
        points = vertices[face]
        normal = np.cross(points[1] - points[0], points[2] - points[0])
        centroid = np.mean(points, axis=0)
        if float(np.dot(normal, interior_point - centroid)) > 0.0:
            oriented[index, [1, 2]] = oriented[index, [2, 1]]
            flips += 1
    return oriented, flips


def _bounds_2d(points: np.ndarray, origin: np.ndarray, u: np.ndarray, v: np.ndarray) -> Dict[str, float]:
    coordinates = project_to_basis(points, origin, u, v)
    return {
        "u_min": float(np.min(coordinates[:, 0])),
        "u_max": float(np.max(coordinates[:, 0])),
        "v_min": float(np.min(coordinates[:, 1])),
        "v_max": float(np.max(coordinates[:, 1])),
    }


def _aabb_area(bounds: Dict[str, float]) -> float:
    return max(bounds["u_max"] - bounds["u_min"], 0.0) * max(
        bounds["v_max"] - bounds["v_min"], 0.0
    )


def _overlap_area(first: Dict[str, float], second: Dict[str, float]) -> float:
    width = max(min(first["u_max"], second["u_max"]) - max(first["u_min"], second["u_min"]), 0.0)
    height = max(min(first["v_max"], second["v_max"]) - max(first["v_min"], second["v_min"]), 0.0)
    return width * height


def _candidate_rectangle_diagnostics(
    bottom: np.ndarray,
    top: np.ndarray,
    wall_candidates: Sequence[PlaneCandidate],
    wall_equations: Sequence[np.ndarray],
    tolerance: float,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    diagnostics = []
    warnings = []
    count = len(wall_candidates)
    for index, candidate in enumerate(wall_candidates):
        following = (index + 1) % count
        quad = np.asarray([bottom[index], bottom[following], top[following], top[index]])
        rectangle = candidate.rectangle
        generated_bounds = _bounds_2d(
            quad, rectangle.origin, rectangle.basis_u, rectangle.basis_v
        )
        candidate_bounds = _bounds_2d(
            rectangle.corners, rectangle.origin, rectangle.basis_u, rectangle.basis_v
        )
        generated_area = _aabb_area(generated_bounds)
        candidate_area = _aabb_area(candidate_bounds)
        overlap = _overlap_area(generated_bounds, candidate_bounds)
        model = wall_equations[index]
        residual = np.abs(quad @ model[:3] + model[3])
        record = {
            "wall_object_name": "wall_{:03d}".format(index),
            "candidate_id": candidate.candidate_id,
            "generated_to_candidate_center_distance": float(
                np.linalg.norm(np.mean(quad, axis=0) - rectangle.origin)
            ),
            "maximum_wall_plane_residual": float(np.max(residual)),
            "generated_projected_bounds": generated_bounds,
            "candidate_projected_bounds": candidate_bounds,
            "generated_projected_aabb_area": generated_area,
            "candidate_projected_aabb_area": candidate_area,
            "projected_aabb_overlap_area": overlap,
            "generated_coverage_ratio": float(overlap / max(generated_area, 1e-12)),
            "candidate_coverage_ratio": float(overlap / max(candidate_area, 1e-12)),
        }
        if float(np.max(residual)) > tolerance:
            raise EnvelopeBuildError(
                "생성 벽 {}가 선택 평면에서 벗어났습니다.".format(candidate.candidate_id)
            )
        if overlap <= tolerance:
            warnings.append(
                "생성 벽 {}와 후보 사각형의 투영 범위가 겹치지 않습니다.".format(
                    candidate.candidate_id
                )
            )
        diagnostics.append(record)
    return diagnostics, warnings


def _compute_polygon_state(
    floor: np.ndarray,
    ceiling: np.ndarray,
    walls: Sequence[PlaneCandidate],
    validation: Dict[str, Any],
    up: np.ndarray,
) -> Tuple[
    np.ndarray,
    np.ndarray,
    List[Dict[str, Any]],
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    float,
]:
    wall_models = [normalize_plane_equation(candidate.plane_equation) for candidate in walls]
    wall_ids = [candidate.candidate_id for candidate in walls]
    bottom, top, intersections = compute_ordered_corners(
        floor, ceiling, wall_models, wall_ids, validation
    )
    origin, basis_u, basis_v, _ = plane_basis(floor, up)
    polygon_2d = project_to_basis(bottom, origin, basis_u, basis_v)
    return (
        bottom,
        top,
        intersections,
        polygon_2d,
        origin,
        basis_u,
        basis_v,
        signed_area(polygon_2d),
    )


def build_room_envelope(
    candidates: EnvelopeCandidates, envelope_config: Dict[str, Any]
) -> EnvelopeMesh:
    room = envelope_config["room_envelope"]
    if not room["enabled"]:
        raise EnvelopeBuildError("room_envelope.enabled가 false입니다.")
    validation = room["validation"]
    tolerance = float(validation["plane_residual_tolerance"])
    vertex_tolerance = float(validation["vertex_merge_tolerance"])
    up = np.asarray(candidates.up_vector, dtype=float)
    up = up / np.linalg.norm(up)

    floor = normalize_plane_equation(candidates.floor.plane_equation)
    ceiling = normalize_plane_equation(candidates.ceiling.plane_equation)
    floor_ceiling_angle = acute_plane_angle_degrees(floor, ceiling)
    if floor_ceiling_angle > float(validation["floor_ceiling_max_angle_deg"]):
        raise EnvelopeBuildError(
            "floor와 ceiling의 기울기 차이가 허용값을 넘습니다: {:.6g}도".format(
                floor_ceiling_angle
            )
        )
    floor_candidate_height = float(np.dot(candidates.floor.centroid, up))
    ceiling_candidate_height = float(np.dot(candidates.ceiling.centroid, up))
    if ceiling_candidate_height <= floor_candidate_height:
        raise EnvelopeBuildError("선택한 ceiling이 up vector 기준으로 floor 위에 있지 않습니다.")

    input_wall_ids = [candidate.candidate_id for candidate in candidates.walls]
    walls = list(candidates.walls)
    for candidate in walls:
        model = normalize_plane_equation(candidate.plane_equation)
        up_dot = float(abs(np.dot(model[:3], up)))
        if up_dot > float(validation["wall_max_up_dot"]):
            raise EnvelopeBuildError(
                "{}의 법선-높이 내적 {:.6g}이 벽 기준을 넘습니다.".format(
                    candidate.candidate_id, up_dot
                )
            )

    try:
        state = _compute_polygon_state(floor, ceiling, walls, validation, up)
    except (ValueError, PolygonError) as exc:
        raise EnvelopeBuildError(str(exc)) from exc
    bottom, top, intersections, polygon_2d, origin, basis_u, basis_v, area = state
    initial_self_intersections = find_self_intersections(polygon_2d, vertex_tolerance)
    if initial_self_intersections:
        raise EnvelopeBuildError(
            "벽 순서로 만든 바닥 다각형에 self-intersection이 있습니다: {}".format(
                initial_self_intersections
            )
        )
    if area < 0.0:
        walls = list(reversed(walls))
        try:
            state = _compute_polygon_state(floor, ceiling, walls, validation, up)
        except (ValueError, PolygonError) as exc:
            raise EnvelopeBuildError(str(exc)) from exc
        bottom, top, intersections, polygon_2d, origin, basis_u, basis_v, area = state
    if area <= tolerance:
        raise EnvelopeBuildError("바닥 다각형 면적이 0에 가깝습니다.")

    polygon_self_intersections = find_self_intersections(polygon_2d, vertex_tolerance)
    if polygon_self_intersections:
        raise EnvelopeBuildError(
            "벽 순서로 만든 바닥 다각형에 self-intersection이 있습니다: {}".format(
                polygon_self_intersections
            )
        )
    lengths = edge_lengths(polygon_2d)
    if np.any(lengths <= vertex_tolerance):
        raise EnvelopeBuildError("바닥 다각형에 길이가 0에 가까운 모서리가 있습니다.")
    top_origin, top_basis_u, top_basis_v, _ = plane_basis(ceiling, up)
    top_polygon_2d = project_to_basis(top, top_origin, top_basis_u, top_basis_v)
    top_self_intersections = find_self_intersections(top_polygon_2d, vertex_tolerance)
    if top_self_intersections:
        raise EnvelopeBuildError(
            "천장 다각형에 self-intersection이 있습니다: {}".format(
                top_self_intersections
            )
        )
    if np.any(edge_lengths(top_polygon_2d) <= vertex_tolerance):
        raise EnvelopeBuildError("천장 다각형에 길이가 0에 가까운 모서리가 있습니다.")

    try:
        triangles = ear_clip_triangulation(polygon_2d, vertex_tolerance)
    except PolygonError as exc:
        raise EnvelopeBuildError(str(exc)) from exc

    heights = (top - bottom) @ up
    minimum_height = validation.get("minimum_height")
    if minimum_height is None:
        minimum_height = float(validation["minimum_height_ratio"]) * _scene_extent(candidates)
    minimum_height = float(minimum_height)
    if np.any(~np.isfinite(heights)) or float(np.min(heights)) <= minimum_height:
        raise EnvelopeBuildError(
            "floor-ceiling 높이가 최소값 이하입니다: 최소 {:.6g}, 기준 {:.6g}".format(
                float(np.min(heights)), minimum_height
            )
        )

    interior, warnings = _resolve_interior_point(
        room.get("interior_point"),
        bottom,
        top,
        polygon_2d,
        triangles,
        origin,
        basis_u,
        basis_v,
        floor,
        ceiling,
        up,
        tolerance,
    )

    count = len(walls)
    vertices = np.vstack([bottom, top])
    faces: List[List[int]] = []
    face_objects: List[str] = []
    face_semantics: List[str] = []
    for triangle in triangles:
        faces.append([int(triangle[0]), int(triangle[2]), int(triangle[1])])
        face_objects.append("floor_000")
        face_semantics.append("floor")
    for triangle in triangles:
        faces.append([int(triangle[0] + count), int(triangle[1] + count), int(triangle[2] + count)])
        face_objects.append("ceiling_000")
        face_semantics.append("ceiling")
    for index in range(count):
        following = (index + 1) % count
        faces.extend(
            [
                [index, following, count + following],
                [index, count + following, count + index],
            ]
        )
        face_objects.extend(["wall_{:03d}".format(index)] * 2)
        face_semantics.extend(["wall"] * 2)
    face_array, flips = _orient_faces_outward(
        vertices, np.asarray(faces, dtype=int), interior
    )

    wall_models = [normalize_plane_equation(candidate.plane_equation) for candidate in walls]
    rectangle_diagnostics, rectangle_warnings = _candidate_rectangle_diagnostics(
        bottom, top, walls, wall_models, tolerance
    )
    warnings.extend(rectangle_warnings)
    return EnvelopeMesh(
        vertices=vertices,
        faces=face_array,
        face_objects=face_objects,
        face_semantics=face_semantics,
        bottom_corners=bottom,
        top_corners=top,
        polygon_2d=polygon_2d,
        top_polygon_2d=top_polygon_2d,
        polygon_signed_area=float(area),
        polygon_winding="counter_clockwise_from_up",
        polygon_edge_lengths=lengths,
        interior_point=interior,
        floor_candidate=candidates.floor,
        ceiling_candidate=candidates.ceiling,
        wall_candidates=walls,
        normalized_floor_equation=floor,
        normalized_ceiling_equation=ceiling,
        normalized_wall_equations=wall_models,
        input_wall_ids=input_wall_ids,
        normalized_wall_ids=[candidate.candidate_id for candidate in walls],
        intersection_diagnostics=intersections,
        candidate_rectangle_diagnostics=rectangle_diagnostics,
        height_statistics={
            "minimum": float(np.min(heights)),
            "maximum": float(np.max(heights)),
            "mean": float(np.mean(heights)),
            "required_minimum": minimum_height,
            "floor_candidate_height": floor_candidate_height,
            "ceiling_candidate_height": ceiling_candidate_height,
            "floor_ceiling_plane_angle_deg": floor_ceiling_angle,
        },
        orientation_flip_count=flips,
        validation_warnings=warnings,
    )
