"""Strict YAML candidate templates for provisional object creation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import yaml

from tools.sionna_scenario.material_resolver import CATEGORY_TO_ITU_TYPE


class CandidateLibraryError(ValueError):
    pass


@dataclass(frozen=True)
class CandidateTemplate:
    id: str
    label: str
    source: Dict[str, Any]


def _positive_size(value: Any, label: str) -> List[float]:
    try:
        result = [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise CandidateLibraryError(
            "{}에는 숫자 3개가 필요합니다.".format(label)
        ) from exc
    if (
        len(result) != 3
        or not np.all(np.isfinite(result))
        or np.any(np.asarray(result) <= 0.0)
    ):
        raise CandidateLibraryError(
            "{}에는 0보다 큰 유한한 숫자 3개가 필요합니다.".format(label)
        )
    return result


def load_candidate_library(path: Path) -> List[CandidateTemplate]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise CandidateLibraryError(
            "Candidate library를 찾을 수 없습니다: {}".format(source)
        )
    try:
        document = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CandidateLibraryError(
            "Candidate library를 읽을 수 없습니다: {}".format(exc)
        ) from exc
    values = document.get("candidates") if isinstance(document, dict) else None
    if not isinstance(values, list) or not values:
        raise CandidateLibraryError("candidates 목록이 비어 있습니다.")
    result = []
    identifiers = set()
    for index, value in enumerate(values):
        if not isinstance(value, dict):
            raise CandidateLibraryError(
                "candidates[{}]가 mapping이 아닙니다.".format(index)
            )
        candidate_id = value.get("id")
        label = value.get("label")
        if (
            not isinstance(candidate_id, str)
            or not candidate_id
            or candidate_id in identifiers
        ):
            raise CandidateLibraryError(
                "Candidate ID가 비어 있거나 중복됩니다: {}".format(candidate_id)
            )
        if not isinstance(label, str) or not label.strip():
            raise CandidateLibraryError("Candidate label이 비어 있습니다.")
        geometry = value.get("geometry", {})
        geometry_type = geometry.get("type")
        if geometry_type not in {"box", "thin_panel"}:
            raise CandidateLibraryError(
                "Candidate geometry는 box/thin_panel만 지원합니다."
            )
        _positive_size(
            geometry.get("default_size_m"), "{}.default_size_m".format(candidate_id)
        )
        category = value.get("material", {}).get("category")
        if category not in CATEGORY_TO_ITU_TYPE:
            raise CandidateLibraryError(
                "Candidate material category가 지원되지 않습니다: {}".format(category)
            )
        anchor = value.get("anchor", {})
        if anchor.get("mode") not in {"center", "bottom_center", "floor_at_xy"}:
            raise CandidateLibraryError("Candidate anchor mode가 지원되지 않습니다.")
        identifiers.add(candidate_id)
        result.append(CandidateTemplate(candidate_id, label.strip(), deepcopy(value)))
    return result


def instantiate_candidate(
    template: CandidateTemplate, object_id: str, room: Any
) -> Dict[str, Any]:
    source = template.source
    geometry = source["geometry"]
    anchor = deepcopy(source["anchor"])
    center = np.asarray(room.interior_point, dtype=float)
    mode = anchor["mode"]
    if mode == "floor_at_xy":
        position: Any = {"x": float(center[0]), "y": float(center[1])}
    else:
        floor_z, ceiling_z = room.floor_ceiling_z(float(center[0]), float(center[1]))
        z = floor_z if mode == "bottom_center" else (floor_z + ceiling_z) / 2.0
        position = {"x": float(center[0]), "y": float(center[1]), "z": float(z)}
    metadata = source.get("metadata", {})
    return {
        "id": object_id,
        "display_name": template.label,
        "enabled": False,
        "semantic_class": metadata.get("semantic_class", template.id),
        "purpose": metadata.get("purpose", "classroom_proxy"),
        "physical_object": bool(metadata.get("physical_object", True)),
        "confidence": metadata.get("confidence", "unset"),
        "measurement_source": metadata.get("measurement_source", "unset"),
        "notes": "UI convenience placeholder; not an on-site measurement.",
        "placement_status": "provisional_unconfirmed",
        "geometry": {
            "type": geometry["type"],
            "anchor": anchor,
            "position_m": position,
            "size_m": [float(value) for value in geometry["default_size_m"]],
            "rotation_deg": {"roll": 0.0, "pitch": 0.0, "yaw": 0.0},
        },
        "material": {
            "source": "sionna_preset",
            "category": source["material"]["category"],
            "preset": source["material"]["category"],
            "thickness_m": float(source["material"].get("thickness_m", 0.1)),
            "scattering_coefficient": float(
                source["material"].get("scattering_coefficient", 0.0)
            ),
        },
        "export": {
            "object_name": object_id,
            "group_name": metadata.get("semantic_class", template.id),
        },
    }
