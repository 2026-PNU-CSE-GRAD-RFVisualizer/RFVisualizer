"""GUI-independent transform gizmo geometry and ray picking math."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

import numpy as np


AXIS_NAMES = ("x", "y", "z")
AXIS_COLORS = {
    "x": (0.95, 0.12, 0.12),
    "y": (0.20, 0.85, 0.25),
    "z": (0.18, 0.42, 1.0),
}


@dataclass(frozen=True)
class GizmoFrame:
    center: np.ndarray
    axes: np.ndarray
    length: float
    mode: str
    space: str

    def axis(self, name: str) -> np.ndarray:
        return self.axes[:, AXIS_NAMES.index(name)]


def _orthonormal_axes(linear: np.ndarray) -> np.ndarray:
    value = np.asarray(linear, dtype=float)
    if value.shape != (3, 3) or not np.all(np.isfinite(value)):
        return np.eye(3, dtype=float)
    u, _, vh = np.linalg.svd(value)
    result = u @ vh
    if np.linalg.det(result) < 0.0:
        u[:, -1] *= -1.0
        result = u @ vh
    return result


def make_gizmo_frame(
    vertices: np.ndarray,
    metric_transform: np.ndarray,
    mode: str,
    space: str,
    room_diagonal: float,
) -> GizmoFrame:
    points = np.asarray(vertices, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) == 0:
        raise ValueError("Gizmo에는 N x 3 object vertices가 필요합니다.")
    if mode not in {"translate", "rotate", "scale"}:
        raise ValueError("Gizmo mode는 translate/rotate/scale이어야 합니다.")
    if space not in {"world", "local"}:
        raise ValueError("Gizmo space는 world/local이어야 합니다.")
    transform = np.asarray(metric_transform, dtype=float)
    local_axes = (
        _orthonormal_axes(transform[:3, :3])
        if transform.shape == (4, 4)
        else np.eye(3, dtype=float)
    )
    # Non-uniform scale of a rotated Phase 2-B primitive is defined in its
    # local dimensions. It intentionally ignores the World/Local toggle.
    axes = local_axes if mode == "scale" or space == "local" else np.eye(3)
    minimum, maximum = np.min(points, axis=0), np.max(points, axis=0)
    center = (minimum + maximum) / 2.0
    object_extent = float(np.max(maximum - minimum))
    diagonal = max(float(room_diagonal), 1.0e-6)
    length = max(object_extent * 0.75, diagonal * 0.045)
    length = min(length, diagonal * 0.20)
    return GizmoFrame(center, axes, length, mode, space)


def closest_ray_segment(
    origin: np.ndarray,
    direction: np.ndarray,
    start: np.ndarray,
    end: np.ndarray,
) -> Tuple[float, float, float]:
    """Return ray depth, segment fraction, and closest distance."""

    o = np.asarray(origin, dtype=float)
    d = np.asarray(direction, dtype=float)
    p0 = np.asarray(start, dtype=float)
    p1 = np.asarray(end, dtype=float)
    d_norm = float(np.linalg.norm(d))
    if d_norm <= 1.0e-12:
        raise ValueError("Ray direction 길이는 0일 수 없습니다.")
    d = d / d_norm
    segment = p1 - p0
    c = float(np.dot(segment, segment))
    if c <= 1.0e-18:
        ray_depth = max(0.0, float(np.dot(p0 - o, d)))
        closest_ray = o + ray_depth * d
        return ray_depth, 0.0, float(np.linalg.norm(closest_ray - p0))
    w = o - p0
    b = float(np.dot(d, segment))
    d_w = float(np.dot(d, w))
    e = float(np.dot(segment, w))
    denominator = c - b * b
    if denominator > 1.0e-12:
        segment_fraction = (e - b * d_w) / denominator
    else:
        segment_fraction = e / c
    segment_fraction = min(1.0, max(0.0, segment_fraction))
    ray_depth = max(0.0, b * segment_fraction - d_w)
    # Re-evaluate the segment parameter when the closest point is the ray origin.
    if ray_depth == 0.0:
        segment_fraction = min(1.0, max(0.0, e / c))
    closest_ray = o + ray_depth * d
    closest_segment = p0 + segment_fraction * segment
    return (
        ray_depth,
        segment_fraction,
        float(np.linalg.norm(closest_ray - closest_segment)),
    )


def ring_points(
    frame: GizmoFrame, axis_name: str, segments: int = 72
) -> np.ndarray:
    axis_index = AXIS_NAMES.index(axis_name)
    first = frame.axes[:, (axis_index + 1) % 3]
    second = frame.axes[:, (axis_index + 2) % 3]
    angles = np.linspace(0.0, 2.0 * np.pi, int(segments), endpoint=False)
    return frame.center + frame.length * (
        np.cos(angles)[:, None] * first + np.sin(angles)[:, None] * second
    )


def pick_gizmo_axis(
    origin: np.ndarray,
    direction: np.ndarray,
    frame: Optional[GizmoFrame],
) -> Optional[Dict[str, float]]:
    if frame is None:
        return None
    tolerance = frame.length * (0.11 if frame.mode == "rotate" else 0.13)
    best: Optional[Dict[str, float]] = None
    for name in AXIS_NAMES:
        if frame.mode == "rotate":
            points = ring_points(frame, name)
            segments = zip(points, np.roll(points, -1, axis=0))
        else:
            axis = frame.axis(name)
            segments = ((frame.center + axis * frame.length * 0.12,
                         frame.center + axis * frame.length * 1.18),)
        for start, end in segments:
            depth, fraction, distance = closest_ray_segment(
                origin, direction, start, end
            )
            if depth <= 0.0 or distance > tolerance:
                continue
            score = distance / tolerance + depth * 1.0e-8
            if best is None or score < best["score"]:
                best = {
                    "axis": name,
                    "distance": distance,
                    "depth": depth,
                    "score": score,
                    "point": (start + fraction * (end - start)).tolist(),
                }
    return best


def pick_projected_gizmo_axis(
    mouse_xy: np.ndarray,
    frame: Optional[GizmoFrame],
    project: Callable[[np.ndarray], Optional[np.ndarray]],
    tolerance_px: float = 14.0,
) -> Optional[Dict[str, object]]:
    """Pick the visible gizmo in screen pixels instead of scene units."""

    if frame is None:
        return None
    mouse = np.asarray(mouse_xy, dtype=float)
    if mouse.shape != (2,) or not np.all(np.isfinite(mouse)):
        raise ValueError("Mouse screen position에는 유한한 x/y가 필요합니다.")
    tolerance = float(tolerance_px)
    if not np.isfinite(tolerance) or tolerance <= 0.0:
        raise ValueError("Gizmo screen tolerance는 유한한 양수여야 합니다.")
    best: Optional[Dict[str, object]] = None
    for name in AXIS_NAMES:
        if frame.mode == "rotate":
            points = ring_points(frame, name)
            segments = zip(points, np.roll(points, -1, axis=0))
        else:
            axis = frame.axis(name)
            segments = (
                (
                    frame.center + axis * frame.length * 0.08,
                    frame.center + axis * frame.length * 1.18,
                ),
            )
        for world_start, world_end in segments:
            screen_start = project(world_start)
            screen_end = project(world_end)
            if screen_start is None or screen_end is None:
                continue
            start = np.asarray(screen_start, dtype=float)
            end = np.asarray(screen_end, dtype=float)
            segment = end[:2] - start[:2]
            squared_length = float(np.dot(segment, segment))
            if squared_length <= 1.0e-8:
                continue
            fraction = float(
                np.clip(np.dot(mouse - start[:2], segment) / squared_length, 0.0, 1.0)
            )
            closest = start[:2] + fraction * segment
            distance = float(np.linalg.norm(mouse - closest))
            if distance > tolerance:
                continue
            depth = float(start[2] + fraction * (end[2] - start[2]))
            score = distance / tolerance + max(depth, 0.0) * 1.0e-5
            if best is None or score < float(best["score"]):
                best = {
                    "axis": name,
                    "distance_px": distance,
                    "depth": depth,
                    "score": score,
                    "point": (
                        world_start + fraction * (world_end - world_start)
                    ).tolist(),
                }
    return best


def axis_drag_parameter(
    origin: np.ndarray,
    direction: np.ndarray,
    center: np.ndarray,
    axis: np.ndarray,
) -> float:
    """Closest signed position on an infinite gizmo axis for one mouse ray."""

    o = np.asarray(origin, dtype=float)
    d = np.asarray(direction, dtype=float)
    c = np.asarray(center, dtype=float)
    a = np.asarray(axis, dtype=float)
    d /= np.linalg.norm(d)
    a /= np.linalg.norm(a)
    w = o - c
    cross_dot = float(np.dot(d, a))
    denominator = 1.0 - cross_dot * cross_dot
    if denominator <= 1.0e-8:
        closest_depth = max(0.0, float(np.dot(c - o, d)))
        return float(np.dot(o + closest_depth * d - c, a))
    d_w = float(np.dot(d, w))
    a_w = float(np.dot(a, w))
    return (a_w - cross_dot * d_w) / denominator


def rotation_drag_angle_deg(
    center: np.ndarray,
    axis: np.ndarray,
    start_point: np.ndarray,
    current_point: np.ndarray,
) -> float:
    normal = np.asarray(axis, dtype=float)
    normal /= np.linalg.norm(normal)

    def projected(value: np.ndarray) -> np.ndarray:
        vector = np.asarray(value, dtype=float) - np.asarray(center, dtype=float)
        vector = vector - normal * float(np.dot(vector, normal))
        length = float(np.linalg.norm(vector))
        if length <= 1.0e-10:
            raise ValueError("회전 drag point가 회전축 위에 있습니다.")
        return vector / length

    first, second = projected(start_point), projected(current_point)
    sine = float(np.dot(normal, np.cross(first, second)))
    cosine = float(np.clip(np.dot(first, second), -1.0, 1.0))
    return float(np.degrees(np.arctan2(sine, cosine)))


def screen_rotation_drag_angle_deg(
    start_xy: np.ndarray,
    current_xy: np.ndarray,
    tangent_xy: np.ndarray,
    degrees_per_pixel: float,
) -> float:
    """Return a signed rotation from mouse motion along a projected ring."""

    start = np.asarray(start_xy, dtype=float)
    current = np.asarray(current_xy, dtype=float)
    tangent = np.asarray(tangent_xy, dtype=float)
    scale = float(degrees_per_pixel)
    if start.shape != (2,) or current.shape != (2,) or tangent.shape != (2,):
        raise ValueError("회전 screen drag에는 2D 좌표가 필요합니다.")
    if not all(np.all(np.isfinite(value)) for value in (start, current, tangent)):
        raise ValueError("회전 screen drag 좌표는 유한해야 합니다.")
    length = float(np.linalg.norm(tangent))
    if length <= 1.0e-9:
        raise ValueError("회전 screen tangent 길이는 0일 수 없습니다.")
    if not np.isfinite(scale) or scale <= 0.0:
        raise ValueError("회전 screen scale은 유한한 양수여야 합니다.")
    return float(np.dot(current - start, tangent / length) * scale)
