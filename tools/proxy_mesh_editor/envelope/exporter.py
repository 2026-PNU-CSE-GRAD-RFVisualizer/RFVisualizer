"""Room Envelope를 공유 꼭짓점 OBJ, 개별 OBJ, PLY로 저장한다."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from ..export.obj_exporter import MATERIAL_COLORS
from .builder import EnvelopeMesh


class EnvelopeExportError(RuntimeError):
    """Room Envelope 파일을 저장할 수 없을 때 발생한다."""


def _format_vector(prefix: str, values: np.ndarray) -> str:
    return "{} {}\n".format(
        prefix, " ".join("{:.12g}".format(float(value)) for value in values)
    )


def _atomic_write(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        raise EnvelopeExportError("파일을 저장할 수 없습니다: {}".format(exc)) from exc


def _face_normal(vertices: np.ndarray, face: np.ndarray) -> np.ndarray:
    points = vertices[np.asarray(face, dtype=int)]
    normal = np.cross(points[1] - points[0], points[2] - points[0])
    length = float(np.linalg.norm(normal))
    if length <= 1e-20:
        raise EnvelopeExportError("퇴화한 삼각형의 법선을 계산할 수 없습니다.")
    return normal / length


def _material_text() -> str:
    blocks = ["# RFVisualizer Room Envelope materials\n"]
    for semantic in ("floor", "ceiling", "wall"):
        color = MATERIAL_COLORS[semantic]
        blocks.extend(
            [
                "\nnewmtl {}\n".format(semantic),
                "Ka 0 0 0\n",
                "Kd {:.6f} {:.6f} {:.6f}\n".format(*color),
                "Ks 0 0 0\n",
                "d 1.0\n",
                "illum 1\n",
            ]
        )
    return "".join(blocks)


def _object_order(mesh: EnvelopeMesh) -> List[str]:
    result = []
    for name in mesh.face_objects:
        if name not in result:
            result.append(name)
    return result


def _combined_obj_text(mesh: EnvelopeMesh) -> str:
    lines = ["# RFVisualizer closed room envelope\n", "mtllib room_envelope.mtl\n\n"]
    for vertex in mesh.vertices:
        lines.append(_format_vector("v", vertex))
    lines.append("\n")
    normal_index = 0
    for object_name in _object_order(mesh):
        face_indices = [
            index for index, value in enumerate(mesh.face_objects) if value == object_name
        ]
        semantic = mesh.face_semantics[face_indices[0]]
        lines.extend(
            [
                "o {}\n".format(object_name),
                "g {}\n".format(semantic),
                "usemtl {}\n".format(semantic),
            ]
        )
        for face_index in face_indices:
            face = mesh.faces[face_index]
            normal_index += 1
            lines.append(_format_vector("vn", _face_normal(mesh.vertices, face)))
            indices = [int(value) + 1 for value in face]
            lines.append(
                "f {}//{} {}//{} {}//{}\n".format(
                    indices[0],
                    normal_index,
                    indices[1],
                    normal_index,
                    indices[2],
                    normal_index,
                )
            )
        lines.append("\n")
    return "".join(lines)


def _individual_obj_text(mesh: EnvelopeMesh, object_name: str) -> str:
    face_indices = [
        index for index, value in enumerate(mesh.face_objects) if value == object_name
    ]
    semantic = mesh.face_semantics[face_indices[0]]
    global_vertices = []
    for face_index in face_indices:
        for value in mesh.faces[face_index]:
            if int(value) not in global_vertices:
                global_vertices.append(int(value))
    local_index = {value: index + 1 for index, value in enumerate(global_vertices)}
    lines = [
        "# RFVisualizer room envelope object\n",
        "mtllib ../room_envelope.mtl\n\n",
    ]
    for value in global_vertices:
        lines.append(_format_vector("v", mesh.vertices[value]))
    lines.extend(
        [
            "\no {}\n".format(object_name),
            "g {}\n".format(semantic),
            "usemtl {}\n".format(semantic),
        ]
    )
    for normal_index, face_index in enumerate(face_indices, start=1):
        face = mesh.faces[face_index]
        lines.append(_format_vector("vn", _face_normal(mesh.vertices, face)))
        indices = [local_index[int(value)] for value in face]
        lines.append(
            "f {}//{} {}//{} {}//{}\n".format(
                indices[0],
                normal_index,
                indices[1],
                normal_index,
                indices[2],
                normal_index,
            )
        )
    return "".join(lines)


def _write_ply(mesh: EnvelopeMesh, path: Path) -> None:
    try:
        import open3d as o3d
    except ImportError as exc:
        raise EnvelopeExportError("Envelope PLY 저장에는 Open3D가 필요합니다.") from exc
    triangle_mesh = o3d.geometry.TriangleMesh(
        vertices=o3d.utility.Vector3dVector(mesh.vertices),
        triangles=o3d.utility.Vector3iVector(mesh.faces.astype(np.int32)),
    )
    triangle_mesh.compute_vertex_normals()
    triangle_mesh.paint_uniform_color([0.82, 0.80, 0.74])
    if not o3d.io.write_triangle_mesh(
        str(path),
        triangle_mesh,
        write_ascii=False,
        compressed=False,
        write_vertex_normals=True,
        write_vertex_colors=True,
    ):
        raise EnvelopeExportError("Room Envelope PLY를 저장하지 못했습니다: {}".format(path))


def export_envelope_geometry(
    mesh: EnvelopeMesh,
    output_directory: Path,
    output_settings: Dict[str, Any],
) -> Dict[str, Any]:
    output = Path(output_directory).expanduser().resolve()
    object_directory = output / "objects"
    output.mkdir(parents=True, exist_ok=True)
    object_directory.mkdir(parents=True, exist_ok=True)
    for stale in object_directory.glob("*.obj"):
        stale.unlink()

    obj_path = output / "room_envelope.obj"
    mtl_path = output / "room_envelope.mtl"
    _atomic_write(mtl_path, _material_text())
    _atomic_write(obj_path, _combined_obj_text(mesh))

    object_paths: Dict[str, str] = {}
    if output_settings["write_individual_objects"]:
        for object_name in _object_order(mesh):
            path = object_directory / "{}.obj".format(object_name)
            _atomic_write(path, _individual_obj_text(mesh, object_name))
            object_paths[object_name] = str(path.resolve())

    ply_path = output / "room_envelope.ply"
    if output_settings["write_preview_ply"]:
        _write_ply(mesh, ply_path)
        ply_value = str(ply_path.resolve())
    else:
        ply_value = None
    return {
        "combined_obj": str(obj_path.resolve()),
        "material_library": str(mtl_path.resolve()),
        "preview_ply": ply_value,
        "object_directory": str(object_directory.resolve()),
        "individual_objects": object_paths,
    }
