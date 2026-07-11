"""향후 Metric 좌표계에 사용할 원점과 수평 X축 후보를 진단한다."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np

from .orientation_analysis import OrientationAnalysisError, normalize_direction


def analyze_frame_candidates(
    bottom_corners: np.ndarray,
    scene_up: np.ndarray,
    tie_tolerance: float = 1.0e-8,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    bottom = np.asarray(bottom_corners, dtype=float)
    if bottom.ndim != 2 or bottom.shape[1] != 3 or len(bottom) < 3:
        raise OrientationAnalysisError("원점/X축 분석에는 bottom corner가 3개 이상 필요합니다.")
    up = normalize_direction(scene_up, "scene_up")
    warnings = []

    height_values = bottom @ up
    minimum = float(np.min(height_values))
    tied_origins = np.flatnonzero(np.abs(height_values - minimum) <= tie_tolerance)
    origin_index = int(tied_origins[0])
    if len(tied_origins) > 1:
        warnings.append(
            "가장 낮은 bottom corner가 여러 개라 가장 작은 index {}를 추천했습니다.".format(
                origin_index
            )
        )
    origin_candidates = [
        {
            "corner_index": index,
            "scene_coordinate": bottom[index].tolist(),
            "height_projection": float(height_values[index]),
        }
        for index in range(len(bottom))
    ]
    origin_result = {
        "method": "lowest_bottom_corner",
        "candidates": origin_candidates,
        "recommended_corner_index": origin_index,
        "recommended_scene_coordinate": bottom[origin_index].tolist(),
        "recommended_height_projection": float(height_values[origin_index]),
        "selection_reason": "scene up 방향 투영값이 가장 작은 bottom corner",
        "tied_candidate_indices": tied_origins.tolist(),
    }

    edge_records = []
    horizontal_lengths = []
    count = len(bottom)
    for index in range(count):
        following = (index + 1) % count
        edge = bottom[following] - bottom[index]
        up_component = float(np.dot(edge, up))
        horizontal = edge - up_component * up
        horizontal_length = float(np.linalg.norm(horizontal))
        if horizontal_length <= 1e-12:
            direction = np.zeros(3)
        else:
            direction = horizontal / horizontal_length
        horizontal_lengths.append(horizontal_length)
        edge_records.append(
            {
                "edge_index": index,
                "start_corner": index,
                "end_corner": following,
                "original_length": float(np.linalg.norm(edge)),
                "horizontal_projected_length": horizontal_length,
                "signed_up_component": up_component,
                "normalized_horizontal_direction": direction.tolist(),
            }
        )
    maximum = float(np.max(horizontal_lengths))
    if maximum <= 1e-12:
        raise OrientationAnalysisError("수평 길이가 양수인 Envelope edge가 없습니다.")
    tied_edges = np.flatnonzero(
        np.abs(np.asarray(horizontal_lengths) - maximum) <= tie_tolerance
    )
    edge_index = int(tied_edges[0])
    if len(tied_edges) > 1:
        warnings.append(
            "가장 긴 수평 edge가 여러 개라 가장 작은 index {}를 추천했습니다.".format(
                edge_index
            )
        )
    x_axis_result = {
        "method": "longest_horizontal_envelope_edge",
        "candidates": edge_records,
        "recommended_edge_index": edge_index,
        "recommended_start_corner": edge_records[edge_index]["start_corner"],
        "recommended_end_corner": edge_records[edge_index]["end_corner"],
        "recommended_horizontal_direction": edge_records[edge_index][
            "normalized_horizontal_direction"
        ],
        "recommended_horizontal_length": maximum,
        "selection_reason": "scene up 성분을 제거한 길이가 가장 긴 bottom polygon edge",
        "tied_candidate_indices": tied_edges.tolist(),
    }
    return origin_result, x_axis_result, warnings
