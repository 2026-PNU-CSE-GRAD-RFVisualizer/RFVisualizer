"""Metric/PGSR vertex and local-transform conversion for authored obstacles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

import numpy as np

from tools.sionna_smoke_test.coordinate_bridge import CoordinateBridge


@dataclass
class PlacementCoordinateBridge:
    bridge: CoordinateBridge

    @classmethod
    def from_calibration(
        cls, calibration: Dict[str, Any]
    ) -> "PlacementCoordinateBridge":
        return cls(CoordinateBridge.from_calibration(calibration))

    def metric_vertices_to_scene(self, vertices: np.ndarray) -> np.ndarray:
        return self.bridge.metric_to_scene(vertices)

    def scene_vertices_to_metric(self, vertices: np.ndarray) -> np.ndarray:
        return self.bridge.scene_to_metric(vertices)

    def metric_transform_to_scene(self, transform: np.ndarray) -> np.ndarray:
        value = self._matrix(transform, "metric transform")
        return self.bridge.scene_from_metric @ value

    def scene_transform_to_metric(self, transform: np.ndarray) -> np.ndarray:
        value = self._matrix(transform, "scene transform")
        return self.bridge.metric_from_scene @ value

    @staticmethod
    def _matrix(value: np.ndarray, label: str) -> np.ndarray:
        result = np.asarray(value, dtype=float)
        if result.shape != (4, 4) or not np.all(np.isfinite(result)):
            raise ValueError("{}은 유한한 4x4 행렬이어야 합니다.".format(label))
        return result

    def report(
        self, metric_vertices: np.ndarray, metric_transform: np.ndarray
    ) -> Dict[str, Any]:
        metric = np.asarray(metric_vertices, dtype=float)
        scene = self.metric_vertices_to_scene(metric)
        metric_round_trip = self.scene_vertices_to_metric(scene)
        scene_transform = self.metric_transform_to_scene(metric_transform)
        metric_transform_round_trip = self.scene_transform_to_metric(scene_transform)
        vertex_error = (
            float(np.max(np.linalg.norm(metric_round_trip - metric, axis=1)))
            if len(metric)
            else 0.0
        )
        transform_error = float(
            np.max(np.abs(metric_transform_round_trip - metric_transform))
        )
        maximum = max(vertex_error, transform_error)
        return {
            "metric_to_scene_to_metric_vertex_max_error_m": vertex_error,
            "metric_to_scene_to_metric_transform_max_error": transform_error,
            "maximum_error": maximum,
            "success": maximum <= 1.0e-8,
            "metric_transform": np.asarray(metric_transform, dtype=float).tolist(),
            "scene_transform": scene_transform.tolist(),
        }
