"""법선과 장면 높이를 이용해 평면의 용도를 보수적으로 제안한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

import numpy as np

from ..config import normalize_vector


@dataclass
class ClassificationResult:
    orientation: str
    suggested_semantic: str
    confidence: float
    reason: str
    angle_to_up_deg: float
    normalized_height: float


def scene_height_range(
    points: np.ndarray,
    up_vector: np.ndarray,
    lower_percentile: float = 0.0,
    upper_percentile: float = 100.0,
) -> Dict[str, float]:
    up = normalize_vector(up_vector, "up_vector")
    heights = np.asarray(points, dtype=float) @ up
    lower, upper = np.percentile(heights, [lower_percentile, upper_percentile])
    return {
        "min": float(lower),
        "max": float(upper),
        "lower_percentile": float(lower_percentile),
        "upper_percentile": float(upper_percentile),
        "raw_min": float(np.min(heights)),
        "raw_max": float(np.max(heights)),
    }


def classify_plane(
    normal: np.ndarray,
    centroid: np.ndarray,
    up_vector: np.ndarray,
    height_range: Dict[str, float],
    settings: Dict[str, Any],
) -> ClassificationResult:
    up = normalize_vector(up_vector, "up_vector")
    n = normalize_vector(normal, "normal")
    cosine = float(np.clip(abs(np.dot(n, up)), 0.0, 1.0))
    angle = float(np.degrees(np.arccos(cosine)))

    horizontal_limit = float(settings["horizontal_max_angle_deg"])
    vertical_limit = float(settings["vertical_max_deviation_deg"])
    if angle <= horizontal_limit:
        orientation = "horizontal"
        orientation_confidence = max(0.0, 1.0 - angle / max(horizontal_limit, 1e-9))
    elif abs(90.0 - angle) <= vertical_limit:
        orientation = "vertical"
        orientation_confidence = max(
            0.0, 1.0 - abs(90.0 - angle) / max(vertical_limit, 1e-9)
        )
    else:
        orientation = "other"
        orientation_confidence = 0.0

    minimum = float(height_range["min"])
    maximum = float(height_range["max"])
    span = maximum - minimum
    height = float(np.dot(np.asarray(centroid, dtype=float), up))
    normalized_height = 0.5 if span <= 1e-12 else (height - minimum) / span
    normalized_height = float(np.clip(normalized_height, 0.0, 1.0))

    boundary_ratio = float(settings["boundary_height_ratio"])
    if orientation == "horizontal" and normalized_height <= boundary_ratio:
        semantic = "floor"
        boundary_confidence = 1.0 - normalized_height / max(boundary_ratio, 1e-9)
        confidence = 0.55 * orientation_confidence + 0.45 * boundary_confidence
        reason = "높이 방향과 거의 수직이고 장면 아래쪽 경계에 가깝습니다."
    elif orientation == "horizontal" and normalized_height >= 1.0 - boundary_ratio:
        semantic = "ceiling"
        boundary_confidence = 1.0 - (1.0 - normalized_height) / max(
            boundary_ratio, 1e-9
        )
        confidence = 0.55 * orientation_confidence + 0.45 * boundary_confidence
        reason = "높이 방향과 거의 수직이고 장면 위쪽 경계에 가깝습니다."
    elif orientation == "vertical":
        semantic = "wall"
        confidence = 0.75 * orientation_confidence
        reason = "법선이 높이 방향과 거의 직각이어서 벽 후보로 보입니다."
    elif orientation == "horizontal":
        semantic = "unknown"
        confidence = 0.35 * orientation_confidence
        reason = "수평면이지만 장면의 바닥·천장 경계에서 멀어 용도를 확정할 수 없습니다."
    else:
        semantic = "unknown"
        confidence = 0.0
        reason = "법선 방향이 수평면이나 수직면 기준과 충분히 가깝지 않습니다."

    return ClassificationResult(
        orientation=orientation,
        suggested_semantic=semantic,
        confidence=float(np.clip(confidence, 0.0, 1.0)),
        reason=reason,
        angle_to_up_deg=angle,
        normalized_height=normalized_height,
    )
