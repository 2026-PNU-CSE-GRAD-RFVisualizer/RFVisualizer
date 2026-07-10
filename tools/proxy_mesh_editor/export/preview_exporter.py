"""후보별 색상 점구름과 네 꼭짓점 후보 메시를 PLY로 저장한다."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from ..models import PlaneCandidate
from ..geometry.plane_mesher import rectangle_triangles


class PreviewExportError(RuntimeError):
    """PLY 미리보기를 저장하지 못했을 때 발생한다."""


def _open3d():
    try:
        import open3d as o3d
    except ImportError as exc:
        raise PreviewExportError("PLY 미리보기 저장에는 Open3D가 필요합니다.") from exc
    return o3d


def _write_empty_point_cloud(path: Path) -> None:
    path.write_text(
        "ply\n"
        "format ascii 1.0\n"
        "comment RFVisualizer empty point preview\n"
        "element vertex 0\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "end_header\n",
        encoding="ascii",
    )


def _write_point_cloud(path: Path, point_cloud: Any, error_label: str) -> None:
    o3d = _open3d()
    if len(point_cloud.points) == 0:
        _write_empty_point_cloud(path)
        return
    if not o3d.io.write_point_cloud(
        str(path), point_cloud, write_ascii=False, compressed=False
    ):
        raise PreviewExportError("{} PLY를 저장하지 못했습니다: {}".format(error_label, path))


def _validate_residual_color(preview_settings: Dict[str, Any]) -> np.ndarray:
    residual_color = np.asarray(preview_settings["residual_color"], dtype=float)
    if residual_color.shape != (3,) or np.any(residual_color < 0.0) or np.any(
        residual_color > 1.0
    ):
        raise PreviewExportError("preview.residual_color는 0~1 사이 숫자 3개여야 합니다.")
    return residual_color


def _write_candidate_meshes(
    candidates: List[PlaneCandidate],
    output: Path,
    directory_name: str,
    file_prefix: str,
) -> Dict[str, str]:
    o3d = _open3d()
    mesh_directory = output / directory_name
    mesh_directory.mkdir(parents=True, exist_ok=True)
    for stale_path in mesh_directory.glob("{}_[0-9][0-9][0-9].ply".format(file_prefix)):
        stale_path.unlink()
    triangles = rectangle_triangles()
    candidate_files: Dict[str, str] = {}
    for candidate in candidates:
        mesh = o3d.geometry.TriangleMesh(
            vertices=o3d.utility.Vector3dVector(candidate.rectangle.corners),
            triangles=o3d.utility.Vector3iVector(triangles),
        )
        mesh.paint_uniform_color(candidate.color.tolist())
        mesh.compute_vertex_normals()
        path = mesh_directory / "{}.ply".format(candidate.candidate_id)
        if not o3d.io.write_triangle_mesh(
            str(path),
            mesh,
            write_ascii=False,
            compressed=False,
            write_vertex_normals=True,
            write_vertex_colors=True,
        ):
            raise PreviewExportError("후보 메시 PLY를 저장하지 못했습니다: {}".format(path))
        candidate_files[candidate.candidate_id] = str(path.resolve())
    return candidate_files


def write_preview(
    point_cloud: Any,
    candidates: List[PlaneCandidate],
    output_directory: Path,
    preview_settings: Dict[str, Any],
) -> Dict[str, Any]:
    o3d = _open3d()
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    point_count = len(point_cloud.points)
    residual_color = _validate_residual_color(preview_settings)

    preview = o3d.geometry.PointCloud()
    preview.points = o3d.utility.Vector3dVector(np.asarray(point_cloud.points))
    if point_cloud.has_normals():
        preview.normals = o3d.utility.Vector3dVector(np.asarray(point_cloud.normals))
    colors = np.tile(residual_color[None, :], (point_count, 1))
    for candidate in candidates:
        if candidate.inlier_indices is None:
            continue
        colors[np.asarray(candidate.inlier_indices, dtype=int)] = candidate.color
    preview.colors = o3d.utility.Vector3dVector(colors)

    preview_path = output / "plane_candidates_colored.ply"
    _write_point_cloud(preview_path, preview, "색상 미리보기")

    candidate_files: Dict[str, str] = {}
    if preview_settings["write_candidate_meshes"]:
        candidate_files = _write_candidate_meshes(
            candidates, output, "candidate_meshes", "plane"
        )

    return {
        "colored_point_cloud": str(preview_path.resolve()),
        "candidate_meshes": candidate_files,
        "residual_color": residual_color.tolist(),
    }


def write_wall_preview(
    point_cloud: Any,
    candidates: List[PlaneCandidate],
    assigned_mask: np.ndarray,
    output_directory: Path,
    preview_settings: Dict[str, Any],
) -> Dict[str, Any]:
    """벽 후보 색상 점구름, 잔여점, 후보 사각형 PLY를 저장한다."""

    o3d = _open3d()
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    point_count = len(point_cloud.points)
    assigned = np.asarray(assigned_mask, dtype=bool)
    if assigned.shape != (point_count,):
        raise PreviewExportError("벽 후보 배정 마스크 크기가 점 수와 다릅니다.")
    residual_color = _validate_residual_color(preview_settings)

    preview = o3d.geometry.PointCloud()
    preview.points = o3d.utility.Vector3dVector(np.asarray(point_cloud.points))
    if point_cloud.has_normals():
        preview.normals = o3d.utility.Vector3dVector(np.asarray(point_cloud.normals))
    colors = np.tile(residual_color[None, :], (point_count, 1))
    for candidate in candidates:
        if candidate.inlier_indices is not None:
            colors[np.asarray(candidate.inlier_indices, dtype=int)] = candidate.color
    preview.colors = o3d.utility.Vector3dVector(colors)
    colored_path = output / "wall_candidates_colored.ply"
    _write_point_cloud(colored_path, preview, "벽 후보 색상 미리보기")

    residual_indices = np.flatnonzero(~assigned)
    residual = point_cloud.select_by_index(residual_indices.tolist())
    if len(residual.points):
        residual.paint_uniform_color(residual_color.tolist())
    residual_path = output / "wall_residual_points.ply"
    _write_point_cloud(residual_path, residual, "벽 잔여점")

    candidate_files: Dict[str, str] = {}
    if preview_settings["write_candidate_meshes"]:
        candidate_files = _write_candidate_meshes(
            candidates, output, "wall_candidate_meshes", "wall"
        )

    return {
        "colored_point_cloud": str(colored_path.resolve()),
        "residual_point_cloud": str(residual_path.resolve()),
        "candidate_meshes": candidate_files,
        "residual_color": residual_color.tolist(),
    }
