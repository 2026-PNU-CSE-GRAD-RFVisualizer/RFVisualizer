"""Display-only OBJ/PLY reference geometry loading and coordinate conversion."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import numpy as np

from .coordinate_bridge import PlacementCoordinateBridge


class ReferenceGeometryError(ValueError):
    pass


LOGGER = logging.getLogger("proxy_placement_editor.reference")


@dataclass
class ReferenceGeometry:
    path: Path
    kind: str
    vertices_metric: np.ndarray
    faces: np.ndarray
    colors: Optional[np.ndarray]
    source_coordinate_space: str
    display_decimated: bool


def _ply_element_counts(path: Path) -> Dict[str, int]:
    """Read only the PLY header so very large triangle data is not allocated."""
    counts: Dict[str, int] = {}
    try:
        with path.open("rb") as stream:
            if stream.readline().strip() != b"ply":
                return counts
            for _ in range(10000):
                raw = stream.readline()
                if not raw:
                    break
                line = raw.decode("ascii", errors="replace").strip()
                if line == "end_header":
                    break
                fields = line.split()
                if len(fields) == 3 and fields[0] == "element":
                    counts[fields[1]] = int(fields[2])
    except (OSError, ValueError):
        return {}
    return counts


def _point_cloud_arrays(o3d, source: Path, maximum_points: int):
    cloud = o3d.io.read_point_cloud(str(source))
    if not len(cloud.points):
        raise ReferenceGeometryError("PLY에 point cloud가 없습니다.")
    vertices = np.asarray(cloud.points, dtype=float)
    colors = np.asarray(cloud.colors, dtype=float) if cloud.has_colors() else None
    sampled = len(vertices) > maximum_points
    if sampled:
        indices = np.linspace(0, len(vertices) - 1, maximum_points, dtype=int)
        vertices = vertices[indices]
        colors = colors[indices] if colors is not None else None
    else:
        vertices = vertices.copy()
        colors = colors.copy() if colors is not None else None
    return vertices, colors, sampled


def load_reference_geometry(
    path: Path,
    coordinate_space: str,
    bridge: PlacementCoordinateBridge,
    maximum_triangles: int = 250000,
    maximum_points: int = 500000,
) -> ReferenceGeometry:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ReferenceGeometryError(
            "Reference geometry를 찾을 수 없습니다: {}".format(source)
        )
    if source.suffix.lower() not in {".obj", ".ply"}:
        raise ReferenceGeometryError("Reference geometry는 OBJ 또는 PLY만 지원합니다.")
    if coordinate_space not in {"metric", "scene"}:
        raise ReferenceGeometryError(
            "reference-coordinate-space는 metric 또는 scene이어야 합니다."
        )
    try:
        import open3d as o3d
    except ImportError as exc:
        raise ReferenceGeometryError(
            "Reference geometry를 읽으려면 Open3D가 필요합니다."
        ) from exc

    ply_counts = _ply_element_counts(source) if source.suffix.lower() == ".ply" else {}
    oversized_ply_mesh = ply_counts.get("face", 0) > maximum_triangles
    if oversized_ply_mesh:
        LOGGER.info(
            "대형 reference PLY(vertex=%s, face=%s)는 GUI 안정성을 위해 최대 %s개 점으로 읽습니다.",
            ply_counts.get("vertex", "unknown"),
            ply_counts.get("face", "unknown"),
            maximum_points,
        )
        vertices, colors, _sampled = _point_cloud_arrays(o3d, source, maximum_points)
        faces = np.empty((0, 3), dtype=int)
        kind = "point_cloud"
        decimated = True
    else:
        mesh = o3d.io.read_triangle_mesh(str(source), enable_post_processing=False)
        decimated = False
        if len(mesh.vertices) and len(mesh.triangles):
            if len(mesh.triangles) > maximum_triangles:
                mesh = mesh.simplify_quadric_decimation(maximum_triangles)
                decimated = True
            vertices = np.asarray(mesh.vertices, dtype=float).copy()
            faces = np.asarray(mesh.triangles, dtype=int).copy()
            colors = (
                np.asarray(mesh.vertex_colors, dtype=float).copy()
                if mesh.has_vertex_colors()
                else None
            )
            kind = "mesh"
        elif source.suffix.lower() == ".ply":
            vertices, colors, decimated = _point_cloud_arrays(
                o3d, source, maximum_points
            )
            faces = np.empty((0, 3), dtype=int)
            kind = "point_cloud"
        else:
            raise ReferenceGeometryError("OBJ에 triangle mesh가 없습니다.")
    if coordinate_space == "scene":
        vertices = bridge.scene_vertices_to_metric(vertices)
    return ReferenceGeometry(
        source, kind, vertices, faces, colors, coordinate_space, decimated
    )
