"""Room-containment and line-of-sight checks for Phase 2-B obstacles."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import math
import numpy as np

from .primitive_builder import TriangleMesh, mesh_statistics


class ObstacleValidationError(ValueError):
    """Raised when an obstacle would make a scenario geometrically invalid."""

    def __init__(self, message: str, report: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.report = report


def _point(value: Any, label: str) -> np.ndarray:
    candidate = value
    if isinstance(candidate, Mapping):
        for key in ("resolved_position_m", "position_m", "position", "point"):
            if key in candidate:
                candidate = candidate[key]
                break
        else:
            if all(key in candidate for key in ("x", "y", "z")):
                candidate = [candidate["x"], candidate["y"], candidate["z"]]
    try:
        result = np.asarray(candidate, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ObstacleValidationError("{} 좌표를 숫자로 읽을 수 없습니다.".format(label)) from exc
    if result.shape != (3,) or not np.all(np.isfinite(result)):
        raise ObstacleValidationError("{} 좌표는 유한한 숫자 3개여야 합니다.".format(label))
    return result


def _mesh_arrays(mesh_or_vertices: Any, faces: Optional[np.ndarray] = None) -> Tuple[np.ndarray, np.ndarray]:
    if isinstance(mesh_or_vertices, TriangleMesh):
        vertices = mesh_or_vertices.vertices
        triangles = mesh_or_vertices.faces
    elif hasattr(mesh_or_vertices, "vertices") and hasattr(mesh_or_vertices, "faces") and faces is None:
        vertices = mesh_or_vertices.vertices
        triangles = mesh_or_vertices.faces
    else:
        vertices = mesh_or_vertices
        triangles = faces
    points = np.asarray(vertices, dtype=float)
    indices = np.asarray(triangles, dtype=int)
    if points.ndim != 2 or points.shape[1:] != (3,) or not np.all(np.isfinite(points)):
        raise ObstacleValidationError("mesh vertices는 유한한 N x 3 배열이어야 합니다.")
    if indices.ndim != 2 or indices.shape[1:] != (3,):
        raise ObstacleValidationError("mesh faces는 M x 3 배열이어야 합니다.")
    if np.any(indices < 0) or np.any(indices >= len(points)):
        raise ObstacleValidationError("mesh face index가 vertex 범위를 벗어납니다.")
    return points, indices


def segment_intersects_aabb(
    start: Sequence[float],
    end: Sequence[float],
    bounds_min: Sequence[float],
    bounds_max: Sequence[float],
    tolerance: float = 1.0e-9,
) -> bool:
    """Inclusive slab test for a finite segment and an axis-aligned box."""

    first, second = _point(start, "segment.start"), _point(end, "segment.end")
    minimum, maximum = _point(bounds_min, "bounds.min"), _point(bounds_max, "bounds.max")
    if np.any(minimum > maximum):
        raise ObstacleValidationError("bounds.min은 bounds.max보다 클 수 없습니다.")
    direction = second - first
    lower, upper = 0.0, 1.0
    for axis in range(3):
        if abs(float(direction[axis])) <= tolerance:
            if first[axis] < minimum[axis] - tolerance or first[axis] > maximum[axis] + tolerance:
                return False
            continue
        one = (minimum[axis] - first[axis]) / direction[axis]
        two = (maximum[axis] - first[axis]) / direction[axis]
        near, far = min(one, two), max(one, two)
        lower = max(lower, float(near))
        upper = min(upper, float(far))
        if lower > upper + tolerance:
            return False
    return bool(upper >= -tolerance and lower <= 1.0 + tolerance)


def _point_on_triangle(point: np.ndarray, triangle: np.ndarray, tolerance: float) -> bool:
    a, b, c = triangle
    normal = np.cross(b - a, c - a)
    length = float(np.linalg.norm(normal))
    if length <= tolerance:
        return False
    distance = abs(float(np.dot(point - a, normal))) / length
    if distance > tolerance:
        return False
    v0, v1, v2 = b - a, c - a, point - a
    dot00 = float(np.dot(v0, v0))
    dot01 = float(np.dot(v0, v1))
    dot02 = float(np.dot(v0, v2))
    dot11 = float(np.dot(v1, v1))
    dot12 = float(np.dot(v1, v2))
    denominator = dot00 * dot11 - dot01 * dot01
    if abs(denominator) <= tolerance * tolerance:
        return False
    u = (dot11 * dot02 - dot01 * dot12) / denominator
    v = (dot00 * dot12 - dot01 * dot02) / denominator
    scaled = max(1.0, math.sqrt(dot00), math.sqrt(dot11))
    epsilon = tolerance / scaled
    return bool(u >= -epsilon and v >= -epsilon and u + v <= 1.0 + epsilon)


def point_inside_mesh(
    point: Sequence[float],
    mesh_or_vertices: Any,
    faces: Optional[np.ndarray] = None,
    tolerance: float = 1.0e-9,
) -> bool:
    """Return whether a point is inside or on a closed oriented triangle mesh.

    The solid-angle winding test works for rotated boxes and for the future
    external-mesh interface without assuming axis alignment.
    """

    value = _point(point, "point")
    vertices, triangles = _mesh_arrays(mesh_or_vertices, faces)
    minimum, maximum = np.min(vertices, axis=0), np.max(vertices, axis=0)
    if np.any(value < minimum - tolerance) or np.any(value > maximum + tolerance):
        return False
    total = 0.0
    for face in triangles:
        triangle = vertices[face]
        if _point_on_triangle(value, triangle, tolerance):
            return True
        a, b, c = triangle - value
        la, lb, lc = float(np.linalg.norm(a)), float(np.linalg.norm(b)), float(np.linalg.norm(c))
        if min(la, lb, lc) <= tolerance:
            return True
        numerator = float(np.dot(a, np.cross(b, c)))
        denominator = (
            la * lb * lc
            + float(np.dot(a, b)) * lc
            + float(np.dot(b, c)) * la
            + float(np.dot(c, a)) * lb
        )
        total += 2.0 * math.atan2(numerator, denominator)
    return bool(abs(total) > 2.0 * math.pi)


def _orientation_2d(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    return float((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))


def _point_in_triangle_2d(point: np.ndarray, triangle: np.ndarray, tolerance: float) -> bool:
    values = [_orientation_2d(triangle[index], triangle[(index + 1) % 3], point) for index in range(3)]
    return bool(not (any(value < -tolerance for value in values) and any(value > tolerance for value in values)))


def _segments_intersect_2d(
    a: np.ndarray,
    b: np.ndarray,
    c: np.ndarray,
    d: np.ndarray,
    tolerance: float,
) -> bool:
    o1, o2 = _orientation_2d(a, b, c), _orientation_2d(a, b, d)
    o3, o4 = _orientation_2d(c, d, a), _orientation_2d(c, d, b)
    if ((o1 > tolerance and o2 < -tolerance) or (o1 < -tolerance and o2 > tolerance)) and (
        (o3 > tolerance and o4 < -tolerance) or (o3 < -tolerance and o4 > tolerance)
    ):
        return True

    def on_segment(first: np.ndarray, second: np.ndarray, candidate: np.ndarray, orientation: float) -> bool:
        return bool(
            abs(orientation) <= tolerance
            and np.all(candidate >= np.minimum(first, second) - tolerance)
            and np.all(candidate <= np.maximum(first, second) + tolerance)
        )

    return bool(
        on_segment(a, b, c, o1)
        or on_segment(a, b, d, o2)
        or on_segment(c, d, a, o3)
        or on_segment(c, d, b, o4)
    )


def _coplanar_hit(
    start: np.ndarray,
    end: np.ndarray,
    triangle: np.ndarray,
    normal: np.ndarray,
    tolerance: float,
) -> bool:
    normal_length = float(np.linalg.norm(normal))
    if normal_length <= tolerance:
        return False
    if abs(float(np.dot(start - triangle[0], normal))) / normal_length > tolerance:
        return False
    if abs(float(np.dot(end - triangle[0], normal))) / normal_length > tolerance:
        return False
    drop = int(np.argmax(np.abs(normal)))
    keep = [axis for axis in range(3) if axis != drop]
    segment = np.asarray([start[keep], end[keep]])
    projected = triangle[:, keep]
    if _point_in_triangle_2d(segment[0], projected, tolerance) or _point_in_triangle_2d(
        segment[1], projected, tolerance
    ):
        return True
    return any(
        _segments_intersect_2d(
            segment[0], segment[1], projected[index], projected[(index + 1) % 3], tolerance
        )
        for index in range(3)
    )


def segment_mesh_intersections(
    start: Sequence[float],
    end: Sequence[float],
    mesh_or_vertices: Any,
    faces: Optional[np.ndarray] = None,
    tolerance: float = 1.0e-9,
) -> List[Dict[str, Any]]:
    """Return deterministic, de-duplicated segment/triangle intersections."""

    first, second = _point(start, "segment.start"), _point(end, "segment.end")
    vertices, triangles = _mesh_arrays(mesh_or_vertices, faces)
    direction = second - first
    length = float(np.linalg.norm(direction))
    if length <= tolerance:
        raise ObstacleValidationError("LoS segment의 두 끝점이 같습니다.")
    if not segment_intersects_aabb(first, second, np.min(vertices, axis=0), np.max(vertices, axis=0), tolerance):
        return []
    hits: List[Dict[str, Any]] = []
    for face_index, face in enumerate(triangles):
        a, b, c = vertices[face]
        edge_one, edge_two = b - a, c - a
        normal = np.cross(edge_one, edge_two)
        h = np.cross(direction, edge_two)
        determinant = float(np.dot(edge_one, h))
        if abs(determinant) <= tolerance * max(1.0, length):
            if _coplanar_hit(first, second, vertices[face], normal, tolerance):
                # A coplanar overlap has no unique entry parameter.  Use the
                # first endpoint on the face, or the segment midpoint, solely
                # for a stable diagnostic record.
                parameter = 0.0 if _point_on_triangle(first, vertices[face], tolerance) else 0.5
                point = first + parameter * direction
            else:
                continue
        else:
            inverse = 1.0 / determinant
            offset = first - a
            u = inverse * float(np.dot(offset, h))
            if u < -tolerance or u > 1.0 + tolerance:
                continue
            q = np.cross(offset, edge_one)
            v = inverse * float(np.dot(direction, q))
            if v < -tolerance or u + v > 1.0 + tolerance:
                continue
            parameter = inverse * float(np.dot(edge_two, q))
            if parameter < -tolerance or parameter > 1.0 + tolerance:
                continue
            parameter = float(np.clip(parameter, 0.0, 1.0))
            point = first + parameter * direction
        if any(
            abs(parameter - previous["segment_parameter"]) <= tolerance * 10.0
            and np.linalg.norm(point - np.asarray(previous["point_m"])) <= tolerance * 10.0
            for previous in hits
        ):
            continue
        hits.append(
            {
                "face_index": int(face_index),
                "segment_parameter": float(parameter),
                "distance_from_start_m": float(parameter * length),
                "point_m": point.tolist(),
            }
        )
    hits.sort(key=lambda item: (item["segment_parameter"], item["face_index"]))
    return hits


def segment_intersects_mesh(
    start: Sequence[float],
    end: Sequence[float],
    mesh_or_vertices: Any,
    faces: Optional[np.ndarray] = None,
    tolerance: float = 1.0e-9,
) -> bool:
    return bool(segment_mesh_intersections(start, end, mesh_or_vertices, faces, tolerance))


def _room_object(room: Any) -> Any:
    candidate = room
    if hasattr(candidate, "metric_metadata"):
        candidate = candidate.metric_metadata
    if isinstance(candidate, Mapping) and "metric_metadata" in candidate:
        candidate = candidate["metric_metadata"]
    if isinstance(candidate, Mapping):
        if "normalized_plane_equations" not in candidate:
            raise ObstacleValidationError("Room metadata에 normalized_plane_equations가 없습니다.")
        try:
            from tools.sionna_smoke_test.placement import RoomContainment

            candidate = RoomContainment.from_metadata(dict(candidate))
        except Exception as exc:
            raise ObstacleValidationError("Room Envelope metadata를 읽을 수 없습니다: {}".format(exc)) from exc
    if not hasattr(candidate, "inspect_point") or not hasattr(candidate, "floor_ceiling_z"):
        raise ObstacleValidationError("room은 RoomContainment 또는 metric metadata여야 합니다.")
    return candidate


def _normalise_segment(value: Any, index: int) -> Tuple[str, np.ndarray, np.ndarray]:
    name = "los_{:03d}".format(index)
    if isinstance(value, Mapping):
        name = str(value.get("name", value.get("receiver_name", name)))
        start = next((value[key] for key in ("start_m", "start", "transmitter", "tx") if key in value), None)
        end = next((value[key] for key in ("end_m", "end", "receiver", "rx") if key in value), None)
        if start is None or end is None:
            raise ObstacleValidationError("LoS segment에는 start/tx와 end/rx가 필요합니다.")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if len(value) == 2:
            start, end = value
        elif len(value) == 3 and isinstance(value[0], str):
            name, start, end = value
        else:
            raise ObstacleValidationError("LoS segment는 (start, end) 또는 (name, start, end) 형식이어야 합니다.")
    else:
        raise ObstacleValidationError("LoS segment 형식이 유효하지 않습니다.")
    return name, _point(start, "{}.start".format(name)), _point(end, "{}.end".format(name))


def _segments(
    transmitter: Any,
    receiver: Any,
    receivers: Optional[Iterable[Any]],
    los_segments: Optional[Iterable[Any]],
) -> List[Tuple[str, np.ndarray, np.ndarray]]:
    values: List[Any] = list(los_segments or [])
    if transmitter is not None:
        if receiver is not None:
            values.append(("los", transmitter, receiver))
        for index, item in enumerate(receivers or []):
            if isinstance(item, Mapping):
                name = str(item.get("name", "rx_{:03d}".format(index)))
            else:
                name = "rx_{:03d}".format(index)
            values.append((name, transmitter, item))
    elif receiver is not None or list(receivers or []):
        raise ObstacleValidationError("receiver가 있으면 transmitter도 필요합니다.")
    return [_normalise_segment(value, index) for index, value in enumerate(values)]


def inspect_obstacle(
    mesh: TriangleMesh,
    room: Any,
    transmitter: Any = None,
    receiver: Any = None,
    receivers: Optional[Iterable[Any]] = None,
    los_segments: Optional[Iterable[Any]] = None,
    require_los_intersection: bool = False,
    tolerance: float = 1.0e-8,
) -> Dict[str, Any]:
    """Inspect an obstacle and return all checks without raising on failure."""

    if tolerance < 0.0 or not math.isfinite(tolerance):
        raise ObstacleValidationError("validation tolerance은 유한한 0 이상 값이어야 합니다.")
    vertices, faces = _mesh_arrays(mesh)
    containment = _room_object(room)
    statistics = mesh_statistics(vertices, faces)
    point_reports = [containment.inspect_point(vertex, 0.0) for vertex in vertices]
    floor_clearances = np.asarray([report["floor_clearance_m"] for report in point_reports], dtype=float)
    ceiling_clearances = np.asarray([report["ceiling_clearance_m"] for report in point_reports], dtype=float)
    wall_clearances = np.asarray([report["minimum_wall_clearance_m"] for report in point_reports], dtype=float)
    floor_failures = np.flatnonzero(floor_clearances < -tolerance).astype(int).tolist()
    ceiling_failures = np.flatnonzero(ceiling_clearances < -tolerance).astype(int).tolist()
    wall_failures = np.flatnonzero(wall_clearances < -tolerance).astype(int).tolist()
    outside = sorted(set(floor_failures + ceiling_failures + wall_failures))

    segment_reports = []
    for name, start, end in _segments(transmitter, receiver, receivers, los_segments):
        hits = segment_mesh_intersections(start, end, mesh, tolerance=tolerance)
        start_inside = point_inside_mesh(start, mesh, tolerance=tolerance)
        end_inside = point_inside_mesh(end, mesh, tolerance=tolerance)
        segment_reports.append(
            {
                "name": name,
                "start_m": start.tolist(),
                "end_m": end.tolist(),
                "length_m": float(np.linalg.norm(end - start)),
                "aabb_intersection": segment_intersects_aabb(
                    start, end, np.min(vertices, axis=0), np.max(vertices, axis=0), tolerance
                ),
                "mesh_intersection": bool(hits),
                "intersection_count": len(hits),
                "intersections": hits,
                "start_inside_obstacle": start_inside,
                "end_inside_obstacle": end_inside,
            }
        )

    geometry_finite = bool(np.all(np.isfinite(vertices)))
    nondegenerate = statistics["degenerate_triangle_count"] == 0
    closed = bool(statistics["closed_manifold"])
    positive_volume = statistics["signed_volume"] > tolerance
    devices_outside = all(
        not report["start_inside_obstacle"] and not report["end_inside_obstacle"]
        for report in segment_reports
    )
    los_intersection = any(report["mesh_intersection"] for report in segment_reports)
    checks = {
        "finite_geometry": geometry_finite,
        "nondegenerate_triangles": nondegenerate,
        "closed_manifold": closed,
        "positive_signed_volume": positive_volume,
        "room_containment": not outside,
        "on_or_above_floor": not floor_failures,
        "on_or_below_ceiling": not ceiling_failures,
        "inside_walls": not wall_failures,
        "devices_outside_obstacle": devices_outside,
        "required_los_intersection": (los_intersection if require_los_intersection else True),
    }
    errors = []
    labels = {
        "finite_geometry": "장애물 좌표에 유한하지 않은 값이 있습니다.",
        "nondegenerate_triangles": "장애물에 퇴화 삼각형이 있습니다.",
        "closed_manifold": "장애물 mesh가 닫힌 manifold가 아닙니다.",
        "positive_signed_volume": "장애물 mesh의 부호 있는 부피가 양수가 아닙니다.",
        "room_containment": "장애물 일부가 Room Envelope 밖에 있습니다.",
        "on_or_above_floor": "장애물 일부가 바닥 아래에 있습니다.",
        "on_or_below_ceiling": "장애물 일부가 천장을 관통합니다.",
        "inside_walls": "장애물 일부가 벽을 관통하거나 방 밖에 있습니다.",
        "devices_outside_obstacle": "TX 또는 RX가 장애물 내부에 있습니다.",
        "required_los_intersection": "지정한 TX-RX LoS가 장애물과 교차하지 않습니다.",
    }
    for key, success in checks.items():
        if not success:
            errors.append(labels[key])
    return {
        "schema_version": "1.0",
        "obstacle_id": mesh.obstacle_id,
        "success": all(checks.values()),
        "checks": checks,
        "errors": errors,
        "mesh_statistics": statistics,
        "bounds": {
            "min": np.min(vertices, axis=0).tolist(),
            "max": np.max(vertices, axis=0).tolist(),
        },
        "containment": {
            "fully_inside": not outside,
            "outside_vertex_indices": outside,
            "floor_failure_vertex_indices": floor_failures,
            "ceiling_failure_vertex_indices": ceiling_failures,
            "wall_failure_vertex_indices": wall_failures,
            "minimum_floor_clearance_m": float(np.min(floor_clearances)),
            "minimum_ceiling_clearance_m": float(np.min(ceiling_clearances)),
            "minimum_wall_clearance_m": float(np.min(wall_clearances)),
            "vertex_inspections": point_reports,
        },
        "los": {
            "required": bool(require_los_intersection),
            "any_intersection": los_intersection,
            "segments": segment_reports,
        },
    }


def validate_obstacle(
    mesh: TriangleMesh,
    room: Any,
    transmitter: Any = None,
    receiver: Any = None,
    receivers: Optional[Iterable[Any]] = None,
    los_segments: Optional[Iterable[Any]] = None,
    require_los_intersection: bool = False,
    tolerance: float = 1.0e-8,
) -> Dict[str, Any]:
    """Return a validation report, or raise with the complete failed report."""

    report = inspect_obstacle(
        mesh,
        room,
        transmitter=transmitter,
        receiver=receiver,
        receivers=receivers,
        los_segments=los_segments,
        require_los_intersection=require_los_intersection,
        tolerance=tolerance,
    )
    if not report["success"]:
        raise ObstacleValidationError("; ".join(report["errors"]), report=report)
    return report


def validate_los_intersection(
    mesh: TriangleMesh,
    transmitter: Any,
    receiver: Any,
    tolerance: float = 1.0e-8,
) -> Dict[str, Any]:
    """Standalone synthetic-blocker LoS assertion without room validation."""

    start, end = _point(transmitter, "transmitter"), _point(receiver, "receiver")
    start_inside = point_inside_mesh(start, mesh, tolerance=tolerance)
    end_inside = point_inside_mesh(end, mesh, tolerance=tolerance)
    hits = segment_mesh_intersections(start, end, mesh, tolerance=tolerance)
    result = {
        "success": bool(hits) and not start_inside and not end_inside,
        "transmitter_inside_obstacle": start_inside,
        "receiver_inside_obstacle": end_inside,
        "intersection_count": len(hits),
        "intersections": hits,
    }
    if not result["success"]:
        raise ObstacleValidationError(
            "Synthetic blocker는 TX/RX 밖에 있어야 하고 LoS segment와 교차해야 합니다.",
            report=result,
        )
    return result
