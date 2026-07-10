"""법선으로 수직면 가능 점을 고른 뒤 벽 평면만 반복 검출한다."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

import numpy as np

from ..config import ConfigError, normalize_vector, resolve_scene_value
from ..models import PlaneCandidate
from .normal_analyzer import NormalAnalysisError, compute_normal_up_scores
from .plane_classifier import scene_height_range
from .plane_mesher import PlaneMeshingError, build_plane_rectangle, normalize_plane


LOGGER = logging.getLogger(__name__)


WALL_PALETTE = np.asarray(
    [
        [0.894, 0.102, 0.110],
        [0.216, 0.494, 0.722],
        [0.302, 0.686, 0.290],
        [0.596, 0.306, 0.639],
        [1.000, 0.498, 0.000],
        [1.000, 1.000, 0.200],
        [0.651, 0.337, 0.157],
        [0.969, 0.506, 0.749],
        [0.121, 0.466, 0.705],
        [0.682, 0.780, 0.910],
        [1.000, 0.733, 0.470],
        [0.173, 0.627, 0.173],
    ],
    dtype=float,
)


def _wall_color(index: int) -> np.ndarray:
    return WALL_PALETTE[index % len(WALL_PALETTE)].copy()


def _remove_local_inliers(
    source_cloud: Any,
    remaining_indices: np.ndarray,
    local_inliers: np.ndarray,
) -> Tuple[Any, np.ndarray]:
    keep = np.ones(len(remaining_indices), dtype=bool)
    keep[np.asarray(local_inliers, dtype=int)] = False
    updated_indices = remaining_indices[keep]
    return source_cloud.select_by_index(updated_indices.tolist()), updated_indices


def filter_vertical_points(
    point_cloud: Any, up_vector: np.ndarray, settings: Dict[str, Any]
) -> Tuple[Any, Dict[str, Any]]:
    """법선 필터를 적용한 벽 RANSAC 입력 점구름과 통계를 반환한다."""

    point_count = len(point_cloud.points)
    has_normals = point_cloud.has_normals() and len(point_cloud.normals) == point_count
    if has_normals:
        scores, valid = compute_normal_up_scores(
            np.asarray(point_cloud.normals, dtype=float), up_vector
        )
    else:
        scores = np.full(point_count, np.nan, dtype=float)
        valid = np.zeros(point_count, dtype=bool)

    enabled = bool(settings["enabled"])
    threshold = float(settings["point_normal_max_up_dot"])
    if enabled:
        if not has_normals:
            raise NormalAnalysisError(
                "벽 법선 필터를 켰지만 전처리된 점구름에 법선이 없습니다. "
                "preprocessing.normal_estimation.enabled를 켜 주세요."
            )
        if not np.any(valid):
            raise NormalAnalysisError("벽 법선 필터에 사용할 유효 법선이 하나도 없습니다.")
        selected_mask = valid & (scores <= threshold)
    else:
        selected_mask = np.ones(point_count, dtype=bool)

    selected_indices = np.flatnonzero(selected_mask)
    filtered = point_cloud.select_by_index(selected_indices.tolist())
    stats = {
        "enabled": enabled,
        "point_normal_max_up_dot": threshold,
        "preprocessed_point_count": int(point_count),
        "valid_normal_count": int(np.count_nonzero(valid)),
        "invalid_normal_count": int(point_count - np.count_nonzero(valid)),
        "normal_filtered_point_count": int(len(selected_indices)),
        "normal_filtered_ratio": float(len(selected_indices) / max(point_count, 1)),
    }
    return filtered, stats


def _wall_local_axes(
    plane_normal: np.ndarray, up_vector: np.ndarray
) -> Tuple[np.ndarray, np.ndarray]:
    normal = normalize_vector(plane_normal, "plane_normal")
    up = normalize_vector(up_vector, "up_vector")
    vertical = up - float(np.dot(up, normal)) * normal
    vertical_length = float(np.linalg.norm(vertical))
    if vertical_length <= 1e-12:
        raise PlaneMeshingError("벽 평면 내부의 높이축을 계산할 수 없습니다.")
    vertical = vertical / vertical_length
    horizontal = np.cross(vertical, normal)
    horizontal = normalize_vector(horizontal, "wall_horizontal_axis")
    dominant = int(np.argmax(np.abs(horizontal)))
    if horizontal[dominant] < 0.0:
        horizontal = -horizontal
    if float(np.dot(vertical, up)) < 0.0:
        vertical = -vertical
    return horizontal, vertical


def _component_record(
    component_id: int,
    points: np.ndarray,
    up_vector: np.ndarray,
    horizontal_axis: np.ndarray,
    vertical_axis: np.ndarray,
    min_points: int,
    min_vertical_span: float,
) -> Dict[str, Any]:
    heights = points @ up_vector
    horizontal_values = points @ horizontal_axis
    vertical_values = points @ vertical_axis
    vertical_span = float(np.max(heights) - np.min(heights))
    horizontal_span = float(np.max(horizontal_values) - np.min(horizontal_values))
    valid_points = len(points) >= min_points
    valid_height = vertical_span >= min_vertical_span
    reasons = []
    if not valid_points:
        reasons.append("too_few_points")
    if not valid_height:
        reasons.append("too_short_vertical_span")
    return {
        "component_id": int(component_id),
        "point_count": int(len(points)),
        "centroid": np.mean(points, axis=0).tolist(),
        "vertical_span": vertical_span,
        "horizontal_span": horizontal_span,
        "bounds_2d": {
            "u_min": float(np.min(horizontal_values)),
            "u_max": float(np.max(horizontal_values)),
            "v_min": float(np.min(vertical_values)),
            "v_max": float(np.max(vertical_values)),
        },
        "estimated_area": float(vertical_span * horizontal_span),
        "valid": bool(valid_points and valid_height),
        "used": False,
        "rejection_reasons": reasons,
    }


def select_wall_components(
    inlier_points: np.ndarray,
    labels: np.ndarray,
    plane_normal: np.ndarray,
    up_vector: np.ndarray,
    min_points: int,
    min_vertical_span: float,
    merge_valid_components: bool,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """동일 RANSAC 평면의 유효 연결 묶음을 선택하거나 합친다."""

    points = np.asarray(inlier_points, dtype=float)
    label_values = np.asarray(labels, dtype=int)
    if len(points) != len(label_values):
        raise ValueError("연결 묶음 라벨 수가 RANSAC 내부점 수와 다릅니다.")
    horizontal_axis, vertical_axis = _wall_local_axes(plane_normal, up_vector)
    up = normalize_vector(up_vector, "up_vector")

    records = []
    indices_by_id: Dict[int, np.ndarray] = {}
    for component_id in sorted(int(value) for value in np.unique(label_values) if value >= 0):
        indices = np.flatnonzero(label_values == component_id)
        indices_by_id[component_id] = indices
        records.append(
            _component_record(
                component_id,
                points[indices],
                up,
                horizontal_axis,
                vertical_axis,
                min_points,
                min_vertical_span,
            )
        )

    valid_records = [record for record in records if record["valid"]]
    if merge_valid_components:
        selected_ids = {record["component_id"] for record in valid_records}
    elif valid_records:
        largest = sorted(
            valid_records,
            key=lambda record: (-record["point_count"], record["component_id"]),
        )[0]
        selected_ids = {largest["component_id"]}
    else:
        selected_ids = set()

    selected_parts = []
    for record in records:
        if record["component_id"] in selected_ids:
            record["used"] = True
            selected_parts.append(indices_by_id[record["component_id"]])
        elif record["valid"] and not merge_valid_components:
            record["rejection_reasons"] = ["not_largest_valid_component"]

    if selected_parts:
        selected_indices = np.sort(np.concatenate(selected_parts)).astype(int)
    else:
        selected_indices = np.empty(0, dtype=int)
    noise_count = int(np.count_nonzero(label_values < 0))
    summary = {
        "component_count": int(len(records)),
        "valid_component_count": int(len(valid_records)),
        "used_component_count": int(len(selected_ids)),
        "merged_component_count": int(len(selected_ids)),
        "excluded_component_count": int(len(records) - len(selected_ids)),
        "noise_point_count": noise_count,
        "merge_valid_components": bool(merge_valid_components),
        "components": records,
    }
    return selected_indices, summary


def _resolve_positive_scaled_value(
    section: Dict[str, Any], absolute_key: str, ratio_key: str, reference: float
) -> float:
    absolute = section.get(absolute_key)
    value = float(absolute) if absolute is not None else float(section[ratio_key]) * reference
    if not np.isfinite(value) or value <= 0.0:
        raise ConfigError(
            "{} 또는 {}로 계산한 값은 0보다 커야 합니다.".format(
                absolute_key, ratio_key
            )
        )
    return value


def extract_wall_planes(
    point_cloud: Any, config: Dict[str, Any], scene_extent: float
) -> Tuple[Any, List[PlaneCandidate], Dict[str, Any], np.ndarray]:
    """전처리 원본에서 벽 후보와 벽 필터 잔여점 정보를 만든다."""

    try:
        import open3d as o3d
    except ImportError as exc:
        raise RuntimeError("벽 평면 검출에는 Open3D가 필요합니다.") from exc

    wall_settings = config["wall_extraction"]
    if not wall_settings["enabled"]:
        raise ConfigError(
            "wall_extraction.enabled가 false입니다. extract-walls를 실행하려면 true로 바꿔 주세요."
        )
    up = normalize_vector(config["scene"]["up_vector"], "scene.up_vector")
    random_seed = int(config["scene"]["random_seed"])
    np.random.seed(random_seed)
    if hasattr(o3d.utility, "random"):
        o3d.utility.random.seed(random_seed)

    wall_cloud, normal_stats = filter_vertical_points(
        point_cloud, up, wall_settings["normal_filter"]
    )
    all_points = np.asarray(wall_cloud.points, dtype=float)
    initial_count = len(all_points)
    assigned = np.zeros(initial_count, dtype=bool)

    ransac = wall_settings["ransac"]
    components = wall_settings["components"]
    meshing = wall_settings["meshing"]
    distance_threshold = resolve_scene_value(
        ransac, "distance_threshold", "distance_threshold_ratio", scene_extent
    )
    component_eps = None
    if components["enabled"]:
        component_eps = resolve_scene_value(
            components, "eps", "eps_ratio", scene_extent
        )

    preprocessed_points = np.asarray(point_cloud.points, dtype=float)
    height_range = scene_height_range(
        preprocessed_points,
        up,
        lower_percentile=float(config["classification"]["height_lower_percentile"]),
        upper_percentile=float(config["classification"]["height_upper_percentile"]),
    )
    scene_height = float(height_range["max"] - height_range["min"])
    min_vertical_span = _resolve_positive_scaled_value(
        components,
        "min_vertical_span",
        "min_vertical_span_ratio",
        scene_height,
    )
    min_area = _resolve_positive_scaled_value(
        meshing, "min_area", "min_area_ratio", float(scene_extent) ** 2
    )
    rectangle_settings = dict(config["plane_meshing"])
    rectangle_settings.update(
        {
            "lower_percentile": meshing["lower_percentile"],
            "upper_percentile": meshing["upper_percentile"],
            "margin_ratio": meshing["margin_ratio"],
        }
    )

    rejection_counts = {
        "too_few_inliers": 0,
        "too_small_ratio": 0,
        "consecutive_small_plane_stop": 0,
        "non_vertical_plane": 0,
        "component_rejection": 0,
        "too_small_area": 0,
        "degenerate_rectangle": 0,
    }
    accepted: List[PlaneCandidate] = []
    attempts = 0
    consecutive_small = 0
    stop_reason = "input_exhausted"

    remaining_cloud = wall_cloud
    remaining_indices = np.arange(initial_count, dtype=int)
    min_inliers = int(ransac["min_inliers"])
    ransac_n = int(ransac["ransac_n"])
    max_attempts = int(ransac["max_attempts"])
    max_planes = int(ransac["max_planes"])
    min_ratio = float(ransac["min_inlier_ratio"])
    max_small = int(ransac["max_consecutive_small_planes"])
    plane_normal_limit = float(ransac["plane_normal_max_up_dot"])

    while len(accepted) < max_planes and attempts < max_attempts:
        remaining_count = len(remaining_indices)
        if initial_count == 0 or remaining_count < max(ransac_n, min_inliers):
            stop_reason = "too_few_remaining_points"
            break
        attempts += 1
        plane_model, local_inliers = remaining_cloud.segment_plane(
            distance_threshold=distance_threshold,
            ransac_n=ransac_n,
            num_iterations=int(ransac["num_iterations"]),
        )
        local_inliers = np.asarray(local_inliers, dtype=int)
        raw_count = len(local_inliers)
        if raw_count < min_inliers:
            rejection_counts["too_few_inliers"] += 1
            stop_reason = "too_few_inliers"
            break

        raw_global = remaining_indices[local_inliers]
        raw_ratio = raw_count / initial_count
        if raw_ratio < min_ratio:
            rejection_counts["too_small_ratio"] += 1
            consecutive_small += 1
            remaining_cloud, remaining_indices = _remove_local_inliers(
                wall_cloud, remaining_indices, local_inliers
            )
            if consecutive_small >= max_small:
                rejection_counts["consecutive_small_plane_stop"] += 1
                stop_reason = "consecutive_small_plane_stop"
                break
            continue
        consecutive_small = 0

        try:
            normalized_model, plane_normal = normalize_plane(
                np.asarray(plane_model, dtype=float), up
            )
        except PlaneMeshingError:
            rejection_counts["degenerate_rectangle"] += 1
            remaining_cloud, remaining_indices = _remove_local_inliers(
                wall_cloud, remaining_indices, local_inliers
            )
            continue

        normal_up_dot = float(abs(np.dot(plane_normal, up)))
        if normal_up_dot > plane_normal_limit:
            rejection_counts["non_vertical_plane"] += 1
            remaining_cloud, remaining_indices = _remove_local_inliers(
                wall_cloud, remaining_indices, local_inliers
            )
            continue

        raw_points = all_points[raw_global]
        if components["enabled"]:
            inlier_cloud = remaining_cloud.select_by_index(local_inliers.tolist())
            labels = np.asarray(
                inlier_cloud.cluster_dbscan(
                    eps=float(component_eps),
                    min_points=int(components["min_points"]),
                    print_progress=False,
                ),
                dtype=int,
            )
            support_local, component_summary = select_wall_components(
                raw_points,
                labels,
                plane_normal,
                up,
                min_points=int(components["min_points"]),
                min_vertical_span=min_vertical_span,
                merge_valid_components=bool(components["merge_valid_components"]),
            )
            component_summary["enabled"] = True
        else:
            labels = np.zeros(raw_count, dtype=int)
            support_local = np.arange(raw_count, dtype=int)
            _, component_summary = select_wall_components(
                raw_points,
                labels,
                plane_normal,
                up,
                min_points=1,
                min_vertical_span=0.0,
                merge_valid_components=True,
            )
            component_summary["enabled"] = False

        support_global = raw_global[support_local]
        support_count = len(support_global)
        support_ratio = support_count / initial_count
        if support_count < min_inliers or support_ratio < min_ratio:
            rejection_counts["component_rejection"] += 1
            remaining_cloud, remaining_indices = _remove_local_inliers(
                wall_cloud, remaining_indices, local_inliers
            )
            continue

        support_points = all_points[support_global]
        try:
            model, normal, signed_distances, rectangle = build_plane_rectangle(
                inlier_points=support_points,
                plane_equation=normalized_model,
                up_vector=up,
                settings=rectangle_settings,
                scene_extent=scene_extent,
            )
        except PlaneMeshingError as exc:
            rejection_counts["degenerate_rectangle"] += 1
            LOGGER.warning("퇴화한 벽 후보를 건너뜁니다: %s", exc)
            remaining_cloud, remaining_indices = _remove_local_inliers(
                wall_cloud, remaining_indices, local_inliers
            )
            continue

        if rectangle.area < min_area:
            rejection_counts["too_small_area"] += 1
            remaining_cloud, remaining_indices = _remove_local_inliers(
                wall_cloud, remaining_indices, local_inliers
            )
            continue

        heights = support_points @ up
        vertical_span = float(np.max(heights) - np.min(heights))
        candidate_id = "wall_{:03d}".format(len(accepted))
        details = {
            "normal_up_absolute_dot": normal_up_dot,
            "raw_ransac_inlier_count": int(raw_count),
            "final_support_point_count": int(support_count),
            "vertical_span": vertical_span,
            **component_summary,
        }
        candidate = PlaneCandidate(
            candidate_id=candidate_id,
            plane_equation=model,
            normal=normal,
            centroid=rectangle.origin,
            inlier_count=support_count,
            raw_ransac_inlier_count=raw_count,
            inlier_ratio=support_ratio,
            remaining_inlier_ratio=float(support_count / remaining_count),
            fitting_rmse=float(np.sqrt(np.mean(np.square(signed_distances)))),
            mean_absolute_distance=float(np.mean(np.abs(signed_distances))),
            rectangle=rectangle,
            orientation="vertical",
            suggested_semantic="wall",
            semantic_confidence=float(np.clip(1.0 - normal_up_dot, 0.0, 1.0)),
            semantic_reason=(
                "벽 전용 추출에서 법선과 높이 방향의 절댓값 내적이 "
                "{:.6f}로 기준 {:.6f} 이하입니다.".format(
                    normal_up_dot, plane_normal_limit
                )
            ),
            color=_wall_color(len(accepted)),
            source_pass="wall_extraction",
            extraction_details=details,
            inlier_indices=support_global.copy(),
        )
        accepted.append(candidate)
        assigned[support_global] = True
        LOGGER.info(
            "%s 승인: 지지점 %d개/평면점 %d개, 연결 묶음 %d개, 면적 %.6g",
            candidate_id,
            support_count,
            raw_count,
            component_summary["used_component_count"],
            rectangle.area,
        )
        remaining_cloud, remaining_indices = _remove_local_inliers(
            wall_cloud, remaining_indices, local_inliers
        )

    if len(accepted) >= max_planes:
        stop_reason = "max_planes"
    elif attempts >= max_attempts:
        stop_reason = "max_attempts"

    stats = {
        "initial_preprocessed_point_count": int(len(point_cloud.points)),
        "valid_normal_count": normal_stats["valid_normal_count"],
        "invalid_normal_count": normal_stats["invalid_normal_count"],
        "normal_filtered_point_count": int(initial_count),
        "normal_filtered_ratio": normal_stats["normal_filtered_ratio"],
        "attempt_count": int(attempts),
        "accepted_wall_count": int(len(accepted)),
        "assigned_wall_point_count": int(np.count_nonzero(assigned)),
        "residual_wall_point_count": int(initial_count - np.count_nonzero(assigned)),
        "rejections": rejection_counts,
        "stop_reason": stop_reason,
        "normal_filter": normal_stats,
        "resolved_thresholds": {
            "distance_threshold": float(distance_threshold),
            "component_eps": float(component_eps) if component_eps is not None else None,
            "min_vertical_span": float(min_vertical_span),
            "min_area": float(min_area),
        },
        "scene_height_range_along_up_vector": height_range,
    }
    return wall_cloud, accepted, stats, assigned
