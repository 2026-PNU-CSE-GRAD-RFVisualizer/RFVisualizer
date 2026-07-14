"""Headless ray math used by Open3D mouse interaction."""

from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple

import numpy as np


def ray_plane_intersection(
    origin: np.ndarray,
    direction: np.ndarray,
    plane: np.ndarray,
    tolerance: float = 1.0e-10,
) -> Optional[np.ndarray]:
    origin = np.asarray(origin, dtype=float)
    direction = np.asarray(direction, dtype=float)
    plane = np.asarray(plane, dtype=float)
    if origin.shape != (3,) or direction.shape != (3,) or plane.shape != (4,):
        raise ValueError(
            "Ray에는 3D origin/direction, plane에는 계수 4개가 필요합니다."
        )
    denominator = float(np.dot(plane[:3], direction))
    if abs(denominator) <= tolerance:
        return None
    distance = -float(np.dot(plane[:3], origin) + plane[3]) / denominator
    if distance < 0.0:
        return None
    return origin + distance * direction


def ray_triangle_intersection(
    origin: np.ndarray,
    direction: np.ndarray,
    triangle: np.ndarray,
    tolerance: float = 1.0e-9,
) -> Optional[Tuple[float, np.ndarray]]:
    o = np.asarray(origin, dtype=float)
    d = np.asarray(direction, dtype=float)
    tri = np.asarray(triangle, dtype=float)
    edge1, edge2 = tri[1] - tri[0], tri[2] - tri[0]
    h = np.cross(d, edge2)
    determinant = float(np.dot(edge1, h))
    if abs(determinant) <= tolerance:
        return None
    inverse = 1.0 / determinant
    s = o - tri[0]
    u = inverse * float(np.dot(s, h))
    if u < -tolerance or u > 1.0 + tolerance:
        return None
    q = np.cross(s, edge1)
    v = inverse * float(np.dot(d, q))
    if v < -tolerance or u + v > 1.0 + tolerance:
        return None
    distance = inverse * float(np.dot(edge2, q))
    if distance <= tolerance:
        return None
    return distance, o + distance * d


def nearest_obstacle_hit(
    origin: np.ndarray,
    direction: np.ndarray,
    obstacle_meshes: Iterable[Tuple[str, np.ndarray, np.ndarray]],
) -> Optional[Dict[str, object]]:
    closest = None
    for object_id, vertices, faces in obstacle_meshes:
        points = np.asarray(vertices, dtype=float)
        triangles = np.asarray(faces, dtype=int)
        for face_index, face in enumerate(triangles):
            hit = ray_triangle_intersection(origin, direction, points[face])
            if hit is None:
                continue
            distance, point = hit
            if closest is None or distance < closest["distance"]:
                closest = {
                    "object_id": object_id,
                    "face_index": int(face_index),
                    "distance": float(distance),
                    "point": point.tolist(),
                }
    return closest
