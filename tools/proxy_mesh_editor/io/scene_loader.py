"""PGSR 메시와 선택적 참고 점구름을 Open3D로 읽는다."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np


LOGGER = logging.getLogger(__name__)


class SceneLoadError(RuntimeError):
    """장면 파일을 정상적으로 불러오지 못했을 때 발생한다."""


def _open3d():
    try:
        import open3d as o3d
    except ImportError as exc:
        raise SceneLoadError(
            "Open3D가 설치되어 있지 않습니다. pgsr 환경을 활성화하거나 "
            "tools/proxy_mesh_editor/requirements.txt를 설치해 주세요."
        ) from exc
    return o3d


@dataclass
class LoadedScene:
    mesh: Any
    point_cloud: Any
    source_mesh: Path
    reference_point_cloud: Optional[Path]
    point_source: str
    input_stats: Dict[str, Any]
    mesh_filter_stats: Dict[str, Any]


def _bounds_dict(geometry: Any) -> Dict[str, Any]:
    box = geometry.get_axis_aligned_bounding_box()
    minimum = np.asarray(box.min_bound, dtype=float)
    maximum = np.asarray(box.max_bound, dtype=float)
    extent = maximum - minimum
    return {
        "min": minimum.tolist(),
        "max": maximum.tolist(),
        "extent": extent.tolist(),
        "diagonal": float(np.linalg.norm(extent)),
    }


def _validate_ply(path: Path, label: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise SceneLoadError("{} 파일을 찾을 수 없습니다: {}".format(label, resolved))
    if resolved.suffix.lower() != ".ply":
        raise SceneLoadError("{}는 PLY 파일이어야 합니다: {}".format(label, resolved))
    return resolved


def filter_mesh_components(mesh: Any, settings: Dict[str, Any]) -> Dict[str, Any]:
    """삼각형 연결 조각 중 설정 기준보다 작은 조각을 제거한다."""

    o3d = _open3d()
    before_triangles = len(mesh.triangles)
    before_vertices = len(mesh.vertices)
    stats = {
        "enabled": bool(settings["enabled"]),
        "before_vertices": before_vertices,
        "before_triangles": before_triangles,
        "after_vertices": before_vertices,
        "after_triangles": before_triangles,
        "removed_triangles": 0,
        "component_count": None,
    }
    if not settings["enabled"]:
        return stats

    LOGGER.info("연결된 메시 조각을 분석합니다. 큰 메시에서는 시간이 걸릴 수 있습니다.")
    labels, triangle_counts, areas = mesh.cluster_connected_triangles()
    labels = np.asarray(labels, dtype=int)
    triangle_counts = np.asarray(triangle_counts, dtype=int)
    areas = np.asarray(areas, dtype=float)
    stats["component_count"] = int(len(triangle_counts))
    if not len(triangle_counts):
        raise SceneLoadError("메시에서 연결된 삼각형 조각을 찾지 못했습니다.")

    keep = np.ones(len(triangle_counts), dtype=bool)
    min_triangles = int(settings["min_triangles"])
    keep &= triangle_counts >= min_triangles

    min_area_ratio = float(settings["min_area_ratio"])
    if min_area_ratio > 0.0:
        total_area = float(np.sum(areas))
        keep &= areas >= total_area * min_area_ratio

    keep_largest = int(settings["keep_largest"])
    if keep_largest > 0:
        largest = np.argsort(triangle_counts)[-keep_largest:]
        largest_mask = np.zeros(len(triangle_counts), dtype=bool)
        largest_mask[largest] = True
        keep &= largest_mask

    if not np.any(keep):
        raise SceneLoadError(
            "메시 조각 필터가 모든 삼각형을 제거합니다. 설정 기준을 낮춰 주세요."
        )

    remove_mask = ~keep[labels]
    mesh.remove_triangles_by_mask(remove_mask)
    mesh.remove_unreferenced_vertices()
    mesh.remove_degenerate_triangles()
    stats.update(
        {
            "after_vertices": len(mesh.vertices),
            "after_triangles": len(mesh.triangles),
            "removed_triangles": int(np.count_nonzero(remove_mask)),
        }
    )
    return stats


def load_scene(
    mesh_path: Path,
    reference_point_cloud_path: Optional[Path],
    config: Dict[str, Any],
) -> LoadedScene:
    o3d = _open3d()
    mesh_file = _validate_ply(mesh_path, "입력 메시")
    reference_file = None
    if reference_point_cloud_path is not None:
        reference_file = _validate_ply(reference_point_cloud_path, "참고 점구름")

    LOGGER.info("메시를 읽습니다: %s", mesh_file)
    mesh = o3d.io.read_triangle_mesh(str(mesh_file), enable_post_processing=False)
    if mesh.is_empty() or len(mesh.vertices) == 0 or len(mesh.triangles) == 0:
        raise SceneLoadError(
            "삼각형 메시를 읽지 못했습니다. 꼭짓점과 삼각형이 있는 PLY인지 확인해 주세요: {}".format(
                mesh_file
            )
        )

    original_stats = {
        "vertex_count": len(mesh.vertices),
        "triangle_count": len(mesh.triangles),
        "bounds": _bounds_dict(mesh),
        "surface_area": float(mesh.get_surface_area()),
    }
    mesh_filter_stats = filter_mesh_components(
        mesh, config["preprocessing"]["mesh_components"]
    )
    filtered_stats = {
        "vertex_count": len(mesh.vertices),
        "triangle_count": len(mesh.triangles),
        "bounds": _bounds_dict(mesh),
        "surface_area": float(mesh.get_surface_area()),
    }

    point_source = config["scene"]["point_source"]
    if point_source == "mesh_vertices":
        point_cloud = o3d.geometry.PointCloud()
        point_cloud.points = o3d.utility.Vector3dVector(np.asarray(mesh.vertices))
        if mesh.has_vertex_colors():
            point_cloud.colors = o3d.utility.Vector3dVector(
                np.asarray(mesh.vertex_colors)
            )
    elif point_source == "mesh_uniform":
        sample_count = int(
            config["preprocessing"]["sampling"]["number_of_points"]
        )
        point_cloud = mesh.sample_points_uniformly(
            number_of_points=sample_count, use_triangle_normal=True
        )
    else:
        if reference_file is None:
            raise SceneLoadError(
                "point_source가 reference_point_cloud이면 "
                "--reference-point-cloud 인자가 필요합니다."
            )
        LOGGER.info("참고 점구름을 읽습니다: %s", reference_file)
        point_cloud = o3d.io.read_point_cloud(str(reference_file))
        if point_cloud.is_empty() or len(point_cloud.points) == 0:
            raise SceneLoadError(
                "참고 점구름에서 점을 읽지 못했습니다: {}".format(reference_file)
            )

    if point_cloud.is_empty() or len(point_cloud.points) < 3:
        raise SceneLoadError("평면 검출에 사용할 점이 3개보다 적습니다.")

    input_stats = {
        "original_mesh": original_stats,
        "filtered_mesh": filtered_stats,
        "detection_points_before_preprocessing": len(point_cloud.points),
        "detection_point_bounds": _bounds_dict(point_cloud),
    }
    return LoadedScene(
        mesh=mesh,
        point_cloud=point_cloud,
        source_mesh=mesh_file,
        reference_point_cloud=reference_file,
        point_source=point_source,
        input_stats=input_stats,
        mesh_filter_stats=mesh_filter_stats,
    )
