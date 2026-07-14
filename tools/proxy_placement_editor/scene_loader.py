"""Load the immutable metric room inputs used by the placement editor."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

from tools.sionna_smoke_test.io_utils import read_json
from tools.sionna_smoke_test.metric_scene_loader import parse_metric_obj
from tools.sionna_smoke_test.placement import RoomContainment


class PlacementSceneError(ValueError):
    """Raised when the immutable room inputs are missing or inconsistent."""


@dataclass
class PlacementScene:
    room_obj_path: Path
    room_json_path: Path
    calibration_path: Path
    room_vertices: np.ndarray
    room_faces: np.ndarray
    room_objects: list
    room_metadata: Dict[str, Any]
    calibration: Dict[str, Any]
    containment: RoomContainment
    source_hashes: Dict[str, str]

    @property
    def center(self) -> np.ndarray:
        return np.asarray(self.containment.interior_point, dtype=float)


def _source(path: Path, label: str) -> Path:
    value = Path(path).expanduser().resolve()
    if not value.is_file():
        raise PlacementSceneError("{} 파일을 찾을 수 없습니다: {}".format(label, value))
    return value


def _hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def infer_room_obj(room_json: Path) -> Path:
    source = _source(room_json, "Room JSON")
    metadata = read_json(source)
    configured = metadata.get("output_files", {}).get("metric_obj")
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.append(source.with_suffix(".obj"))
    for candidate in candidates:
        if not candidate.is_absolute():
            candidate = source.parent / candidate
        candidate = candidate.resolve()
        if candidate.is_file():
            return candidate
    raise PlacementSceneError("Room JSON에서 실제 Metric OBJ 경로를 찾지 못했습니다.")


def load_placement_scene(
    room_json: Path,
    calibration: Path,
    room_obj: Optional[Path] = None,
) -> PlacementScene:
    json_path = _source(room_json, "Room JSON")
    calibration_path = _source(calibration, "Calibration JSON")
    obj_path = _source(room_obj, "Room OBJ") if room_obj else infer_room_obj(json_path)
    metadata = read_json(json_path)
    calibration_document = read_json(calibration_path)
    coordinate = metadata.get("coordinate_system", {})
    topology = metadata.get("topology_summary", {})
    if coordinate.get("unit") != "meter" or coordinate.get("up_axis") != "+Z":
        raise PlacementSceneError("Room Envelope는 meter/+Z 좌표계여야 합니다.")
    if not topology.get("closed_manifold_success"):
        raise PlacementSceneError("Room Envelope가 닫힌 manifold가 아닙니다.")
    vertices, faces, objects = parse_metric_obj(obj_path)
    if len(vertices) != topology.get("vertex_count") or len(faces) != topology.get(
        "triangle_count"
    ):
        raise PlacementSceneError(
            "Room OBJ와 Room JSON의 vertex/triangle 수가 다릅니다."
        )
    containment = RoomContainment.from_metadata(metadata)
    return PlacementScene(
        room_obj_path=obj_path,
        room_json_path=json_path,
        calibration_path=calibration_path,
        room_vertices=vertices,
        room_faces=faces,
        room_objects=objects,
        room_metadata=metadata,
        calibration=calibration_document,
        containment=containment,
        source_hashes={
            "room_obj_sha256": _hash(obj_path),
            "room_json_sha256": _hash(json_path),
            "calibration_sha256": _hash(calibration_path),
        },
    )
