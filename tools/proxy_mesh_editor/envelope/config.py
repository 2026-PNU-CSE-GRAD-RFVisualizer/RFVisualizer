"""Room Envelope 전용 YAML 설정 로드와 검증."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict

import numpy as np
import yaml


class EnvelopeConfigError(ValueError):
    """Room Envelope 선택이나 검증 설정에 문제가 있을 때 발생한다."""


DEFAULT_ENVELOPE_CONFIG: Dict[str, Any] = {
    "schema_version": "1.0",
    "room_envelope": {
        "enabled": True,
        "floor": {"candidate_id": ""},
        "ceiling": {"candidate_id": ""},
        "ordered_walls": [],
        "interior_point": None,
        "validation": {
            "floor_ceiling_max_angle_deg": 10.0,
            "wall_max_up_dot": 0.25,
            "adjacent_wall_min_angle_deg": 10.0,
            "plane_residual_tolerance": 1.0e-6,
            "vertex_merge_tolerance": 1.0e-6,
            "intersection_max_condition_number": 1.0e12,
            "minimum_height": None,
            "minimum_height_ratio": 0.05,
            "require_simple_polygon": True,
            "require_closed_manifold": True,
        },
        "output": {
            "normal_orientation": "outward",
            "write_individual_objects": True,
            "write_preview_ply": True,
        },
    },
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _finite_number(value: Any, field: str, positive: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise EnvelopeConfigError("{} 값은 숫자여야 합니다.".format(field)) from exc
    if not np.isfinite(number) or (positive and number <= 0.0):
        relation = "유한한 양수" if positive else "유한한 숫자"
        raise EnvelopeConfigError("{} 값은 {}여야 합니다.".format(field, relation))
    return number


def _candidate_id(section: Any, field: str) -> str:
    if not isinstance(section, dict):
        raise EnvelopeConfigError("{}는 candidate_id를 가진 항목이어야 합니다.".format(field))
    candidate_id = str(section.get("candidate_id", "")).strip()
    if not candidate_id:
        raise EnvelopeConfigError("{}.candidate_id가 비어 있습니다.".format(field))
    return candidate_id


def validate_envelope_config(config: Dict[str, Any]) -> Dict[str, Any]:
    room = config["room_envelope"]
    if not isinstance(room["enabled"], bool):
        raise EnvelopeConfigError("room_envelope.enabled는 true 또는 false여야 합니다.")
    _candidate_id(room["floor"], "room_envelope.floor")
    _candidate_id(room["ceiling"], "room_envelope.ceiling")

    ordered = room["ordered_walls"]
    if not isinstance(ordered, list) or len(ordered) < 3:
        raise EnvelopeConfigError("room_envelope.ordered_walls에는 벽이 3개 이상 필요합니다.")
    wall_ids = [
        _candidate_id(item, "room_envelope.ordered_walls[{}]".format(index))
        for index, item in enumerate(ordered)
    ]
    if len(set(wall_ids)) != len(wall_ids):
        raise EnvelopeConfigError("room_envelope.ordered_walls에 중복 candidate_id가 있습니다.")

    interior = room.get("interior_point")
    if interior is not None:
        values = np.asarray(interior, dtype=float)
        if values.shape != (3,) or not np.all(np.isfinite(values)):
            raise EnvelopeConfigError("room_envelope.interior_point는 유한한 숫자 3개여야 합니다.")

    validation = room["validation"]
    angle = _finite_number(
        validation["floor_ceiling_max_angle_deg"],
        "room_envelope.validation.floor_ceiling_max_angle_deg",
        positive=True,
    )
    if angle >= 90.0:
        raise EnvelopeConfigError("floor_ceiling_max_angle_deg는 90도보다 작아야 합니다.")
    wall_dot = _finite_number(
        validation["wall_max_up_dot"],
        "room_envelope.validation.wall_max_up_dot",
    )
    if not 0.0 <= wall_dot <= 1.0:
        raise EnvelopeConfigError("wall_max_up_dot는 0과 1 사이여야 합니다.")
    adjacent_angle = _finite_number(
        validation["adjacent_wall_min_angle_deg"],
        "room_envelope.validation.adjacent_wall_min_angle_deg",
        positive=True,
    )
    if adjacent_angle >= 90.0:
        raise EnvelopeConfigError("adjacent_wall_min_angle_deg는 90도보다 작아야 합니다.")
    for key in (
        "plane_residual_tolerance",
        "vertex_merge_tolerance",
        "intersection_max_condition_number",
    ):
        _finite_number(
            validation[key], "room_envelope.validation.{}".format(key), positive=True
        )

    minimum_height = validation.get("minimum_height")
    ratio = _finite_number(
        validation["minimum_height_ratio"],
        "room_envelope.validation.minimum_height_ratio",
    )
    if ratio < 0.0:
        raise EnvelopeConfigError("minimum_height_ratio는 0 이상이어야 합니다.")
    if minimum_height is not None:
        _finite_number(
            minimum_height,
            "room_envelope.validation.minimum_height",
            positive=True,
        )
    elif ratio <= 0.0:
        raise EnvelopeConfigError(
            "minimum_height가 null이면 minimum_height_ratio는 0보다 커야 합니다."
        )

    for key in ("require_simple_polygon", "require_closed_manifold"):
        if not isinstance(validation[key], bool):
            raise EnvelopeConfigError(
                "room_envelope.validation.{}는 true 또는 false여야 합니다.".format(key)
            )

    output = room["output"]
    if output["normal_orientation"] != "outward":
        raise EnvelopeConfigError("현재 normal_orientation은 outward만 지원합니다.")
    for key in ("write_individual_objects", "write_preview_ply"):
        if not isinstance(output[key], bool):
            raise EnvelopeConfigError(
                "room_envelope.output.{}는 true 또는 false여야 합니다.".format(key)
            )
    return config


def load_envelope_config(path: Path) -> Dict[str, Any]:
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise EnvelopeConfigError("Envelope 설정 파일을 찾을 수 없습니다: {}".format(config_path))
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise EnvelopeConfigError("Envelope 설정 파일을 읽을 수 없습니다: {}".format(exc)) from exc
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise EnvelopeConfigError("Envelope YAML 최상위 값은 키와 값의 모음이어야 합니다.")
    return validate_envelope_config(_deep_merge(DEFAULT_ENVELOPE_CONFIG, loaded))
