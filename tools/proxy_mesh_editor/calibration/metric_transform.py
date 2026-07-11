"""Scene 좌표를 미터 단위 표준 좌표계로 옮기는 양방향 변환."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple

import numpy as np

from .orientation_analysis import normalize_direction


class MetricTransformError(ValueError):
    """표준 좌표 프레임 또는 변환 행렬을 안전하게 만들 수 없을 때 발생한다."""


@dataclass
class MetricTransform:
    scale: float
    origin_scene: np.ndarray
    x_scene: np.ndarray
    y_scene: np.ndarray
    z_scene: np.ndarray
    rotation: np.ndarray
    forward: np.ndarray
    inverse: np.ndarray
    origin_corner_index: int
    x_axis_edge: Tuple[int, int]


def _positive_scale(value: float) -> float:
    scale = float(value)
    if not np.isfinite(scale) or scale <= 0.0:
        raise MetricTransformError("실제 크기 배율은 유한한 양수여야 합니다.")
    return scale


def build_metric_transform(
    envelope: Dict[str, Any],
    coordinate_frame: Dict[str, Any],
    resolved_scale: float,
    validation: Dict[str, Any],
) -> MetricTransform:
    scale = _positive_scale(resolved_scale)
    bottom = np.asarray(envelope.get("bottom_corners"), dtype=float)
    if bottom.ndim != 2 or bottom.shape[1] != 3 or len(bottom) < 3 or not np.all(np.isfinite(bottom)):
        raise MetricTransformError("Envelope bottom corner 배열이 유효하지 않습니다.")
    z_scene = normalize_direction(np.asarray(envelope.get("up_vector"), dtype=float), "scene up")
    origin_index = int(coordinate_frame["origin"]["corner_index"])
    start = int(coordinate_frame["x_axis"]["start_corner"])
    end = int(coordinate_frame["x_axis"]["end_corner"])
    for index, name in ((origin_index, "origin"), (start, "X축 시작"), (end, "X축 끝")):
        if index < 0 or index >= len(bottom):
            raise MetricTransformError("{} corner index {}가 범위를 벗어납니다.".format(name, index))
    if start == end:
        raise MetricTransformError("X축 시작점과 끝점은 달라야 합니다.")
    if end != (start + 1) % len(bottom):
        raise MetricTransformError("X축 corner 쌍은 polygon에서 연속한 방향성 edge여야 합니다.")

    edge = bottom[end] - bottom[start]
    projected = edge - float(np.dot(edge, z_scene)) * z_scene
    projected_length = float(np.linalg.norm(projected))
    axis_tolerance = float(validation["maximum_axis_alignment_error"])
    if not np.isfinite(projected_length) or projected_length <= axis_tolerance:
        raise MetricTransformError("선택한 X축 edge가 scene up과 거의 평행합니다.")
    x_scene = projected / projected_length
    y_scene = normalize_direction(np.cross(z_scene, x_scene), "source Y axis")
    rotation = np.vstack([x_scene, y_scene, z_scene])
    determinant = float(np.linalg.det(rotation))
    orthogonality_error = float(np.max(np.abs(rotation.T @ rotation - np.eye(3))))
    handedness_error = float(np.linalg.norm(np.cross(x_scene, y_scene) - z_scene))
    determinant_error = abs(determinant - 1.0)
    if determinant <= 0.0 or determinant_error > float(validation["maximum_rotation_determinant_error"]):
        raise MetricTransformError("회전 행렬이 determinant +1인 proper rotation이 아닙니다.")
    if orthogonality_error > float(validation["maximum_orthogonality_error"]):
        raise MetricTransformError("회전 행렬의 축이 서로 직교하지 않습니다.")
    if handedness_error > axis_tolerance:
        raise MetricTransformError("X/Y/Z 축이 오른손 좌표계를 이루지 않습니다.")

    origin = bottom[origin_index].copy()
    linear = scale * rotation
    translation = -linear @ origin
    forward = np.eye(4)
    forward[:3, :3] = linear
    forward[:3, 3] = translation
    inverse = np.eye(4)
    inverse[:3, :3] = rotation.T / scale
    inverse[:3, 3] = origin
    identity_error = max(
        float(np.max(np.abs(inverse @ forward - np.eye(4)))),
        float(np.max(np.abs(forward @ inverse - np.eye(4)))),
    )
    if identity_error > float(validation["maximum_round_trip_error"]):
        raise MetricTransformError("정방향·역방향 변환 행렬이 서로 역행렬이 아닙니다.")
    return MetricTransform(
        scale=scale,
        origin_scene=origin,
        x_scene=x_scene,
        y_scene=y_scene,
        z_scene=z_scene,
        rotation=rotation,
        forward=forward,
        inverse=inverse,
        origin_corner_index=origin_index,
        x_axis_edge=(start, end),
    )


def transform_points(points: np.ndarray, transform: MetricTransform) -> np.ndarray:
    values = np.asarray(points, dtype=float)
    if values.shape[-1] != 3 or not np.all(np.isfinite(values)):
        raise MetricTransformError("변환할 point는 유한한 3차원 좌표여야 합니다.")
    return (values - transform.origin_scene) @ transform.rotation.T * transform.scale


def inverse_transform_points(points: np.ndarray, transform: MetricTransform) -> np.ndarray:
    values = np.asarray(points, dtype=float)
    if values.shape[-1] != 3 or not np.all(np.isfinite(values)):
        raise MetricTransformError("역변환할 point는 유한한 3차원 좌표여야 합니다.")
    return (values / transform.scale) @ transform.rotation + transform.origin_scene


def transform_normals(normals: np.ndarray, transform: MetricTransform) -> np.ndarray:
    values = np.asarray(normals, dtype=float)
    if values.shape[-1] != 3 or not np.all(np.isfinite(values)):
        raise MetricTransformError("변환할 normal은 유한한 3차원 벡터여야 합니다.")
    lengths = np.linalg.norm(values, axis=-1)
    if np.any(lengths <= 1e-12):
        raise MetricTransformError("길이가 0인 normal은 변환할 수 없습니다.")
    normalized = values / lengths[..., None]
    rotated = normalized @ transform.rotation.T
    return rotated / np.linalg.norm(rotated, axis=-1)[..., None]


def transform_plane(equation: np.ndarray, transform: MetricTransform) -> np.ndarray:
    model = np.asarray(equation, dtype=float)
    if model.shape != (4,) or not np.all(np.isfinite(model)):
        raise MetricTransformError("평면식은 유한한 숫자 4개여야 합니다.")
    length = float(np.linalg.norm(model[:3]))
    if length <= 1e-12:
        raise MetricTransformError("평면 법선 길이가 0입니다.")
    normal_scene = model[:3] / length
    offset_scene = float(model[3] / length)
    point_scene = -offset_scene * normal_scene
    point_metric = transform_points(point_scene, transform)
    normal_metric = transform_normals(normal_scene, transform)
    offset_metric = -float(np.dot(normal_metric, point_metric))
    return np.r_[normal_metric, offset_metric]


def transform_diagnostics(transform: MetricTransform) -> Dict[str, Any]:
    rotation = transform.rotation
    return {
        "resolved_meters_per_scene_unit": transform.scale,
        "origin_corner_index": transform.origin_corner_index,
        "origin_scene_coordinate": transform.origin_scene.tolist(),
        "origin_metric_coordinate": transform_points(transform.origin_scene, transform).tolist(),
        "x_axis_edge_indices": list(transform.x_axis_edge),
        "source_x_axis": transform.x_scene.tolist(),
        "source_y_axis": transform.y_scene.tolist(),
        "source_z_axis": transform.z_scene.tolist(),
        "rotation_matrix": rotation.tolist(),
        "rotation_determinant": float(np.linalg.det(rotation)),
        "orthogonality_error": float(np.max(np.abs(rotation.T @ rotation - np.eye(3)))),
        "handedness_error": float(np.linalg.norm(np.cross(transform.x_scene, transform.y_scene) - transform.z_scene)),
        "translation_vector": transform.forward[:3, 3].tolist(),
        "T_metric_from_scene": transform.forward.tolist(),
        "T_scene_from_metric": transform.inverse.tolist(),
        "matrix_inverse_error": max(
            float(np.max(np.abs(transform.inverse @ transform.forward - np.eye(4)))),
            float(np.max(np.abs(transform.forward @ transform.inverse - np.eye(4)))),
        ),
    }
