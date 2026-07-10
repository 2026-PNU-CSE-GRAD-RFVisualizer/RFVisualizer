"""평면 내부점을 구멍 없는 네 꼭짓점 사각형으로 바꾼다."""

from __future__ import annotations

from typing import Any, Dict, Tuple

import numpy as np

from ..config import normalize_vector
from ..models import PlaneRectangle


class PlaneMeshingError(ValueError):
    """사각형을 만들 수 없는 퇴화한 평면일 때 발생한다."""


def normalize_plane(
    plane_equation: np.ndarray, up_vector: np.ndarray
) -> Tuple[np.ndarray, np.ndarray]:
    model = np.asarray(plane_equation, dtype=float).reshape(4)
    normal_length = float(np.linalg.norm(model[:3]))
    if normal_length <= 1e-12:
        raise PlaneMeshingError("평면 법선의 길이가 0입니다.")
    model = model / normal_length
    normal = model[:3]
    up = normalize_vector(up_vector, "up_vector")

    up_dot = float(np.dot(normal, up))
    if abs(up_dot) > 0.5:
        should_flip = up_dot < 0.0
    else:
        dominant = int(np.argmax(np.abs(normal)))
        should_flip = normal[dominant] < 0.0
    if should_flip:
        model = -model
        normal = -normal
    return model, normal


def _canonical_direction(direction: np.ndarray) -> np.ndarray:
    vector = np.asarray(direction, dtype=float)
    length = float(np.linalg.norm(vector))
    if length <= 1e-12:
        raise PlaneMeshingError("평면의 로컬 축을 계산할 수 없습니다.")
    vector = vector / length
    dominant = int(np.argmax(np.abs(vector)))
    if vector[dominant] < 0.0:
        vector = -vector
    return vector


def _pca_basis(points: np.ndarray, normal: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    centered = points - np.mean(points, axis=0)
    covariance = centered.T @ centered / max(len(points) - 1, 1)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    order = np.argsort(eigenvalues)[::-1]
    basis_u = eigenvectors[:, order[0]]
    basis_u = basis_u - np.dot(basis_u, normal) * normal
    basis_u = _canonical_direction(basis_u)
    basis_v = np.cross(normal, basis_u)
    basis_v = basis_v / np.linalg.norm(basis_v)
    return basis_u, basis_v


def _local_basis(
    projected_points: np.ndarray,
    normal: np.ndarray,
    up_vector: np.ndarray,
    vertical_alignment_max_dot: float,
) -> Tuple[np.ndarray, np.ndarray]:
    up = normalize_vector(up_vector, "up_vector")
    if abs(float(np.dot(normal, up))) <= vertical_alignment_max_dot:
        basis_v = up - np.dot(up, normal) * normal
        basis_v = basis_v / np.linalg.norm(basis_v)
        basis_u = np.cross(basis_v, normal)
        basis_u = _canonical_direction(basis_u)
        # basis_u 부호가 바뀌었을 수 있으므로 법선과 감김 방향을 다시 맞춘다.
        basis_v = np.cross(normal, basis_u)
        basis_v = basis_v / np.linalg.norm(basis_v)
        if np.dot(basis_v, up) < 0.0:
            basis_u = -basis_u
            basis_v = -basis_v
        return basis_u, basis_v
    return _pca_basis(projected_points, normal)


def _expand_minimum_extent(lower: float, upper: float, minimum: float) -> Tuple[float, float]:
    extent = upper - lower
    if extent >= minimum:
        return lower, upper
    center = 0.5 * (lower + upper)
    half = 0.5 * minimum
    return center - half, center + half


def build_plane_rectangle(
    inlier_points: np.ndarray,
    plane_equation: np.ndarray,
    up_vector: np.ndarray,
    settings: Dict[str, Any],
    scene_extent: float,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, PlaneRectangle]:
    points = np.asarray(inlier_points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) < 3:
        raise PlaneMeshingError("사각형 생성에는 3차원 점이 3개 이상 필요합니다.")

    model, normal = normalize_plane(plane_equation, up_vector)
    signed_distances = points @ normal + model[3]
    projected = points - signed_distances[:, None] * normal[None, :]
    origin = np.mean(projected, axis=0)
    basis_u, basis_v = _local_basis(
        projected,
        normal,
        up_vector,
        float(settings["vertical_alignment_max_dot"]),
    )

    relative = projected - origin
    coordinates_u = relative @ basis_u
    coordinates_v = relative @ basis_v
    lower_percentile = float(settings["lower_percentile"])
    upper_percentile = float(settings["upper_percentile"])
    u_min, u_max = np.percentile(
        coordinates_u, [lower_percentile, upper_percentile]
    )
    v_min, v_max = np.percentile(
        coordinates_v, [lower_percentile, upper_percentile]
    )

    margin_ratio = float(settings["margin_ratio"])
    u_margin = max(float(u_max - u_min), 0.0) * margin_ratio
    v_margin = max(float(v_max - v_min), 0.0) * margin_ratio
    u_min, u_max = float(u_min - u_margin), float(u_max + u_margin)
    v_min, v_max = float(v_min - v_margin), float(v_max + v_margin)

    min_extent_value = settings.get("min_extent")
    if min_extent_value is None:
        min_extent = float(settings["min_extent_ratio"]) * float(scene_extent)
    else:
        min_extent = float(min_extent_value)
    if min_extent <= 0.0:
        raise PlaneMeshingError("최소 사각형 길이는 0보다 커야 합니다.")
    u_min, u_max = _expand_minimum_extent(u_min, u_max, min_extent)
    v_min, v_max = _expand_minimum_extent(v_min, v_max, min_extent)

    corners = np.asarray(
        [
            origin + u_min * basis_u + v_min * basis_v,
            origin + u_max * basis_u + v_min * basis_v,
            origin + u_max * basis_u + v_max * basis_v,
            origin + u_min * basis_u + v_max * basis_v,
        ],
        dtype=float,
    )
    width = float(u_max - u_min)
    height = float(v_max - v_min)
    area = width * height
    if not np.isfinite(area) or area <= 1e-12:
        raise PlaneMeshingError("사각형 면적이 0에 가까워 메시를 만들 수 없습니다.")

    winding_normal = np.cross(corners[1] - corners[0], corners[2] - corners[0])
    if float(np.dot(winding_normal, normal)) <= 0.0:
        raise PlaneMeshingError("사각형 꼭짓점 감김 방향이 평면 법선과 맞지 않습니다.")
    if float(np.max(np.abs(corners @ normal + model[3]))) > 1e-7:
        raise PlaneMeshingError("계산된 사각형 꼭짓점이 원래 평면에서 벗어났습니다.")

    rectangle = PlaneRectangle(
        origin=origin,
        basis_u=basis_u,
        basis_v=basis_v,
        bounds_2d={
            "u_min": u_min,
            "u_max": u_max,
            "v_min": v_min,
            "v_max": v_max,
        },
        corners=corners,
        width=width,
        height=height,
        area=area,
    )
    return model, normal, signed_distances, rectangle


def rectangle_triangles() -> np.ndarray:
    return np.asarray([[0, 1, 2], [0, 2, 3]], dtype=np.int32)

