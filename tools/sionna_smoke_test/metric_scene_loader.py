"""Phase 1.5-C 미터 단위 Room Envelope와 OBJ 그룹을 읽는다."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from .io_utils import read_json


class MetricSceneError(ValueError):
    """미터 단위 Room Envelope 입력이 Phase 2-A 조건을 만족하지 않을 때 발생한다."""


@dataclass
class MeshObject:
    name: str
    semantic: str
    material: str
    faces: np.ndarray


@dataclass
class MetricScene:
    vertices: np.ndarray
    faces: np.ndarray
    objects: List[MeshObject]
    metric_metadata: Dict[str, Any]
    calibration: Dict[str, Any]
    paths: Dict[str, Path]


def _parse_index(token: str, count: int) -> int:
    try:
        value = int(token.split("/", 1)[0])
    except ValueError as exc:
        raise MetricSceneError("OBJ face index를 읽을 수 없습니다: {}".format(token)) from exc
    if value == 0:
        raise MetricSceneError("OBJ face index 0은 허용되지 않습니다.")
    return value - 1 if value > 0 else count + value


def parse_metric_obj(path: Path):
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise MetricSceneError("Metric OBJ를 찾을 수 없습니다: {}".format(source))
    vertices = []
    object_faces: Dict[str, List[List[int]]] = {}
    object_semantics: Dict[str, str] = {}
    object_materials: Dict[str, str] = {}
    current_object = None
    current_group = None
    current_material = None
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise MetricSceneError("Metric OBJ를 읽을 수 없습니다: {}".format(exc)) from exc
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("v "):
            parts = stripped.split()
            if len(parts) < 4:
                raise MetricSceneError("OBJ vertex 좌표가 부족합니다.")
            vertices.append([float(parts[1]), float(parts[2]), float(parts[3])])
        elif stripped.startswith("o "):
            current_object = stripped.split(maxsplit=1)[1]
            object_faces.setdefault(current_object, [])
        elif stripped.startswith("g "):
            current_group = stripped.split(maxsplit=1)[1]
            if current_object is not None:
                object_semantics[current_object] = current_group
        elif stripped.startswith("usemtl "):
            current_material = stripped.split(maxsplit=1)[1]
            if current_object is not None:
                object_materials[current_object] = current_material
        elif stripped.startswith("f "):
            if current_object is None:
                raise MetricSceneError("OBJ face보다 object 선언이 먼저 필요합니다.")
            tokens = stripped.split()[1:]
            indices = [_parse_index(token, len(vertices)) for token in tokens]
            for index in range(1, len(indices) - 1):
                object_faces[current_object].append([indices[0], indices[index], indices[index + 1]])
            object_semantics.setdefault(current_object, current_group or "unknown")
            object_materials.setdefault(current_object, current_material or "unknown")
    vertex_array = np.asarray(vertices, dtype=float)
    if vertex_array.ndim != 2 or vertex_array.shape[1] != 3 or not np.all(np.isfinite(vertex_array)):
        raise MetricSceneError("OBJ vertex가 유효하지 않습니다.")
    objects = []
    all_faces = []
    for name, faces in object_faces.items():
        if not faces:
            continue
        array = np.asarray(faces, dtype=int)
        if np.any(array < 0) or np.any(array >= len(vertex_array)):
            raise MetricSceneError("OBJ face index가 vertex 범위를 벗어납니다.")
        objects.append(
            MeshObject(
                name=name,
                semantic=object_semantics.get(name, "unknown"),
                material=object_materials.get(name, "unknown"),
                faces=array,
            )
        )
        all_faces.extend(array.tolist())
    if not objects:
        raise MetricSceneError("OBJ에서 object와 face를 찾지 못했습니다.")
    return vertex_array, np.asarray(all_faces, dtype=int), objects


def mesh_statistics(vertices: np.ndarray, faces: np.ndarray) -> Dict[str, Any]:
    points = np.asarray(vertices, dtype=float)
    triangles = np.asarray(faces, dtype=int)
    first, second, third = points[triangles[:, 0]], points[triangles[:, 1]], points[triangles[:, 2]]
    cross = np.cross(second - first, third - first)
    areas = 0.5 * np.linalg.norm(cross, axis=1)
    signed_volume = float(np.sum(np.einsum("ij,ij->i", first, np.cross(second, third))) / 6.0)
    minimum, maximum = np.min(points, axis=0), np.max(points, axis=0)
    return {
        "vertex_count": int(len(points)),
        "triangle_count": int(len(triangles)),
        "bounds": {
            "min": minimum.tolist(),
            "max": maximum.tolist(),
            "extent": (maximum - minimum).tolist(),
        },
        "surface_area": float(np.sum(areas)),
        "signed_volume": signed_volume,
        "absolute_volume": abs(signed_volume),
    }


def load_metric_scene(settings: Dict[str, Any]) -> MetricScene:
    paths = {key: Path(value).expanduser().resolve() for key, value in settings["input"].items()}
    for key, path in paths.items():
        if not path.is_file():
            raise MetricSceneError("{} 입력 파일을 찾을 수 없습니다: {}".format(key, path))
    metadata = read_json(paths["metric_json"])
    calibration = read_json(paths["calibration_json"])
    coordinate = metadata.get("coordinate_system", {})
    topology = metadata.get("topology_summary", {})
    if coordinate.get("unit") != "meter" or coordinate.get("up_axis") != "+Z":
        raise MetricSceneError("Metric metadata가 meter/+Z 좌표계가 아닙니다.")
    if not topology.get("closed_manifold_success"):
        raise MetricSceneError("Metric Room Envelope가 닫힌 manifold가 아닙니다.")
    if topology.get("boundary_edge_count") != 0 or topology.get("non_manifold_edge_count") != 0:
        raise MetricSceneError("Metric Room Envelope에 경계 또는 비다양체 모서리가 있습니다.")
    if topology.get("signed_volume", 0.0) <= 0.0:
        raise MetricSceneError("Metric Room Envelope의 부호 있는 부피가 양수가 아닙니다.")
    if calibration.get("status") != "provisional" or calibration.get("is_provisional") is not True:
        raise MetricSceneError("현재 Smoke Test는 provisional calibration 입력을 요구합니다.")
    vertices, faces, objects = parse_metric_obj(paths["metric_obj"])
    stats = mesh_statistics(vertices, faces)
    if stats["vertex_count"] != topology.get("vertex_count") or stats["triangle_count"] != topology.get("triangle_count"):
        raise MetricSceneError("Metric OBJ와 metadata의 vertex/triangle 수가 다릅니다.")
    allowed = {"floor", "ceiling", "wall"}
    if any(obj.semantic not in allowed for obj in objects):
        raise MetricSceneError("OBJ에 알 수 없는 semantic group이 있습니다.")
    return MetricScene(vertices, faces, objects, metadata, calibration, paths)
