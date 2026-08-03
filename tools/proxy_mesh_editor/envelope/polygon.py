"""평면 위 2D 다각형 검사와 오목 다각형 삼각분할."""

from __future__ import annotations

from typing import List, Tuple

import numpy as np

from .intersections import normalize_plane_equation


class PolygonError(ValueError):
    """다각형이 단순하지 않거나 안정적으로 삼각분할할 수 없을 때 발생한다."""


def plane_basis(
    plane_equation: np.ndarray, up_vector: np.ndarray
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    model = normalize_plane_equation(plane_equation)
    up = np.asarray(up_vector, dtype=float)
    up = up / np.linalg.norm(up)
    normal = model[:3]
    if float(np.dot(normal, up)) < 0.0:
        model = -model
        normal = -normal
    axes = np.eye(3)
    seed = axes[int(np.argmin(np.abs(axes @ normal)))]
    basis_u = seed - float(np.dot(seed, normal)) * normal
    basis_u = basis_u / np.linalg.norm(basis_u)
    dominant = int(np.argmax(np.abs(basis_u)))
    if basis_u[dominant] < 0.0:
        basis_u = -basis_u
    basis_v = np.cross(normal, basis_u)
    basis_v = basis_v / np.linalg.norm(basis_v)
    origin = -model[3] * normal
    return origin, basis_u, basis_v, normal


def project_to_basis(
    points: np.ndarray, origin: np.ndarray, basis_u: np.ndarray, basis_v: np.ndarray
) -> np.ndarray:
    relative = np.asarray(points, dtype=float) - np.asarray(origin, dtype=float)
    return np.column_stack([relative @ basis_u, relative @ basis_v])


def signed_area(points_2d: np.ndarray) -> float:
    points = np.asarray(points_2d, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3:
        raise PolygonError("다각형에는 2차원 점이 3개 이상 필요합니다.")
    x = points[:, 0]
    y = points[:, 1]
    return float(0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def edge_lengths(points_2d: np.ndarray) -> np.ndarray:
    points = np.asarray(points_2d, dtype=float)
    return np.linalg.norm(np.roll(points, -1, axis=0) - points, axis=1)


def _orientation(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    return float(np.cross(b - a, c - a))


def _on_segment(a: np.ndarray, b: np.ndarray, point: np.ndarray, tolerance: float) -> bool:
    return (
        abs(_orientation(a, b, point)) <= tolerance
        and min(a[0], b[0]) - tolerance <= point[0] <= max(a[0], b[0]) + tolerance
        and min(a[1], b[1]) - tolerance <= point[1] <= max(a[1], b[1]) + tolerance
    )


def segments_intersect(
    a: np.ndarray,
    b: np.ndarray,
    c: np.ndarray,
    d: np.ndarray,
    tolerance: float = 1e-12,
) -> bool:
    values = (
        _orientation(a, b, c),
        _orientation(a, b, d),
        _orientation(c, d, a),
        _orientation(c, d, b),
    )
    if values[0] * values[1] < -tolerance and values[2] * values[3] < -tolerance:
        return True
    return (
        (abs(values[0]) <= tolerance and _on_segment(a, b, c, tolerance))
        or (abs(values[1]) <= tolerance and _on_segment(a, b, d, tolerance))
        or (abs(values[2]) <= tolerance and _on_segment(c, d, a, tolerance))
        or (abs(values[3]) <= tolerance and _on_segment(c, d, b, tolerance))
    )


def find_self_intersections(
    points_2d: np.ndarray, tolerance: float = 1e-12
) -> List[Tuple[int, int]]:
    points = np.asarray(points_2d, dtype=float)
    count = len(points)
    intersections = []
    for first in range(count):
        first_next = (first + 1) % count
        for second in range(first + 1, count):
            second_next = (second + 1) % count
            if first == second or first_next == second or second_next == first:
                continue
            if first == 0 and second_next == 0:
                continue
            if segments_intersect(
                points[first],
                points[first_next],
                points[second],
                points[second_next],
                tolerance,
            ):
                intersections.append((first, second))
    return intersections


def point_in_polygon(point: np.ndarray, polygon: np.ndarray, tolerance: float = 1e-12) -> bool:
    query = np.asarray(point, dtype=float)
    points = np.asarray(polygon, dtype=float)
    inside = False
    for index in range(len(points)):
        a = points[index]
        b = points[(index + 1) % len(points)]
        if _on_segment(a, b, query, tolerance):
            return True
        crosses = (a[1] > query[1]) != (b[1] > query[1])
        if crosses:
            x_cross = (b[0] - a[0]) * (query[1] - a[1]) / (b[1] - a[1]) + a[0]
            if query[0] < x_cross:
                inside = not inside
    return inside


def polygon_centroid(points_2d: np.ndarray) -> np.ndarray:
    points = np.asarray(points_2d, dtype=float)
    area = signed_area(points)
    if abs(area) <= 1e-12:
        raise PolygonError("다각형 면적이 0에 가깝습니다.")
    cross = points[:, 0] * np.roll(points[:, 1], -1) - np.roll(
        points[:, 0], -1
    ) * points[:, 1]
    x = np.sum((points[:, 0] + np.roll(points[:, 0], -1)) * cross) / (6.0 * area)
    y = np.sum((points[:, 1] + np.roll(points[:, 1], -1)) * cross) / (6.0 * area)
    return np.asarray([x, y], dtype=float)


def _point_in_triangle(
    point: np.ndarray,
    a: np.ndarray,
    b: np.ndarray,
    c: np.ndarray,
    tolerance: float,
) -> bool:
    first = _orientation(a, b, point)
    second = _orientation(b, c, point)
    third = _orientation(c, a, point)
    return first >= -tolerance and second >= -tolerance and third >= -tolerance


def ear_clip_triangulation(
    points_2d: np.ndarray, tolerance: float = 1e-12
) -> np.ndarray:
    """반시계 방향 단순 다각형을 결정적인 순서로 삼각분할한다."""

    points = np.asarray(points_2d, dtype=float)
    if len(points) < 3:
        raise PolygonError("삼각분할에는 점이 3개 이상 필요합니다.")
    if signed_area(points) <= tolerance:
        raise PolygonError("ear clipping 입력은 반시계 방향이어야 합니다.")
    if find_self_intersections(points, tolerance):
        raise PolygonError("self-intersection이 있는 다각형은 삼각분할할 수 없습니다.")
    remaining = list(range(len(points)))
    triangles: List[Tuple[int, int, int]] = []
    while len(remaining) > 3:
        ear_found = False
        for position, current in enumerate(remaining):
            previous = remaining[(position - 1) % len(remaining)]
            following = remaining[(position + 1) % len(remaining)]
            if _orientation(points[previous], points[current], points[following]) <= tolerance:
                continue
            contains_point = False
            for other in remaining:
                if other in (previous, current, following):
                    continue
                if _point_in_triangle(
                    points[other],
                    points[previous],
                    points[current],
                    points[following],
                    tolerance,
                ):
                    contains_point = True
                    break
            if contains_point:
                continue
            triangles.append((previous, current, following))
            del remaining[position]
            ear_found = True
            break
        if not ear_found:
            raise PolygonError("다각형에서 유효한 ear를 찾지 못했습니다.")
    triangles.append(tuple(remaining))
    return np.asarray(triangles, dtype=int)
