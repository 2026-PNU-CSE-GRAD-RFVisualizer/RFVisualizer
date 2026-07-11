"""실제 크기 Room Envelope와 표준 좌표축 미리보기를 저장한다."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

from .metric_transform import MetricTransform, transform_normals
from .preview_exporter import ObjGeometry, write_rotation_only_ply


class MetricExportError(RuntimeError):
    """실제 크기 OBJ/MTL/PLY를 저장할 수 없을 때 발생한다."""


def _atomic_write(path: Path, text: str) -> None:
    output = Path(path)
    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(output)
    except OSError as exc:
        raise MetricExportError("실제 크기 결과를 저장할 수 없습니다: {}".format(exc)) from exc


def _format_vector(prefix: str, values: np.ndarray) -> str:
    return "{} {}\n".format(
        prefix, " ".join("{:.12g}".format(float(value)) for value in values)
    )


def _source_material_path(source_obj: Path, lines: List[str]) -> Path:
    libraries = [line.strip().split(maxsplit=1)[1] for line in lines if line.strip().startswith("mtllib ")]
    if len(libraries) != 1:
        raise MetricExportError("입력 OBJ에는 정확히 하나의 mtllib 선언이 필요합니다.")
    material = (Path(source_obj).resolve().parent / libraries[0]).resolve()
    if not material.is_file():
        raise MetricExportError("입력 OBJ의 MTL 파일을 찾을 수 없습니다: {}".format(material))
    return material


def _structural_directives(lines: List[str]) -> List[str]:
    prefixes = ("o ", "g ", "usemtl ", "f ")
    return [line.strip() for line in lines if line.strip().startswith(prefixes)]


def write_metric_obj_and_mtl(
    source_obj: Path,
    geometry: ObjGeometry,
    metric_vertices: np.ndarray,
    transform: MetricTransform,
    output_directory: Path,
    status: str,
) -> Tuple[Path, Path, Dict[str, Any]]:
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    obj_path = output / "room_envelope_metric.obj"
    mtl_path = output / "room_envelope_metric.mtl"
    source_mtl = _source_material_path(source_obj, geometry.source_lines)
    try:
        material_text = source_mtl.read_text(encoding="utf-8")
    except OSError as exc:
        raise MetricExportError("입력 MTL을 읽을 수 없습니다: {}".format(exc)) from exc

    lines = [
        "# PROVISIONAL METRIC CALIBRATION\n"
        if status == "provisional"
        else "# MEASURED METRIC CALIBRATION\n",
        "# meters_per_scene_unit: {:.12g}\n".format(transform.scale),
        "# source: calibration references in metric calibration config\n",
    ]
    vertex_index = 0
    for line in geometry.source_lines:
        stripped = line.strip()
        if stripped.startswith("mtllib "):
            lines.append("mtllib room_envelope_metric.mtl\n")
        elif stripped.startswith("v "):
            lines.append(_format_vector("v", metric_vertices[vertex_index]))
            vertex_index += 1
        elif stripped.startswith("vn "):
            parts = stripped.split()
            try:
                source_normal = np.asarray([float(value) for value in parts[1:4]])
            except (ValueError, IndexError) as exc:
                raise MetricExportError("OBJ normal을 읽을 수 없습니다: {}".format(stripped)) from exc
            lines.append(_format_vector("vn", transform_normals(source_normal, transform)))
        else:
            lines.append(line if line.endswith("\n") else line + "\n")
    _atomic_write(obj_path, "".join(lines))
    _atomic_write(mtl_path, material_text)

    output_lines = obj_path.read_text(encoding="utf-8").splitlines(keepends=True)
    source_directives = _structural_directives(geometry.source_lines)
    output_directives = _structural_directives(output_lines)
    preservation = {
        "object_group_material_face_directives_unchanged": source_directives == output_directives,
        "face_indices_unchanged": [value for value in source_directives if value.startswith("f ")]
        == [value for value in output_directives if value.startswith("f ")],
        "source_material_library": str(source_mtl),
        "metric_material_library": str(mtl_path.resolve()),
        "material_library_copied": material_text == mtl_path.read_text(encoding="utf-8"),
    }
    preservation["obj_structure_preserved"] = bool(
        preservation["object_group_material_face_directives_unchanged"]
        and preservation["face_indices_unchanged"]
        and preservation["material_library_copied"]
    )
    return obj_path, mtl_path, preservation


def _sample_axis(direction: np.ndarray, length: float, color: np.ndarray, count: int = 100):
    values = np.linspace(0.0, length, count)
    points = values[:, None] * direction[None, :]
    colors = np.tile(color[None, :], (count, 1))
    return points, colors


def write_metric_axes_ply(
    path: Path,
    bottom_corners: np.ndarray,
    top_corners: np.ndarray,
    x_axis_edge: Tuple[int, int],
) -> Dict[str, Any]:
    try:
        import open3d as o3d
    except ImportError as exc:
        raise MetricExportError("좌표축 PLY 저장에는 Open3D가 필요합니다.") from exc
    bottom = np.asarray(bottom_corners, dtype=float)
    top = np.asarray(top_corners, dtype=float)
    combined = np.vstack([bottom, top])
    diagonal = float(np.linalg.norm(np.max(combined, axis=0) - np.min(combined, axis=0)))
    axis_length = max(0.2 * diagonal, 1.0)
    all_points = []
    all_colors = []
    for direction, color in (
        (np.asarray([1.0, 0.0, 0.0]), np.asarray([1.0, 0.0, 0.0])),
        (np.asarray([0.0, 1.0, 0.0]), np.asarray([0.0, 1.0, 0.0])),
        (np.asarray([0.0, 0.0, 1.0]), np.asarray([0.0, 0.0, 1.0])),
    ):
        points, colors = _sample_axis(direction, axis_length, color)
        all_points.append(points)
        all_colors.append(colors)
    start, end = x_axis_edge
    edge_points = np.linspace(bottom[start], bottom[end], 120)
    all_points.extend([bottom, top, edge_points, np.zeros((1, 3))])
    all_colors.extend(
        [
            np.tile([0.10, 0.10, 0.10], (len(bottom), 1)),
            np.tile([1.00, 0.25, 0.75], (len(top), 1)),
            np.tile([1.00, 0.55, 0.00], (len(edge_points), 1)),
            np.asarray([[1.0, 1.0, 1.0]]),
        ]
    )
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(np.vstack(all_points))
    cloud.colors = o3d.utility.Vector3dVector(np.vstack(all_colors))
    if not o3d.io.write_point_cloud(str(path), cloud, write_ascii=False, compressed=False):
        raise MetricExportError("표준 좌표축 PLY를 저장하지 못했습니다: {}".format(path))
    return {
        "axis_length_m": axis_length,
        "point_count": int(len(cloud.points)),
        "highlighted_x_axis_edge": [start, end],
        "colors": {
            "x": [1.0, 0.0, 0.0],
            "y": [0.0, 1.0, 0.0],
            "z": [0.0, 0.0, 1.0],
            "bottom": [0.10, 0.10, 0.10],
            "top": [1.00, 0.25, 0.75],
            "selected_edge": [1.00, 0.55, 0.00],
        },
    }


def export_metric_geometry(
    source_obj: Path,
    geometry: ObjGeometry,
    metric_vertices: np.ndarray,
    metric_bottom: np.ndarray,
    metric_top: np.ndarray,
    transform: MetricTransform,
    output_directory: Path,
    settings: Dict[str, Any],
    status: str,
) -> Dict[str, Any]:
    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    files: Dict[str, Any] = {}
    preservation: Dict[str, Any] = {
        "obj_structure_preserved": None,
        "face_indices_unchanged": True,
    }
    if settings["write_obj"]:
        obj_path, mtl_path, preservation = write_metric_obj_and_mtl(
            source_obj, geometry, metric_vertices, transform, output, status
        )
        files["metric_obj"] = str(obj_path.resolve())
        files["metric_mtl"] = str(mtl_path.resolve())
    else:
        files["metric_obj"] = None
        files["metric_mtl"] = None
    ply_path = output / "room_envelope_metric.ply"
    if settings["write_ply"]:
        write_rotation_only_ply(metric_vertices, geometry.faces, ply_path)
        files["metric_ply"] = str(ply_path.resolve())
    else:
        files["metric_ply"] = None
    axes_path = output / "metric_coordinate_axes.ply"
    if settings["write_axis_preview"]:
        axis_preview = write_metric_axes_ply(
            axes_path, metric_bottom, metric_top, transform.x_axis_edge
        )
        files["metric_coordinate_axes_ply"] = str(axes_path.resolve())
    else:
        axis_preview = None
        files["metric_coordinate_axes_ply"] = None
    return {"files": files, "obj_preservation": preservation, "axis_preview": axis_preview}
