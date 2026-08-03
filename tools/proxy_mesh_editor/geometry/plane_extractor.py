"""Open3D RANSAC을 반복해 큰 평면 후보를 찾는다."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

import numpy as np

from ..config import normalize_vector, resolve_scene_value
from ..models import PlaneCandidate
from .plane_classifier import classify_plane, scene_height_range
from .plane_mesher import PlaneMeshingError, build_plane_rectangle, normalize_plane


LOGGER = logging.getLogger(__name__)


PALETTE = np.asarray(
    [
        [0.894, 0.102, 0.110],
        [0.216, 0.494, 0.722],
        [0.302, 0.686, 0.290],
        [0.596, 0.306, 0.639],
        [1.000, 0.498, 0.000],
        [1.000, 1.000, 0.200],
        [0.651, 0.337, 0.157],
        [0.969, 0.506, 0.749],
        [0.600, 0.600, 0.600],
        [0.121, 0.466, 0.705],
        [0.682, 0.780, 0.910],
        [1.000, 0.733, 0.470],
        [0.173, 0.627, 0.173],
        [0.839, 0.153, 0.157],
        [0.580, 0.404, 0.741],
        [0.549, 0.337, 0.294],
        [0.890, 0.467, 0.761],
        [0.498, 0.498, 0.498],
        [0.737, 0.741, 0.133],
        [0.090, 0.745, 0.811],
    ],
    dtype=float,
)


def _candidate_color(index: int) -> np.ndarray:
    return PALETTE[index % len(PALETTE)].copy()


def remove_local_inliers(
    source_cloud: Any,
    remaining_indices: np.ndarray,
    local_inliers: np.ndarray,
) -> Tuple[Any, np.ndarray]:
    """RANSAC 반복에서 이번에 뽑힌 inlier를 남은 점 집합에서 제거한다."""

    keep_mask = np.ones(len(remaining_indices), dtype=bool)
    keep_mask[np.asarray(local_inliers, dtype=int)] = False
    updated_indices = remaining_indices[keep_mask]
    updated_cloud = source_cloud.select_by_index(updated_indices.tolist())
    return updated_cloud, updated_indices


def extract_planes(
    point_cloud: Any, config: Dict[str, Any], scene_extent: float
) -> Tuple[List[PlaneCandidate], Dict[str, Any]]:
    try:
        import open3d as o3d
    except ImportError as exc:
        raise RuntimeError("평면 검출에는 Open3D가 필요합니다.") from exc

    settings = config["plane_extraction"]
    up_vector = normalize_vector(config["scene"]["up_vector"], "scene.up_vector")
    random_seed = int(config["scene"]["random_seed"])
    np.random.seed(random_seed)
    if hasattr(o3d.utility, "random"):
        o3d.utility.random.seed(random_seed)

    distance_threshold = resolve_scene_value(
        settings,
        "distance_threshold",
        "distance_threshold_ratio",
        scene_extent,
    )
    configured_min_area = settings.get("min_area")
    if configured_min_area is None:
        min_area = float(settings["min_area_ratio"]) * float(scene_extent) ** 2
    else:
        min_area = float(configured_min_area)
    if min_area <= 0.0:
        raise ValueError("평면 최소 면적은 0보다 커야 합니다.")

    component_settings = settings["inlier_components"]
    component_eps = None
    if component_settings["enabled"]:
        component_eps = resolve_scene_value(
            component_settings, "eps", "eps_ratio", scene_extent
        )

    all_points = np.asarray(point_cloud.points, dtype=float)
    initial_count = len(all_points)
    remaining_cloud = point_cloud
    remaining_indices = np.arange(initial_count, dtype=int)
    assigned = np.zeros(initial_count, dtype=bool)
    classification_settings = config["classification"]
    height_range = scene_height_range(
        all_points,
        up_vector,
        lower_percentile=float(classification_settings["height_lower_percentile"]),
        upper_percentile=float(classification_settings["height_upper_percentile"]),
    )

    accepted: List[PlaneCandidate] = []
    rejection_counts: Dict[str, int] = {
        "too_few_inliers": 0,
        "too_small_ratio": 0,
        "too_small_area": 0,
        "degenerate_rectangle": 0,
        "no_connected_component": 0,
        "connected_component_too_small": 0,
        "orientation_limit": 0,
    }
    orientation_counts = {"horizontal": 0, "vertical": 0, "other": 0}
    attempts = 0
    max_planes = int(settings["max_planes"])
    max_attempts = int(settings["max_attempts"])
    ransac_n = int(settings["ransac_n"])

    while len(accepted) < max_planes and attempts < max_attempts:
        remaining_count = len(remaining_indices)
        remaining_ratio = remaining_count / initial_count
        if remaining_count < max(ransac_n, int(settings["min_inliers"])):
            LOGGER.info("남은 점이 최소 내부점 수보다 적어 검출을 끝냅니다.")
            break
        if remaining_ratio <= float(settings["stop_remaining_ratio"]):
            LOGGER.info("남은 점 비율이 중단 기준 이하라 검출을 끝냅니다.")
            break

        attempts += 1
        plane_model, local_inliers = remaining_cloud.segment_plane(
            distance_threshold=distance_threshold,
            ransac_n=ransac_n,
            num_iterations=int(settings["num_iterations"]),
        )
        local_inliers = np.asarray(local_inliers, dtype=int)
        raw_inlier_count = len(local_inliers)
        if raw_inlier_count < int(settings["min_inliers"]):
            rejection_counts["too_few_inliers"] += 1
            break

        raw_global_inliers = remaining_indices[local_inliers]
        raw_initial_ratio = raw_inlier_count / initial_count
        if raw_initial_ratio < float(settings["min_inlier_ratio"]):
            rejection_counts["too_small_ratio"] += 1
            break

        global_inliers = raw_global_inliers
        preserve_boundary = False
        if component_eps is not None and component_settings["preserve_boundary_planes"]:
            raw_points = all_points[raw_global_inliers]
            raw_model, raw_normal = normalize_plane(
                np.asarray(plane_model, dtype=float), up_vector
            )
            raw_distances = raw_points @ raw_normal + raw_model[3]
            raw_centroid = np.mean(
                raw_points - raw_distances[:, None] * raw_normal[None, :], axis=0
            )
            raw_classification = classify_plane(
                normal=raw_normal,
                centroid=raw_centroid,
                up_vector=up_vector,
                height_range=height_range,
                settings=classification_settings,
            )
            preserve_boundary = raw_classification.suggested_semantic in {
                "floor",
                "ceiling",
            }

        if component_eps is not None and not preserve_boundary:
            inlier_cloud = remaining_cloud.select_by_index(local_inliers.tolist())
            labels = np.asarray(
                inlier_cloud.cluster_dbscan(
                    eps=component_eps,
                    min_points=int(component_settings["min_points"]),
                    print_progress=False,
                ),
                dtype=int,
            )
            valid_labels = labels[labels >= 0]
            if not len(valid_labels):
                rejection_counts["no_connected_component"] += 1
                remaining_cloud, remaining_indices = remove_local_inliers(
                    point_cloud, remaining_indices, local_inliers
                )
                continue
            component_ids, component_counts = np.unique(
                valid_labels, return_counts=True
            )
            largest_component = int(component_ids[np.argmax(component_counts)])
            component_mask = labels == largest_component
            global_inliers = raw_global_inliers[component_mask]

        inlier_count = len(global_inliers)
        initial_ratio = inlier_count / initial_count
        local_ratio = inlier_count / remaining_count
        if (
            inlier_count < int(settings["min_inliers"])
            or initial_ratio < float(settings["min_inlier_ratio"])
        ):
            rejection_counts["connected_component_too_small"] += 1
            remaining_cloud, remaining_indices = remove_local_inliers(
                point_cloud, remaining_indices, local_inliers
            )
            continue

        inlier_points = all_points[global_inliers]
        try:
            model, normal, signed_distances, rectangle = build_plane_rectangle(
                inlier_points=inlier_points,
                plane_equation=np.asarray(plane_model, dtype=float),
                up_vector=up_vector,
                settings=config["plane_meshing"],
                scene_extent=scene_extent,
            )
        except PlaneMeshingError as exc:
            rejection_counts["degenerate_rectangle"] += 1
            LOGGER.warning("퇴화한 평면 후보를 건너뜁니다: %s", exc)
            remaining_cloud, remaining_indices = remove_local_inliers(
                point_cloud, remaining_indices, local_inliers
            )
            continue

        if rectangle.area < min_area:
            rejection_counts["too_small_area"] += 1
            LOGGER.info(
                "작은 평면 후보를 건너뜁니다: 면적 %.6g < %.6g",
                rectangle.area,
                min_area,
            )
            remaining_cloud, remaining_indices = remove_local_inliers(
                point_cloud, remaining_indices, local_inliers
            )
            continue

        classification = classify_plane(
            normal=normal,
            centroid=rectangle.origin,
            up_vector=up_vector,
            height_range=height_range,
            settings=classification_settings,
        )
        limit_settings = settings["orientation_limits"]
        if (
            limit_settings["enabled"]
            and orientation_counts[classification.orientation]
            >= int(limit_settings[classification.orientation])
        ):
            rejection_counts["orientation_limit"] += 1
            remaining_cloud, remaining_indices = remove_local_inliers(
                point_cloud, remaining_indices, local_inliers
            )
            continue

        candidate_id = "plane_{:03d}".format(len(accepted))
        candidate = PlaneCandidate(
            candidate_id=candidate_id,
            plane_equation=model,
            normal=normal,
            centroid=rectangle.origin,
            inlier_count=inlier_count,
            raw_ransac_inlier_count=raw_inlier_count,
            inlier_ratio=initial_ratio,
            remaining_inlier_ratio=local_ratio,
            fitting_rmse=float(np.sqrt(np.mean(np.square(signed_distances)))),
            mean_absolute_distance=float(np.mean(np.abs(signed_distances))),
            rectangle=rectangle,
            orientation=classification.orientation,
            suggested_semantic=classification.suggested_semantic,
            semantic_confidence=classification.confidence,
            semantic_reason=(
                "{} 높이 정규화값={:.3f}, 높이축과 법선 사이 각도={:.2f}도.".format(
                    classification.reason,
                    classification.normalized_height,
                    classification.angle_to_up_deg,
                )
            ),
            color=_candidate_color(len(accepted)),
            inlier_indices=global_inliers.copy(),
        )
        accepted.append(candidate)
        orientation_counts[classification.orientation] += 1
        assigned[global_inliers] = True
        LOGGER.info(
            "%s 승인: 연결점 %d개/평면점 %d개, 면적 %.6g, 제안 %s (신뢰도 %.2f)",
            candidate_id,
            inlier_count,
            raw_inlier_count,
            rectangle.area,
            classification.suggested_semantic,
            classification.confidence,
        )

        remaining_cloud, remaining_indices = remove_local_inliers(
            point_cloud, remaining_indices, local_inliers
        )

    stats = {
        "initial_point_count": initial_count,
        "assigned_point_count": int(np.count_nonzero(assigned)),
        "residual_point_count": int(initial_count - np.count_nonzero(assigned)),
        "accepted_candidate_count": len(accepted),
        "attempt_count": attempts,
        "rejections": rejection_counts,
        "accepted_orientation_counts": orientation_counts,
        "resolved_thresholds": {
            "distance_threshold": distance_threshold,
            "min_area": min_area,
            "inlier_component_eps": component_eps,
        },
        "height_range_along_up_vector": height_range,
    }
    return accepted, stats
