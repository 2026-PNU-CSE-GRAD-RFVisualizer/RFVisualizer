"""회전만 적용한 OBJ/PLY와 좌표축 진단 PLY를 생성한다."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np


class CalibrationPreviewError(RuntimeError):
    """원본 OBJ를 읽거나 진단 미리보기를 저장할 수 없을 때 발생한다."""


@dataclass
class ObjGeometry:
    vertices: np.ndarray
    faces: np.ndarray
    normal_count: int
    source_lines: List[str]


def _parse_face_vertex(token: str, vertex_count: int) -> int:
    raw = token.split("/", 1)[0]
    try:
        value = int(raw)
    except ValueError as exc:
        raise CalibrationPreviewError("OBJ face vertex index를 읽을 수 없습니다: {}".format(token)) from exc
    if value == 0:
        raise CalibrationPreviewError("OBJ vertex index 0은 유효하지 않습니다.")
    return value - 1 if value > 0 else vertex_count + value


def load_obj_geometry(path: Path) -> ObjGeometry:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise CalibrationPreviewError("Envelope OBJ를 찾을 수 없습니다: {}".format(source))
    try:
        lines = source.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as exc:
        raise CalibrationPreviewError("Envelope OBJ를 읽을 수 없습니다: {}".format(exc)) from exc
    vertices = []
    faces = []
    normal_count = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("v "):
            parts = stripped.split()
            if len(parts) < 4:
                raise CalibrationPreviewError("OBJ vertex는 좌표 3개가 필요합니다.")
            vertices.append([float(parts[1]), float(parts[2]), float(parts[3])])
        elif stripped.startswith("vn "):
            normal_count += 1
        elif stripped.startswith("f "):
            tokens = stripped.split()[1:]
            if len(tokens) < 3:
                raise CalibrationPreviewError("OBJ face는 vertex가 3개 이상 필요합니다.")
            indices = [_parse_face_vertex(token, len(vertices)) for token in tokens]
            for index in range(1, len(indices) - 1):
                faces.append([indices[0], indices[index], indices[index + 1]])
    vertex_array = np.asarray(vertices, dtype=float)
    face_array = np.asarray(faces, dtype=int)
    if (
        vertex_array.ndim != 2
        or vertex_array.shape[1] != 3
        or face_array.ndim != 2
        or face_array.shape[1] != 3
        or not np.all(np.isfinite(vertex_array))
    ):
        raise CalibrationPreviewError("OBJ에서 유효한 삼각형 geometry를 읽지 못했습니다.")
    if np.any(face_array < 0) or np.any(face_array >= len(vertex_array)):
        raise CalibrationPreviewError("OBJ face index가 vertex 범위를 벗어납니다.")
    return ObjGeometry(vertex_array, face_array, normal_count, lines)


def mesh_topology_signature(vertices: np.ndarray, faces: np.ndarray) -> Dict[str, Any]:
    points = np.asarray(vertices, dtype=float)
    triangles = np.asarray(faces, dtype=int)
    edges: Counter = Counter()
    for face in triangles:
        for start, end in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            edges[tuple(sorted((int(start), int(end))))] += 1
    signed_volume = float(
        np.sum(
            np.einsum(
                "ij,ij->i",
                points[triangles[:, 0]],
                np.cross(points[triangles[:, 1]], points[triangles[:, 2]]),
            )
        )
        / 6.0
    )
    return {
        "vertex_count": int(len(points)),
        "triangle_count": int(len(triangles)),
        "face_index_checksum": int(np.sum(triangles)),
        "boundary_edge_count": int(sum(value == 1 for value in edges.values())),
        "non_manifold_edge_count": int(sum(value > 2 for value in edges.values())),
        "signed_volume": signed_volume,
        "absolute_volume": abs(signed_volume),
    }


def _format_vector(prefix: str, values: np.ndarray) -> str:
    return "{} {}\n".format(
        prefix, " ".join("{:.12g}".format(float(value)) for value in values)
    )


def write_rotation_only_obj(
    geometry: ObjGeometry, rotation: np.ndarray, output_path: Path
) -> np.ndarray:
    rotation = np.asarray(rotation, dtype=float)
    transformed_vertices = geometry.vertices @ rotation.T
    output_lines = []
    vertex_index = 0
    for line in geometry.source_lines:
        stripped = line.strip()
        if stripped.startswith("v "):
            output_lines.append(_format_vector("v", transformed_vertices[vertex_index]))
            vertex_index += 1
        elif stripped.startswith("vn "):
            parts = stripped.split()
            normal = np.asarray([float(parts[1]), float(parts[2]), float(parts[3])])
            transformed = rotation @ normal
            length = float(np.linalg.norm(transformed))
            if length > 1e-12:
                transformed = transformed / length
            output_lines.append(_format_vector("vn", transformed))
        else:
            output_lines.append(line if line.endswith("\n") else line + "\n")
    output = Path(output_path)
    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        temporary.write_text("".join(output_lines), encoding="utf-8")
        temporary.replace(output)
    except OSError as exc:
        raise CalibrationPreviewError("회전 미리보기 OBJ를 저장하지 못했습니다: {}".format(exc)) from exc
    return transformed_vertices


def _open3d():
    try:
        import open3d as o3d
    except ImportError as exc:
        raise CalibrationPreviewError("PLY 미리보기 저장에는 Open3D가 필요합니다.") from exc
    return o3d


def write_rotation_only_ply(
    vertices: np.ndarray, faces: np.ndarray, output_path: Path
) -> None:
    o3d = _open3d()
    mesh = o3d.geometry.TriangleMesh(
        vertices=o3d.utility.Vector3dVector(np.asarray(vertices, dtype=float)),
        triangles=o3d.utility.Vector3iVector(np.asarray(faces, dtype=np.int32)),
    )
    mesh.compute_vertex_normals()
    mesh.paint_uniform_color([0.82, 0.80, 0.74])
    if not o3d.io.write_triangle_mesh(
        str(output_path),
        mesh,
        write_ascii=False,
        compressed=False,
        write_vertex_normals=True,
        write_vertex_colors=True,
    ):
        raise CalibrationPreviewError("회전 미리보기 PLY를 저장하지 못했습니다: {}".format(output_path))


def _sample_vector(
    origin: np.ndarray,
    direction: np.ndarray,
    length: float,
    color: np.ndarray,
    count: int = 80,
) -> Tuple[np.ndarray, np.ndarray]:
    values = np.linspace(0.0, length, count)
    points = origin[None, :] + values[:, None] * direction[None, :]
    colors = np.tile(color[None, :], (count, 1))
    return points, colors


def write_axis_gizmo_ply(
    output_path: Path,
    source_up: np.ndarray,
    target_up: np.ndarray,
    bottom_corners: np.ndarray,
    top_corners: np.ndarray,
) -> Dict[str, Any]:
    o3d = _open3d()
    bottom = np.asarray(bottom_corners, dtype=float)
    top = np.asarray(top_corners, dtype=float)
    combined = np.vstack([bottom, top])
    diagonal = float(np.linalg.norm(np.max(combined, axis=0) - np.min(combined, axis=0)))
    axis_length = max(0.2 * diagonal, 1.0)
    origin = np.zeros(3)
    vectors = [
        (np.asarray([1.0, 0.0, 0.0]), np.asarray([1.0, 0.0, 0.0]), "world_x"),
        (np.asarray([0.0, 1.0, 0.0]), np.asarray([0.0, 1.0, 0.0]), "world_y"),
        (np.asarray([0.0, 0.0, 1.0]), np.asarray([0.0, 0.0, 1.0]), "world_z"),
        (np.asarray(source_up, dtype=float), np.asarray([1.0, 1.0, 0.0]), "source_up"),
        (np.asarray(target_up, dtype=float), np.asarray([0.0, 1.0, 1.0]), "target_up"),
    ]
    all_points = []
    all_colors = []
    for direction, color, _ in vectors:
        direction = direction / np.linalg.norm(direction)
        points, colors = _sample_vector(origin, direction, axis_length, color)
        all_points.append(points)
        all_colors.append(colors)
    all_points.extend([bottom, top, origin[None, :]])
    all_colors.extend(
        [
            np.tile([0.10, 0.10, 0.10], (len(bottom), 1)),
            np.tile([1.00, 0.25, 0.75], (len(top), 1)),
            np.asarray([[1.0, 1.0, 1.0]]),
        ]
    )
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(np.vstack(all_points))
    cloud.colors = o3d.utility.Vector3dVector(np.vstack(all_colors))
    if not o3d.io.write_point_cloud(
        str(output_path), cloud, write_ascii=False, compressed=False
    ):
        raise CalibrationPreviewError("좌표축 PLY를 저장하지 못했습니다: {}".format(output_path))
    return {
        "axis_length": axis_length,
        "point_count": int(len(cloud.points)),
        "colors": {
            "world_x": [1.0, 0.0, 0.0],
            "world_y": [0.0, 1.0, 0.0],
            "world_z": [0.0, 0.0, 1.0],
            "source_up": [1.0, 1.0, 0.0],
            "target_up": [0.0, 1.0, 1.0],
            "bottom_corners": [0.10, 0.10, 0.10],
            "top_corners": [1.00, 0.25, 0.75],
        },
    }


def topology_preservation_report(
    original_vertices: np.ndarray,
    transformed_vertices: np.ndarray,
    faces: np.ndarray,
    tolerance: float,
) -> Dict[str, Any]:
    before = mesh_topology_signature(original_vertices, faces)
    after = mesh_topology_signature(transformed_vertices, faces)
    volume_difference = float(abs(after["absolute_volume"] - before["absolute_volume"]))
    signed_difference = float(abs(after["signed_volume"] - before["signed_volume"]))
    success = bool(
        before["vertex_count"] == after["vertex_count"]
        and before["triangle_count"] == after["triangle_count"]
        and before["face_index_checksum"] == after["face_index_checksum"]
        and before["boundary_edge_count"] == after["boundary_edge_count"]
        and before["non_manifold_edge_count"] == after["non_manifold_edge_count"]
        and volume_difference <= tolerance
        and signed_difference <= tolerance
    )
    return {
        "before_rotation": before,
        "after_rotation": after,
        "absolute_volume_difference": volume_difference,
        "signed_volume_difference": signed_difference,
        "face_indices_unchanged": True,
        "topology_preserved": success,
    }
