"""Metric OBJ 객체를 Sionna/Mitsuba용 PLY와 scene.xml로 변환한다."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

from .io_utils import atomic_write_text, write_json
from .metric_scene_loader import MetricScene, mesh_statistics


class SceneExportError(RuntimeError):
    """Sionna/Mitsuba 장면 파일을 만들 수 없을 때 발생한다."""


def _local_mesh(vertices: np.ndarray, faces: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    used = []
    for face in faces:
        for value in face:
            if int(value) not in used:
                used.append(int(value))
    mapping = {value: index for index, value in enumerate(used)}
    local_faces = np.asarray([[mapping[int(value)] for value in face] for face in faces], dtype=int)
    return vertices[np.asarray(used, dtype=int)], local_faces


def write_ascii_ply(
    path: Path,
    vertices: np.ndarray,
    faces: np.ndarray,
    comment: str = "RFVisualizer Phase 2-A metric mesh",
) -> None:
    safe_comment = str(comment).replace("\n", " ").replace("\r", " ")
    lines = [
        "ply\n",
        "format ascii 1.0\n",
        "comment {}\n".format(safe_comment),
        "element vertex {}\n".format(len(vertices)),
        "property float x\nproperty float y\nproperty float z\n",
        "element face {}\n".format(len(faces)),
        "property list uchar int vertex_indices\n",
        "end_header\n",
    ]
    lines.extend("{:.12g} {:.12g} {:.12g}\n".format(*value) for value in vertices)
    lines.extend("3 {} {} {}\n".format(*[int(value) for value in face]) for face in faces)
    atomic_write_text(path, "".join(lines))


def read_ascii_ply(path: Path) -> Tuple[np.ndarray, np.ndarray]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    vertex_count = face_count = None
    end = None
    for index, line in enumerate(lines):
        if line.startswith("element vertex "):
            vertex_count = int(line.split()[-1])
        elif line.startswith("element face "):
            face_count = int(line.split()[-1])
        elif line == "end_header":
            end = index + 1
            break
    if vertex_count is None or face_count is None or end is None:
        raise SceneExportError("ASCII PLY header가 유효하지 않습니다: {}".format(path))
    vertices = np.asarray([[float(v) for v in line.split()[:3]] for line in lines[end : end + vertex_count]])
    face_lines = lines[end + vertex_count : end + vertex_count + face_count]
    faces = np.asarray([[int(v) for v in line.split()[1:4]] for line in face_lines], dtype=int)
    return vertices, faces


# Sionna는 id가 "itu_"/"itu-"로 시작하는 BSDF를 XML 단계에서 다시 쓰면서
# type/thickness/color만 남기고 scattering_coefficient 같은 나머지 property를 버린다
# (sionna/rt/scene_utils.py). Phase 2-B material_resolver와 같은 "radio_itu_" 접두사를 쓴다.
MATERIAL_ID_PREFIX = "radio_itu"


def _material_id(semantic: str) -> str:
    return "{}_concrete_{}".format(
        MATERIAL_ID_PREFIX, "walls" if semantic == "wall" else semantic)


def export_scene(
    metric_scene: MetricScene, settings: Dict[str, Any], output_directory: Path
) -> Dict[str, Any]:
    output = Path(output_directory).expanduser().resolve()
    scene_directory = output / "scene"
    mesh_directory = scene_directory / "meshes"
    mesh_directory.mkdir(parents=True, exist_ok=True)
    for stale in mesh_directory.glob("*.ply"):
        stale.unlink()
    object_records: List[Dict[str, Any]] = []
    xml = ["<scene version=\"2.1.0\">\n", "    <!-- PROVISIONAL RF MATERIALS -->\n"]
    for semantic in ("floor", "ceiling", "walls"):
        material = settings["materials"][semantic]
        preset = material["preset"]
        material_id = "{}_{}_{}".format(MATERIAL_ID_PREFIX, preset, semantic)
        xml.extend(
            [
                "    <bsdf type=\"itu-radio-material\" id=\"{}\">\n".format(material_id),
                "        <string name=\"type\" value=\"{}\"/>\n".format(preset),
                "        <float name=\"thickness\" value=\"0.1\"/>\n",
            ]
        )
        # Sionna는 두 계수를 XML property로 읽는다. 적지 않으면 0.0이고,
        # scattering_coefficient가 0이면 diffuse_reflection을 켜도 확산 경로가 없다.
        for key in ("scattering_coefficient", "xpd_coefficient"):
            if key in material:
                xml.append("        <float name=\"{}\" value=\"{}\"/>\n".format(
                    key, float(material[key])))
        xml.append("    </bsdf>\n")
    xml.append("\n    <!-- Metric Room Envelope shapes -->\n")
    exported_vertices = []
    exported_faces_global = []
    vertex_offset = 0
    for obj in metric_scene.objects:
        local_vertices, local_faces = _local_mesh(metric_scene.vertices, obj.faces)
        path = mesh_directory / "{}.ply".format(obj.name)
        write_ascii_ply(path, local_vertices, local_faces)
        semantic_key = "walls" if obj.semantic == "wall" else obj.semantic
        material_id = "{}_{}_{}".format(
            MATERIAL_ID_PREFIX, settings["materials"][semantic_key]["preset"], semantic_key)
        xml.extend(
            [
                "    <shape type=\"ply\" id=\"mesh-{}\">\n".format(obj.name),
                "        <string name=\"filename\" value=\"meshes/{}.ply\"/>\n".format(obj.name),
                "        <boolean name=\"face_normals\" value=\"true\"/>\n",
                "        <ref id=\"{}\" name=\"bsdf\"/>\n".format(material_id),
                "    </shape>\n",
            ]
        )
        loaded_vertices, loaded_faces = read_ascii_ply(path)
        if not np.allclose(loaded_vertices, local_vertices, atol=1e-9) or not np.array_equal(loaded_faces, local_faces):
            raise SceneExportError("내보낸 PLY를 다시 읽었을 때 geometry가 달라졌습니다.")
        object_records.append(
            {
                "object_name": obj.name,
                "semantic": obj.semantic,
                "source_material": obj.material,
                "resolved_radio_material": material_id,
                "mesh_file": str(path.resolve()),
                "vertex_count": int(len(local_vertices)),
                "triangle_count": int(len(local_faces)),
                "bounds": mesh_statistics(local_vertices, local_faces)["bounds"],
            }
        )
        exported_vertices.extend(local_vertices.tolist())
        exported_faces_global.extend((local_faces + vertex_offset).tolist())
        vertex_offset += len(local_vertices)
    xml.append("</scene>\n")
    scene_xml = scene_directory / "scene.xml"
    atomic_write_text(scene_xml, "".join(xml))
    source_stats = mesh_statistics(metric_scene.vertices, metric_scene.faces)
    exported_stats = mesh_statistics(np.asarray(exported_vertices), np.asarray(exported_faces_global))
    validation = {
        "triangle_count_match": source_stats["triangle_count"] == exported_stats["triangle_count"],
        "bounds_match": bool(
            np.allclose(source_stats["bounds"]["min"], exported_stats["bounds"]["min"], atol=1e-9)
            and np.allclose(source_stats["bounds"]["max"], exported_stats["bounds"]["max"], atol=1e-9)
        ),
        "surface_area_match": bool(
            np.isclose(source_stats["surface_area"], exported_stats["surface_area"], atol=1e-8)
        ),
        "volume_match": bool(
            np.isclose(source_stats["signed_volume"], exported_stats["signed_volume"], atol=1e-8)
        ),
    }
    validation["success"] = all(validation.values())
    if not validation["success"]:
        raise SceneExportError("Sionna scene mesh 변환 검증에 실패했습니다.")
    manifest = {
        "schema_version": "1.0",
        "status": settings["status"],
        "confidence": settings["confidence"],
        "physically_validated": settings["physically_validated"],
        "scene_name": settings["scene"]["name"],
        "scene_xml": str(scene_xml.resolve()),
        "source_metric_obj": str(metric_scene.paths["metric_obj"]),
        "source_statistics": source_stats,
        "exported_statistics": exported_stats,
        "objects": object_records,
        "conversion_validation": validation,
    }
    write_json(output / "scene_manifest.json", manifest)
    return manifest
