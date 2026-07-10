"""평면 후보와 사각형 메시의 공통 자료 구조."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np


ALLOWED_SEMANTICS = (
    "floor",
    "wall",
    "ceiling",
    "unknown",
    "door",
    "blackboard",
    "desk",
)


def _float_list(values: np.ndarray) -> List[float]:
    return [float(value) for value in np.asarray(values).reshape(-1)]


@dataclass
class PlaneRectangle:
    origin: np.ndarray
    basis_u: np.ndarray
    basis_v: np.ndarray
    bounds_2d: Dict[str, float]
    corners: np.ndarray
    width: float
    height: float
    area: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "origin": _float_list(self.origin),
            "basis_u": _float_list(self.basis_u),
            "basis_v": _float_list(self.basis_v),
            "bounds_2d": {key: float(value) for key, value in self.bounds_2d.items()},
            "corners": [
                _float_list(corner) for corner in np.asarray(self.corners, dtype=float)
            ],
            "width": float(self.width),
            "height": float(self.height),
            "area": float(self.area),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlaneRectangle":
        return cls(
            origin=np.asarray(data["origin"], dtype=float),
            basis_u=np.asarray(data["basis_u"], dtype=float),
            basis_v=np.asarray(data["basis_v"], dtype=float),
            bounds_2d={key: float(value) for key, value in data["bounds_2d"].items()},
            corners=np.asarray(data["corners"], dtype=float),
            width=float(data["width"]),
            height=float(data["height"]),
            area=float(data["area"]),
        )


@dataclass
class PlaneCandidate:
    candidate_id: str
    plane_equation: np.ndarray
    normal: np.ndarray
    centroid: np.ndarray
    inlier_count: int
    raw_ransac_inlier_count: int
    inlier_ratio: float
    remaining_inlier_ratio: float
    fitting_rmse: float
    mean_absolute_distance: float
    rectangle: PlaneRectangle
    orientation: str
    suggested_semantic: str
    semantic_confidence: float
    semantic_reason: str
    color: np.ndarray
    inlier_indices: Optional[np.ndarray] = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "plane_equation": _float_list(self.plane_equation),
            "normalized_normal": _float_list(self.normal),
            "centroid": _float_list(self.centroid),
            "inlier_count": int(self.inlier_count),
            "raw_ransac_inlier_count": int(self.raw_ransac_inlier_count),
            "inlier_ratio": float(self.inlier_ratio),
            "remaining_inlier_ratio": float(self.remaining_inlier_ratio),
            "fitting_rmse": float(self.fitting_rmse),
            "mean_absolute_distance": float(self.mean_absolute_distance),
            "estimated_width": float(self.rectangle.width),
            "estimated_height": float(self.rectangle.height),
            "estimated_area": float(self.rectangle.area),
            "projected_bounds": self.rectangle.to_dict(),
            "corners_3d": [
                _float_list(corner) for corner in self.rectangle.corners
            ],
            "orientation": self.orientation,
            "suggested_semantic": self.suggested_semantic,
            "semantic_confidence": float(self.semantic_confidence),
            "semantic_reason": self.semantic_reason,
            "preview_color": _float_list(self.color),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlaneCandidate":
        rectangle_data = data.get("projected_bounds", {})
        if "corners" not in rectangle_data:
            rectangle_data = dict(rectangle_data)
            rectangle_data["corners"] = data["corners_3d"]
            rectangle_data["width"] = data["estimated_width"]
            rectangle_data["height"] = data["estimated_height"]
            rectangle_data["area"] = data["estimated_area"]
        return cls(
            candidate_id=str(data["candidate_id"]),
            plane_equation=np.asarray(data["plane_equation"], dtype=float),
            normal=np.asarray(data["normalized_normal"], dtype=float),
            centroid=np.asarray(data["centroid"], dtype=float),
            inlier_count=int(data["inlier_count"]),
            raw_ransac_inlier_count=int(
                data.get("raw_ransac_inlier_count", data["inlier_count"])
            ),
            inlier_ratio=float(data["inlier_ratio"]),
            remaining_inlier_ratio=float(data.get("remaining_inlier_ratio", 0.0)),
            fitting_rmse=float(data["fitting_rmse"]),
            mean_absolute_distance=float(data["mean_absolute_distance"]),
            rectangle=PlaneRectangle.from_dict(rectangle_data),
            orientation=str(data["orientation"]),
            suggested_semantic=str(data["suggested_semantic"]),
            semantic_confidence=float(data["semantic_confidence"]),
            semantic_reason=str(data["semantic_reason"]),
            color=np.asarray(data["preview_color"], dtype=float),
        )
