"""무한 평면 정규화와 세 평면 교점을 계산한다."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

import numpy as np


class PlaneIntersectionError(ValueError):
    """평면이 유효하지 않거나 안정적인 교점을 만들 수 없을 때 발생한다."""


def normalize_plane_equation(equation: np.ndarray) -> np.ndarray:
    model = np.asarray(equation, dtype=float)
    if model.shape != (4,) or not np.all(np.isfinite(model)):
        raise PlaneIntersectionError("평면식은 유한한 숫자 4개여야 합니다.")
    length = float(np.linalg.norm(model[:3]))
    if length <= 1e-12:
        raise PlaneIntersectionError("평면 법선 길이가 0입니다.")
    return model / length


def acute_plane_angle_degrees(first: np.ndarray, second: np.ndarray) -> float:
    first_model = normalize_plane_equation(first)
    second_model = normalize_plane_equation(second)
    cosine = float(np.clip(abs(np.dot(first_model[:3], second_model[:3])), 0.0, 1.0))
    return float(np.degrees(np.arccos(cosine)))


def solve_three_plane_intersection(
    equations: Sequence[np.ndarray],
    residual_tolerance: float,
    max_condition_number: float,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    if len(equations) != 3:
        raise PlaneIntersectionError("세 평면 교점 계산에는 평면식 3개가 필요합니다.")
    models = np.asarray([normalize_plane_equation(value) for value in equations])
    matrix = models[:, :3]
    right = -models[:, 3]
    determinant = float(np.linalg.det(matrix))
    condition = float(np.linalg.cond(matrix))
    if not np.isfinite(determinant) or abs(determinant) <= 1e-12:
        raise PlaneIntersectionError("세 평면 교차 행렬이 singular합니다.")
    if not np.isfinite(condition) or condition > float(max_condition_number):
        raise PlaneIntersectionError(
            "세 평면 교차 행렬의 condition number가 너무 큽니다: {:.6g}".format(condition)
        )
    try:
        point = np.linalg.solve(matrix, right)
    except np.linalg.LinAlgError as exc:
        raise PlaneIntersectionError("세 평면 교점을 계산할 수 없습니다.") from exc
    residuals = np.abs(matrix @ point + models[:, 3])
    if not np.all(np.isfinite(point)) or float(np.max(residuals)) > residual_tolerance:
        raise PlaneIntersectionError(
            "세 평면 교점 residual이 허용값을 넘습니다: {:.6g}".format(
                float(np.max(residuals))
            )
        )
    return point, {
        "determinant": determinant,
        "condition_number": condition,
        "plane_residuals": residuals.tolist(),
        "maximum_residual": float(np.max(residuals)),
    }


def compute_ordered_corners(
    floor_equation: np.ndarray,
    ceiling_equation: np.ndarray,
    wall_equations: Sequence[np.ndarray],
    wall_ids: Sequence[str],
    validation: Dict[str, Any],
) -> Tuple[np.ndarray, np.ndarray, List[Dict[str, Any]]]:
    """꼭짓점 i를 이전 벽과 현재 벽의 교점으로 계산한다."""

    if len(wall_equations) < 3 or len(wall_equations) != len(wall_ids):
        raise PlaneIntersectionError("순서가 있는 벽 평면이 3개 이상 필요합니다.")
    minimum_angle = float(validation["adjacent_wall_min_angle_deg"])
    residual_tolerance = float(validation["plane_residual_tolerance"])
    max_condition = float(validation["intersection_max_condition_number"])
    bottom = []
    top = []
    diagnostics = []
    count = len(wall_equations)
    for index in range(count):
        previous_index = (index - 1) % count
        previous = wall_equations[previous_index]
        current = wall_equations[index]
        angle = acute_plane_angle_degrees(previous, current)
        if angle < minimum_angle:
            raise PlaneIntersectionError(
                "인접 벽 {}와 {}의 각도 {:.6g}도가 최소값보다 작습니다.".format(
                    wall_ids[previous_index], wall_ids[index], angle
                )
            )
        bottom_point, bottom_diagnostic = solve_three_plane_intersection(
            [floor_equation, previous, current], residual_tolerance, max_condition
        )
        top_point, top_diagnostic = solve_three_plane_intersection(
            [ceiling_equation, previous, current], residual_tolerance, max_condition
        )
        bottom.append(bottom_point)
        top.append(top_point)
        diagnostics.append(
            {
                "corner_index": index,
                "previous_wall_id": wall_ids[previous_index],
                "current_wall_id": wall_ids[index],
                "adjacent_wall_angle_deg": angle,
                "bottom": bottom_diagnostic,
                "top": top_diagnostic,
            }
        )
    return np.asarray(bottom), np.asarray(top), diagnostics
