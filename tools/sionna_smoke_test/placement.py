"""기울어진 바닥·천장과 벽 평면을 사용해 TX/RX 내부 배치를 검증한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


class PlacementError(ValueError):
    """TX/RX를 Room Envelope 내부에 안전하게 배치할 수 없을 때 발생한다."""


def _point_segment_distance_2d(
    point: np.ndarray, start: np.ndarray, end: np.ndarray
) -> float:
    direction = end - start
    denominator = float(np.dot(direction, direction))
    if denominator <= 1.0e-24:
        return float(np.linalg.norm(point - start))
    parameter = float(np.clip(np.dot(point - start, direction) / denominator, 0.0, 1.0))
    return float(np.linalg.norm(point - (start + parameter * direction)))


def _point_in_polygon_2d(
    point: np.ndarray, polygon: np.ndarray, tolerance: float = 1.0e-8
) -> bool:
    """Boundary-inclusive even/odd test for a simple 2-D polygon."""

    inside = False
    x, y = float(point[0]), float(point[1])
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        if _point_segment_distance_2d(point, start, end) <= tolerance:
            return True
        y1, y2 = float(start[1]), float(end[1])
        if (y1 > y) == (y2 > y):
            continue
        intersection_x = float(start[0]) + (y - y1) * float(end[0] - start[0]) / (y2 - y1)
        if x < intersection_x:
            inside = not inside
    return inside


def _polygon_is_concave_2d(polygon: np.ndarray, tolerance: float = 1.0e-10) -> bool:
    signs = set()
    for index in range(len(polygon)):
        first = polygon[(index + 1) % len(polygon)] - polygon[index]
        second = polygon[(index + 2) % len(polygon)] - polygon[(index + 1) % len(polygon)]
        cross = float(first[0] * second[1] - first[1] * second[0])
        if abs(cross) > tolerance:
            signs.add(1 if cross > 0.0 else -1)
    return len(signs) > 1


@dataclass
class RoomContainment:
    floor: np.ndarray
    ceiling: np.ndarray
    walls: List[np.ndarray]
    interior_point: np.ndarray
    bounds_min: np.ndarray
    bounds_max: np.ndarray
    footprint_xy: Optional[np.ndarray] = None
    footprint_is_concave: bool = False

    @classmethod
    def from_metadata(cls, metadata: Dict[str, Any]):
        equations = metadata.get("normalized_plane_equations", {})
        floor = np.asarray(equations.get("floor"), dtype=float)
        ceiling = np.asarray(equations.get("ceiling"), dtype=float)
        walls = [np.asarray(value, dtype=float) for value in equations.get("walls", [])]
        interior = np.asarray(metadata.get("interior_point"), dtype=float)
        bounds = metadata.get("bounds", {})
        minimum = np.asarray(bounds.get("min"), dtype=float)
        maximum = np.asarray(bounds.get("max"), dtype=float)
        if floor.shape != (4,) or ceiling.shape != (4,) or not walls:
            raise PlacementError("Metric metadata의 floor/ceiling/wall 평면식이 부족합니다.")
        if interior.shape != (3,) or minimum.shape != (3,) or maximum.shape != (3,):
            raise PlacementError("Metric metadata의 interior point 또는 bounds가 유효하지 않습니다.")
        corners = np.asarray(metadata.get("bottom_corners", []), dtype=float)
        footprint = None
        concave = False
        if corners.size:
            if (
                corners.ndim != 2
                or corners.shape[1] != 3
                or len(corners) < 3
                or not np.all(np.isfinite(corners))
            ):
                raise PlacementError("Metric metadata의 bottom_corners가 유효하지 않습니다.")
            footprint = corners[:, :2].copy()
            concave = _polygon_is_concave_2d(footprint)
        return cls(
            floor,
            ceiling,
            walls,
            interior,
            minimum,
            maximum,
            footprint_xy=footprint,
            footprint_is_concave=concave,
        )

    @property
    def planes(self):
        return [self.floor, self.ceiling] + self.walls

    def _oriented_distance(self, plane: np.ndarray, point: np.ndarray) -> float:
        normal_length = float(np.linalg.norm(plane[:3]))
        if normal_length <= 1e-12:
            raise PlacementError("길이가 0인 Room Envelope plane normal입니다.")
        interior_value = float(np.dot(plane[:3], self.interior_point) + plane[3]) / normal_length
        point_value = float(np.dot(plane[:3], point) + plane[3]) / normal_length
        sign = 1.0 if interior_value >= 0.0 else -1.0
        return sign * point_value

    @staticmethod
    def _plane_z(plane: np.ndarray, x: float, y: float) -> float:
        if abs(float(plane[2])) <= 1e-12:
            raise PlacementError("바닥 또는 천장 평면에서 Z를 계산할 수 없습니다.")
        return float(-(plane[0] * x + plane[1] * y + plane[3]) / plane[2])

    def floor_ceiling_z(self, x: float, y: float) -> Tuple[float, float]:
        floor_z = self._plane_z(self.floor, x, y)
        ceiling_z = self._plane_z(self.ceiling, x, y)
        return min(floor_z, ceiling_z), max(floor_z, ceiling_z)

    def inspect_point(self, point: np.ndarray, clearance: float) -> Dict[str, Any]:
        value = np.asarray(point, dtype=float)
        if value.shape != (3,) or not np.all(np.isfinite(value)):
            raise PlacementError("TX/RX 좌표는 유한한 숫자 3개여야 합니다.")
        plane_distances = [self._oriented_distance(plane, value) for plane in self.planes]
        floor_z, ceiling_z = self.floor_ceiling_z(value[0], value[1])
        floor_clearance = float(value[2] - floor_z)
        ceiling_clearance = float(ceiling_z - value[2])
        if self.footprint_is_concave and self.footprint_xy is not None:
            horizontal_inside = _point_in_polygon_2d(value[:2], self.footprint_xy)
            wall_clearance = min(
                _point_segment_distance_2d(
                    value[:2],
                    start,
                    self.footprint_xy[(index + 1) % len(self.footprint_xy)],
                )
                for index, start in enumerate(self.footprint_xy)
            )
            if not horizontal_inside:
                wall_clearance = -wall_clearance
            inside = bool(
                horizontal_inside
                and plane_distances[0] >= -1.0e-8
                and plane_distances[1] >= -1.0e-8
            )
        else:
            wall_clearance = float(min(plane_distances[2:]))
            inside = bool(all(distance >= -1e-8 for distance in plane_distances))
        safe = bool(
            inside
            and floor_clearance >= clearance
            and ceiling_clearance >= clearance
            and wall_clearance >= clearance
        )
        return {
            "position_m": value.tolist(),
            "inside_room": inside,
            "safe_with_clearance": safe,
            "floor_z_m": floor_z,
            "ceiling_z_m": ceiling_z,
            "floor_clearance_m": floor_clearance,
            "ceiling_clearance_m": ceiling_clearance,
            "minimum_wall_clearance_m": wall_clearance,
            "oriented_plane_distances_m": plane_distances,
        }

    def fallback_candidates(self, preferred_z: float, clearance: float):
        xs = np.linspace(self.bounds_min[0] + clearance, self.bounds_max[0] - clearance, 9)
        ys = np.linspace(self.bounds_min[1] + clearance, self.bounds_max[1] - clearance, 9)
        center = self.interior_point[:2]
        candidates = sorted(
            ((float(x), float(y)) for x in xs for y in ys),
            key=lambda xy: (float(np.linalg.norm(np.asarray(xy) - center)), xy[0], xy[1]),
        )
        for x, y in candidates:
            floor_z, ceiling_z = self.floor_ceiling_z(x, y)
            lower, upper = floor_z + clearance, ceiling_z - clearance
            if lower > upper:
                continue
            z = float(np.clip(preferred_z, lower, upper))
            point = np.asarray([x, y, z])
            if self.inspect_point(point, clearance)["safe_with_clearance"]:
                yield point


def resolve_positions(settings: Dict[str, Any], metadata: Dict[str, Any]):
    room = RoomContainment.from_metadata(metadata)
    placement = settings["placement"]
    clearance = float(placement["clearance_m"])
    minimum_separation = float(placement["minimum_device_separation_m"])
    requested = [("transmitter", settings["transmitter"])] + [
        ("receiver", value) for value in settings["receivers"]
    ]
    resolved = []
    warnings = []
    used = []
    for kind, item in requested:
        preferred = np.asarray(item["position_m"], dtype=float)
        inspection = room.inspect_point(preferred, clearance)
        separated = all(np.linalg.norm(preferred - other) >= minimum_separation for other in used)
        if inspection["safe_with_clearance"] and separated:
            point = preferred
            fallback = False
        else:
            if placement["mode"] == "strict":
                raise PlacementError("{} '{}' 위치가 방 내부 안전 조건을 만족하지 않습니다.".format(kind, item["name"]))
            point = None
            for candidate in room.fallback_candidates(preferred[2], clearance):
                if all(np.linalg.norm(candidate - other) >= minimum_separation for other in used):
                    point = candidate
                    break
            if point is None:
                raise PlacementError("{} '{}'의 대체 내부 위치를 찾지 못했습니다.".format(kind, item["name"]))
            fallback = True
            warnings.append(
                "{} '{}'의 요청 위치가 유효하지 않아 결정적인 내부 후보로 교체했습니다.".format(kind, item["name"])
            )
            inspection = room.inspect_point(point, clearance)
        used.append(point)
        resolved.append(
            {
                "kind": kind,
                "name": item["name"],
                "requested_position_m": preferred.tolist(),
                "resolved_position_m": point.tolist(),
                "used_fallback": fallback,
                "validation": inspection,
            }
        )
    return room, resolved, warnings
