"""미터 좌표와 원본 PGSR 장면 좌표 사이의 양방향 변환."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

import numpy as np


class CoordinateBridgeError(ValueError):
    """Calibration 행렬 또는 좌표 변환이 유효하지 않을 때 발생한다."""


@dataclass
class CoordinateBridge:
    metric_from_scene: np.ndarray
    scene_from_metric: np.ndarray

    @classmethod
    def from_calibration(cls, calibration: Dict[str, Any]):
        transform = calibration.get("transform", {})
        forward = np.asarray(transform.get("T_metric_from_scene"), dtype=float)
        inverse = np.asarray(transform.get("T_scene_from_metric"), dtype=float)
        if forward.shape != (4, 4) or inverse.shape != (4, 4):
            raise CoordinateBridgeError("Calibration의 양방향 4×4 행렬이 없습니다.")
        if not np.all(np.isfinite(forward)) or not np.all(np.isfinite(inverse)):
            raise CoordinateBridgeError("Calibration 행렬에 NaN 또는 Inf가 있습니다.")
        error = max(
            float(np.max(np.abs(forward @ inverse - np.eye(4)))),
            float(np.max(np.abs(inverse @ forward - np.eye(4)))),
        )
        if error > 1e-8:
            raise CoordinateBridgeError("Calibration 행렬이 서로 역행렬이 아닙니다.")
        return cls(forward, inverse)

    @staticmethod
    def _apply(points: np.ndarray, matrix: np.ndarray) -> np.ndarray:
        values = np.asarray(points, dtype=float)
        if values.shape[-1] != 3 or not np.all(np.isfinite(values)):
            raise CoordinateBridgeError("좌표는 유한한 3차원 점이어야 합니다.")
        flat = values.reshape((-1, 3))
        homogeneous = np.c_[flat, np.ones(len(flat))]
        transformed = homogeneous @ matrix.T
        if np.any(np.abs(transformed[:, 3]) <= 1e-15):
            raise CoordinateBridgeError("동차 좌표 w가 0입니다.")
        transformed = transformed[:, :3] / transformed[:, 3, None]
        return transformed.reshape(values.shape)

    def metric_to_scene(self, points: np.ndarray) -> np.ndarray:
        return self._apply(points, self.scene_from_metric)

    def scene_to_metric(self, points: np.ndarray) -> np.ndarray:
        return self._apply(points, self.metric_from_scene)

    def validation_report(self, metric_points: np.ndarray, scene_points: np.ndarray) -> Dict[str, Any]:
        metric = np.asarray(metric_points, dtype=float)
        scene = np.asarray(scene_points, dtype=float)
        metric_round_trip = self.scene_to_metric(self.metric_to_scene(metric))
        scene_round_trip = self.metric_to_scene(self.scene_to_metric(scene))
        metric_error = float(np.max(np.linalg.norm(metric_round_trip.reshape(-1, 3) - metric.reshape(-1, 3), axis=1)))
        scene_error = float(np.max(np.linalg.norm(scene_round_trip.reshape(-1, 3) - scene.reshape(-1, 3), axis=1)))
        return {
            "metric_to_scene_to_metric_max_error": metric_error,
            "scene_to_metric_to_scene_max_error": scene_error,
            "maximum_error": max(metric_error, scene_error),
            "success": max(metric_error, scene_error) <= 1e-8,
        }
