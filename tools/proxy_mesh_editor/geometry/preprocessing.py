"""평면 검출용 점구름에 선택 가능한 보수적 전처리를 적용한다."""

from __future__ import annotations

import logging
from typing import Any, Dict, Tuple

import numpy as np

from ..config import resolve_scene_value


LOGGER = logging.getLogger(__name__)


def _bounds_dict(point_cloud: Any) -> Dict[str, Any]:
    box = point_cloud.get_axis_aligned_bounding_box()
    minimum = np.asarray(box.min_bound, dtype=float)
    maximum = np.asarray(box.max_bound, dtype=float)
    extent = maximum - minimum
    return {
        "min": minimum.tolist(),
        "max": maximum.tolist(),
        "extent": extent.tolist(),
        "diagonal": float(np.linalg.norm(extent)),
    }


def preprocess_point_cloud(
    point_cloud: Any, config: Dict[str, Any], scene_extent: float
) -> Tuple[Any, Dict[str, Any]]:
    settings = config["preprocessing"]
    initial_count = len(point_cloud.points)
    stage_counts: Dict[str, Any] = {"initial": initial_count}
    used_values: Dict[str, Any] = {}

    voxel = settings["voxel_downsampling"]
    if voxel["enabled"]:
        voxel_size = resolve_scene_value(
            voxel, "voxel_size", "voxel_size_ratio", scene_extent
        )
        before = len(point_cloud.points)
        point_cloud = point_cloud.voxel_down_sample(voxel_size=voxel_size)
        after = len(point_cloud.points)
        stage_counts["voxel_downsampling"] = {
            "before": before,
            "after": after,
            "removed": before - after,
        }
        used_values["voxel_size"] = voxel_size
        LOGGER.info(
            "격자 간격 줄이기: %d -> %d점 (간격 %.6g)", before, after, voxel_size
        )
    else:
        stage_counts["voxel_downsampling"] = {"enabled": False}
        used_values["voxel_size"] = None

    statistical = settings["statistical_outlier_removal"]
    if statistical["enabled"]:
        before = len(point_cloud.points)
        point_cloud, _ = point_cloud.remove_statistical_outlier(
            nb_neighbors=int(statistical["nb_neighbors"]),
            std_ratio=float(statistical["std_ratio"]),
        )
        after = len(point_cloud.points)
        stage_counts["statistical_outlier_removal"] = {
            "before": before,
            "after": after,
            "removed": before - after,
        }
        LOGGER.info("통계 기반 이상점 제거: %d -> %d점", before, after)
    else:
        stage_counts["statistical_outlier_removal"] = {"enabled": False}

    radius = settings["radius_outlier_removal"]
    if radius["enabled"]:
        radius_value = resolve_scene_value(
            radius, "radius", "radius_ratio", scene_extent
        )
        before = len(point_cloud.points)
        point_cloud, _ = point_cloud.remove_radius_outlier(
            nb_points=int(radius["nb_points"]), radius=radius_value
        )
        after = len(point_cloud.points)
        stage_counts["radius_outlier_removal"] = {
            "before": before,
            "after": after,
            "removed": before - after,
        }
        used_values["radius_outlier_radius"] = radius_value
        LOGGER.info("반경 기반 이상점 제거: %d -> %d점", before, after)
    else:
        stage_counts["radius_outlier_removal"] = {"enabled": False}
        used_values["radius_outlier_radius"] = None

    if len(point_cloud.points) < 3:
        raise ValueError(
            "전처리 후 점이 3개보다 적습니다. 격자 간격과 이상점 제거 설정을 완화해 주세요."
        )

    normals = settings["normal_estimation"]
    if normals["enabled"]:
        try:
            import open3d as o3d
        except ImportError as exc:
            raise RuntimeError("법선 추정에는 Open3D가 필요합니다.") from exc
        search_radius = resolve_scene_value(
            normals, "search_radius", "search_radius_ratio", scene_extent
        )
        point_cloud.estimate_normals(
            search_param=o3d.geometry.KDTreeSearchParamHybrid(
                radius=search_radius, max_nn=int(normals["max_nn"])
            )
        )
        used_values["normal_search_radius"] = search_radius
        stage_counts["normal_estimation"] = {
            "enabled": True,
            "point_count": len(point_cloud.points),
        }
        LOGGER.info("점 법선 추정 완료 (검색 반경 %.6g)", search_radius)
    else:
        used_values["normal_search_radius"] = None
        stage_counts["normal_estimation"] = {"enabled": False}

    final_count = len(point_cloud.points)
    stats = {
        "before_point_count": initial_count,
        "after_point_count": final_count,
        "removed_point_count": initial_count - final_count,
        "bounds_after": _bounds_dict(point_cloud),
        "scene_extent": float(scene_extent),
        "stages": stage_counts,
        "used_values": used_values,
    }
    return point_cloud, stats

