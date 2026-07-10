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
    residual_color = np.asarray(preview_settings["residual_color"], dtype=float)
    if residual_color.shape != (3,) or np.any(residual_color < 0.0) or np.any(
        residual_color > 1.0
    ):
        raise PreviewExportError("preview.residual_color는 0~1 사이 숫자 3개여야 합니다.")

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
    if not o3d.io.write_point_cloud(
        str(preview_path), preview, write_ascii=False, compressed=False
    ):
        raise PreviewExportError("색상 미리보기 PLY를 저장하지 못했습니다: {}".format(preview_path))

    candidate_files: Dict[str, str] = {}
    if preview_settings["write_candidate_meshes"]:
        mesh_directory = output / "candidate_meshes"
        mesh_directory.mkdir(parents=True, exist_ok=True)
        for stale_path in mesh_directory.glob("plane_[0-9][0-9][0-9].ply"):
            stale_path.unlink()
        triangles = rectangle_triangles()
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

    return {
        "colored_point_cloud": str(preview_path.resolve()),
        "candidate_meshes": candidate_files,
        "residual_color": residual_color.tolist(),
    }
