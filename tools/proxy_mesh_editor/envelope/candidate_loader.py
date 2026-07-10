"""일반 평면과 벽 후보 문서에서 Room Envelope 선택 항목을 읽는다."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from ..config import normalize_vector
from ..io.metadata_io import MetadataError, read_json
from ..models import PlaneCandidate


@dataclass
class EnvelopeCandidates:
    floor: PlaneCandidate
    ceiling: PlaneCandidate
    walls: List[PlaneCandidate]
    up_vector: np.ndarray
    plane_document_path: Path
    wall_document_path: Path
    plane_document: Dict[str, Any]
    wall_document: Dict[str, Any]


def _candidate_map(document: Dict[str, Any], key: str, label: str) -> Dict[str, PlaneCandidate]:
    raw = document.get(key)
    if not isinstance(raw, list):
        raise MetadataError("{} 문서에 {} 목록이 없습니다.".format(label, key))
    candidates = [PlaneCandidate.from_dict(item) for item in raw]
    ids = [candidate.candidate_id for candidate in candidates]
    if len(set(ids)) != len(ids):
        raise MetadataError("{} 문서에 중복 candidate_id가 있습니다.".format(label))
    return {candidate.candidate_id: candidate for candidate in candidates}


def _validate_candidate_geometry(candidate: PlaneCandidate, label: str) -> None:
    equation = np.asarray(candidate.plane_equation, dtype=float)
    normal = np.asarray(candidate.normal, dtype=float)
    if equation.shape != (4,) or not np.all(np.isfinite(equation)):
        raise MetadataError("{}의 평면식이 유한한 숫자 4개가 아닙니다.".format(label))
    if normal.shape != (3,) or not np.all(np.isfinite(normal)):
        raise MetadataError("{}의 법선이 유한한 숫자 3개가 아닙니다.".format(label))
    if float(np.linalg.norm(equation[:3])) <= 1e-12 or float(np.linalg.norm(normal)) <= 1e-12:
        raise MetadataError("{}의 평면 법선 길이가 0입니다.".format(label))


def _document_up_vector(document: Dict[str, Any], label: str) -> np.ndarray:
    values = document.get("scene", {}).get("up_vector")
    if values is None:
        raise MetadataError("{} 문서에 scene.up_vector가 없습니다.".format(label))
    return normalize_vector(values, "{}.scene.up_vector".format(label))


def load_envelope_candidates(
    plane_path: Path,
    wall_path: Path,
    envelope_config: Dict[str, Any],
) -> EnvelopeCandidates:
    plane_file = Path(plane_path).expanduser().resolve()
    wall_file = Path(wall_path).expanduser().resolve()
    plane_document = read_json(plane_file)
    wall_document = read_json(wall_file)
    general = _candidate_map(plane_document, "plane_candidates", "일반 후보")
    walls_by_id = _candidate_map(wall_document, "wall_candidates", "벽 후보")
    duplicate_document_ids = set(general).intersection(walls_by_id)
    if duplicate_document_ids:
        raise MetadataError(
            "일반 후보와 벽 후보 문서의 candidate_id가 충돌합니다: {}".format(
                ", ".join(sorted(duplicate_document_ids))
            )
        )

    room = envelope_config["room_envelope"]
    floor_id = str(room["floor"]["candidate_id"])
    ceiling_id = str(room["ceiling"]["candidate_id"])
    if floor_id == ceiling_id:
        raise MetadataError("floor와 ceiling은 서로 다른 candidate_id여야 합니다.")
    if floor_id not in general:
        raise MetadataError("일반 후보 문서에 floor 후보가 없습니다: {}".format(floor_id))
    if ceiling_id not in general:
        raise MetadataError("일반 후보 문서에 ceiling 후보가 없습니다: {}".format(ceiling_id))
    floor = general[floor_id]
    ceiling = general[ceiling_id]
    if floor.orientation != "horizontal" or ceiling.orientation != "horizontal":
        raise MetadataError("선택한 floor와 ceiling은 horizontal 후보여야 합니다.")

    selected_walls = []
    for item in room["ordered_walls"]:
        candidate_id = str(item["candidate_id"])
        if candidate_id not in walls_by_id:
            raise MetadataError("벽 후보 문서에 선택한 후보가 없습니다: {}".format(candidate_id))
        candidate = walls_by_id[candidate_id]
        if candidate.source_pass != "wall_extraction":
            raise MetadataError("{}의 source_pass가 wall_extraction이 아닙니다.".format(candidate_id))
        if candidate.orientation != "vertical":
            raise MetadataError("{} 후보의 방향이 vertical이 아닙니다.".format(candidate_id))
        selected_walls.append(candidate)

    for label, candidate in [("floor", floor), ("ceiling", ceiling)]:
        _validate_candidate_geometry(candidate, label)
    for candidate in selected_walls:
        _validate_candidate_geometry(candidate, candidate.candidate_id)

    plane_up = _document_up_vector(plane_document, "일반 후보")
    wall_up = _document_up_vector(wall_document, "벽 후보")
    if abs(float(np.dot(plane_up, wall_up))) < 1.0 - 1e-6:
        raise MetadataError("일반 후보와 벽 후보 문서의 up_vector가 일치하지 않습니다.")
    if float(np.dot(plane_up, wall_up)) < 0.0:
        wall_up = -wall_up

    return EnvelopeCandidates(
        floor=floor,
        ceiling=ceiling,
        walls=selected_walls,
        up_vector=plane_up,
        plane_document_path=plane_file,
        wall_document_path=wall_file,
        plane_document=plane_document,
        wall_document=wall_document,
    )
