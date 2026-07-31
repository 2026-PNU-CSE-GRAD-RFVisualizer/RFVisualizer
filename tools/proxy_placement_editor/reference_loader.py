"""Display-only point-cloud/mesh loading, caching, and coordinate conversion."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import numpy as np

from .coordinate_bridge import PlacementCoordinateBridge


class ReferenceGeometryError(ValueError):
    pass


LOGGER = logging.getLogger("proxy_placement_editor.reference")
DEFAULT_PGSR_MESH_PREVIEW_TRIANGLES = 1_000_000


@dataclass
class ReferenceGeometry:
    path: Path
    kind: str
    vertices_metric: np.ndarray
    faces: np.ndarray
    colors: Optional[np.ndarray]
    source_coordinate_space: str
    display_decimated: bool
    preview_path: Optional[Path] = None
    discarded_nonfinite_points: int = 0


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
    finite = np.all(np.isfinite(vertices), axis=1)
    discarded = int(np.count_nonzero(~finite))
    if discarded:
        LOGGER.warning(
            "Point Cloud의 유한하지 않은 좌표 %d개를 표시 계층에서 제외합니다: %s",
            discarded,
            source,
        )
        vertices = vertices[finite]
        colors = colors[finite] if colors is not None else None
    if not len(vertices):
        raise ReferenceGeometryError("PLY에 유한한 point cloud 좌표가 없습니다.")
    sampled = len(vertices) > maximum_points
    if sampled:
        indices = np.linspace(0, len(vertices) - 1, maximum_points, dtype=int)
        vertices = vertices[indices]
        colors = colors[indices] if colors is not None else None
    else:
        vertices = vertices.copy()
        colors = colors.copy() if colors is not None else None
    return vertices, colors, sampled, discarded


def _validate_source(path: Path, label: str) -> Path:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ReferenceGeometryError("{}를 찾을 수 없습니다: {}".format(label, source))
    if source.suffix.lower() not in {".obj", ".ply"}:
        raise ReferenceGeometryError("{}는 OBJ 또는 PLY만 지원합니다.".format(label))
    return source


def _validate_coordinate_space(coordinate_space: str) -> None:
    if coordinate_space not in {"metric", "scene"}:
        raise ReferenceGeometryError("좌표 공간은 metric 또는 scene이어야 합니다.")


def _open3d():
    try:
        import open3d as o3d
    except ImportError as exc:
        raise ReferenceGeometryError(
            "표시용 형상을 읽으려면 Open3D가 필요합니다."
        ) from exc
    return o3d


def load_point_cloud_geometry(
    path: Path,
    coordinate_space: str,
    bridge: PlacementCoordinateBridge,
    maximum_points: int = 500000,
) -> ReferenceGeometry:
    """Load PGSR Gaussian positions as a bounded point-cloud display layer."""

    source = _validate_source(path, "Point Cloud")
    if source.suffix.lower() != ".ply":
        raise ReferenceGeometryError("Point Cloud는 PLY만 지원합니다.")
    _validate_coordinate_space(coordinate_space)
    vertices, colors, sampled, discarded = _point_cloud_arrays(
        _open3d(), source, maximum_points
    )
    if coordinate_space == "scene":
        vertices = bridge.scene_vertices_to_metric(vertices)
    return ReferenceGeometry(
        source,
        "point_cloud",
        vertices,
        np.empty((0, 3), dtype=int),
        colors,
        coordinate_space,
        sampled or discarded > 0,
        discarded_nonfinite_points=discarded,
    )


def mesh_preview_metadata_path(preview_path: Path) -> Path:
    preview = Path(preview_path).expanduser().resolve()
    return preview.with_suffix(preview.suffix + ".json")


def _mesh_preview_signature(source: Path, maximum_triangles: int) -> Dict[str, object]:
    stat = source.stat()
    return {
        "schema_version": "1.0",
        "source_path": str(source),
        "source_size_bytes": int(stat.st_size),
        "source_mtime_ns": int(stat.st_mtime_ns),
        "maximum_triangles": int(maximum_triangles),
    }


def mesh_preview_cache_is_current(
    source_path: Path,
    preview_path: Path,
    maximum_triangles: int = DEFAULT_PGSR_MESH_PREVIEW_TRIANGLES,
) -> bool:
    source = Path(source_path).expanduser().resolve()
    preview = Path(preview_path).expanduser().resolve()
    metadata_path = mesh_preview_metadata_path(preview)
    if not source.is_file() or not preview.is_file() or not metadata_path.is_file():
        return False
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    expected = _mesh_preview_signature(source, maximum_triangles)
    return all(metadata.get(key) == value for key, value in expected.items())


def build_mesh_preview_cache(
    source_path: Path,
    preview_path: Path,
    maximum_triangles: int = DEFAULT_PGSR_MESH_PREVIEW_TRIANGLES,
) -> Dict[str, object]:
    """Build a persistent bounded triangle mesh without changing the PGSR source."""

    source = _validate_source(source_path, "PGSR Output Mesh")
    preview = Path(preview_path).expanduser().resolve()
    if preview.suffix.lower() != ".ply":
        raise ReferenceGeometryError("표시용 PGSR Mesh 캐시는 PLY여야 합니다.")
    if source == preview:
        raise ReferenceGeometryError("PGSR 원본 Mesh와 표시용 캐시 경로는 달라야 합니다.")
    limit = int(maximum_triangles)
    if limit <= 0:
        raise ReferenceGeometryError("표시용 Mesh triangle 제한은 양수여야 합니다.")
    if mesh_preview_cache_is_current(source, preview, limit):
        metadata = json.loads(
            mesh_preview_metadata_path(preview).read_text(encoding="utf-8")
        )
        metadata["cache_reused"] = True
        return metadata

    o3d = _open3d()
    LOGGER.info("PGSR 원본 Mesh를 읽는 중입니다: %s", source)
    mesh = o3d.io.read_triangle_mesh(str(source), enable_post_processing=False)
    if not len(mesh.vertices) or not len(mesh.triangles):
        raise ReferenceGeometryError("PGSR Output Mesh에 triangle mesh가 없습니다.")
    source_vertices = len(mesh.vertices)
    source_triangles = len(mesh.triangles)
    if source_triangles > limit:
        LOGGER.info(
            "표시용 PGSR Mesh를 단순화합니다: triangles=%d -> <=%d",
            source_triangles,
            limit,
        )
        mesh = mesh.simplify_quadric_decimation(limit)
    if not len(mesh.vertices) or not len(mesh.triangles):
        raise ReferenceGeometryError("표시용 PGSR Mesh 단순화 결과가 비어 있습니다.")

    preview.parent.mkdir(parents=True, exist_ok=True)
    temporary = preview.with_name(
        "{}.tmp-{}{}".format(preview.stem, os.getpid(), preview.suffix)
    )
    try:
        if not o3d.io.write_triangle_mesh(
            str(temporary), mesh, write_ascii=False, compressed=False
        ):
            raise ReferenceGeometryError("표시용 PGSR Mesh 캐시를 저장하지 못했습니다.")
        os.replace(str(temporary), str(preview))
    finally:
        if temporary.exists():
            temporary.unlink()

    metadata = _mesh_preview_signature(source, limit)
    metadata.update(
        {
            "preview_path": str(preview),
            "source_vertices": int(source_vertices),
            "source_triangles": int(source_triangles),
            "preview_vertices": int(len(mesh.vertices)),
            "preview_triangles": int(len(mesh.triangles)),
            "cache_reused": False,
        }
    )
    metadata_path = mesh_preview_metadata_path(preview)
    temporary_metadata = metadata_path.with_name(
        "{}.tmp-{}".format(metadata_path.name, os.getpid())
    )
    try:
        temporary_metadata.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(str(temporary_metadata), str(metadata_path))
    finally:
        if temporary_metadata.exists():
            temporary_metadata.unlink()
    return metadata


def load_pgsr_output_mesh_geometry(
    source_path: Path,
    coordinate_space: str,
    bridge: PlacementCoordinateBridge,
    preview_path: Optional[Path] = None,
    maximum_triangles: int = DEFAULT_PGSR_MESH_PREVIEW_TRIANGLES,
    full_resolution: bool = False,
) -> ReferenceGeometry:
    """Load the PGSR triangle layer from the source or a bounded display cache."""

    source = _validate_source(source_path, "PGSR Output Mesh")
    _validate_coordinate_space(coordinate_space)
    counts = _ply_element_counts(source) if source.suffix.lower() == ".ply" else {}
    oversized = not full_resolution and counts.get("face", 0) > int(maximum_triangles)
    display_path = source
    decimated = False
    current_preview = (
        not full_resolution
        and preview_path is not None
        and mesh_preview_cache_is_current(source, preview_path, maximum_triangles)
    )
    if current_preview:
        display_path = Path(preview_path).expanduser().resolve()
        decimated = True
    elif oversized:
        if preview_path is None:
            raise ReferenceGeometryError(
                "대형 PGSR Output Mesh의 표시용 캐시가 없습니다. "
                "edit 명령으로 캐시를 먼저 준비하세요."
            )
        raise ReferenceGeometryError(
            "PGSR Output Mesh 표시용 캐시가 원본과 일치하지 않습니다. "
            "edit 명령으로 캐시를 다시 준비하세요."
        )

    o3d = _open3d()
    mesh = o3d.io.read_triangle_mesh(
        str(display_path), enable_post_processing=False
    )
    if not len(mesh.vertices) or not len(mesh.triangles):
        raise ReferenceGeometryError("PGSR Output Mesh에 triangle mesh가 없습니다.")
    if not full_resolution and len(mesh.triangles) > int(maximum_triangles):
        mesh = mesh.simplify_quadric_decimation(int(maximum_triangles))
        decimated = True
    vertices = np.asarray(mesh.vertices, dtype=float).copy()
    faces = np.asarray(mesh.triangles, dtype=int).copy()
    colors = (
        np.asarray(mesh.vertex_colors, dtype=float).copy()
        if mesh.has_vertex_colors()
        else None
    )
    if coordinate_space == "scene":
        vertices = bridge.scene_vertices_to_metric(vertices)
    return ReferenceGeometry(
        source,
        "mesh",
        vertices,
        faces,
        colors,
        coordinate_space,
        decimated,
        preview_path=display_path if display_path != source else None,
    )


def load_reference_geometry(
    path: Path,
    coordinate_space: str,
    bridge: PlacementCoordinateBridge,
    maximum_triangles: int = 250000,
    maximum_points: int = 500000,
) -> ReferenceGeometry:
    source = _validate_source(path, "Reference geometry")
    _validate_coordinate_space(coordinate_space)
    o3d = _open3d()

    ply_counts = _ply_element_counts(source) if source.suffix.lower() == ".ply" else {}
    oversized_ply_mesh = ply_counts.get("face", 0) > maximum_triangles
    if oversized_ply_mesh:
        LOGGER.info(
            "대형 reference PLY(vertex=%s, face=%s)는 GUI 안정성을 위해 최대 %s개 점으로 읽습니다.",
            ply_counts.get("vertex", "unknown"),
            ply_counts.get("face", "unknown"),
            maximum_points,
        )
        vertices, colors, _sampled, discarded = _point_cloud_arrays(
            o3d, source, maximum_points
        )
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
            vertices, colors, decimated, discarded = _point_cloud_arrays(
                o3d, source, maximum_points
            )
            faces = np.empty((0, 3), dtype=int)
            kind = "point_cloud"
        else:
            raise ReferenceGeometryError("OBJ에 triangle mesh가 없습니다.")
    if coordinate_space == "scene":
        vertices = bridge.scene_vertices_to_metric(vertices)
    return ReferenceGeometry(
        source,
        kind,
        vertices,
        faces,
        colors,
        coordinate_space,
        decimated,
        discarded_nonfinite_points=discarded if kind == "point_cloud" else 0,
    )
