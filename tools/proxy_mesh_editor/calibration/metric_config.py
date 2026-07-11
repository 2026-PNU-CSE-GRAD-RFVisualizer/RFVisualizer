"""Phase 1.5-C 실제 크기 보정 설정 로드와 검증."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict

import numpy as np
import yaml


class MetricCalibrationConfigError(ValueError):
    """실제 크기 보정 설정이 안전 조건을 만족하지 않을 때 발생한다."""


DEFAULT_METRIC_CONFIG: Dict[str, Any] = {
    "schema_version": "1.0",
    "metric_calibration": {
        "status": "provisional",
        "confidence": "low",
        "source": {"envelope_json": "", "envelope_obj": ""},
        "scale": {
            "method": "weighted_least_squares",
            "uniform_scale_only": True,
            "references": [],
        },
        "coordinate_frame": {
            "source_up": {"type": "envelope_scene_up_vector"},
            "target_up": [0.0, 0.0, 1.0],
            "origin": {"type": "envelope_bottom_corner", "corner_index": 0},
            "x_axis": {
                "type": "envelope_bottom_edge",
                "start_corner": 0,
                "end_corner": 1,
                "remove_up_component": True,
            },
            "handedness": "right",
            "require_proper_rotation": True,
        },
        "validation": {
            "maximum_reference_relative_error": 0.10,
            "maximum_reference_spread_warning": 0.05,
            "maximum_reference_spread_failure": 0.20,
            "maximum_rotation_determinant_error": 1.0e-8,
            "maximum_orthogonality_error": 1.0e-8,
            "maximum_axis_alignment_error": 1.0e-8,
            "maximum_origin_error": 1.0e-8,
            "maximum_round_trip_error": 1.0e-8,
            "maximum_plane_residual": 1.0e-7,
            "topology_must_match_source": True,
        },
        "output": {
            "write_obj": True,
            "write_ply": True,
            "write_metric_metadata": True,
            "write_axis_preview": True,
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


def _finite_positive(value: Any, field: str, allow_zero: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise MetricCalibrationConfigError("{} 값은 숫자여야 합니다.".format(field)) from exc
    valid = number >= 0.0 if allow_zero else number > 0.0
    if not np.isfinite(number) or not valid:
        relation = "0 이상" if allow_zero else "0보다 큰"
        raise MetricCalibrationConfigError(
            "{} 값은 유한하고 {} 수여야 합니다.".format(field, relation)
        )
    return number


def _corner_index(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise MetricCalibrationConfigError("{}는 0 이상의 정수여야 합니다.".format(field))
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise MetricCalibrationConfigError("{}는 0 이상의 정수여야 합니다.".format(field)) from exc
    if number < 0 or float(value) != float(number):
        raise MetricCalibrationConfigError("{}는 0 이상의 정수여야 합니다.".format(field))
    return number


def validate_metric_config(config: Dict[str, Any]) -> Dict[str, Any]:
    settings = config.get("metric_calibration")
    if not isinstance(settings, dict):
        raise MetricCalibrationConfigError("metric_calibration 설정이 필요합니다.")
    if settings.get("status") not in {"provisional", "measured"}:
        raise MetricCalibrationConfigError("status는 provisional 또는 measured여야 합니다.")
    if not str(settings.get("confidence", "")).strip():
        raise MetricCalibrationConfigError("confidence가 비어 있습니다.")

    scale = settings["scale"]
    if scale.get("method") != "weighted_least_squares":
        raise MetricCalibrationConfigError("이번 단계는 weighted_least_squares만 지원합니다.")
    if scale.get("uniform_scale_only") is not True:
        raise MetricCalibrationConfigError("축마다 다른 배율은 지원하지 않습니다.")
    references = scale.get("references")
    if not isinstance(references, list) or not references:
        raise MetricCalibrationConfigError("scale reference가 하나 이상 필요합니다.")
    names = []
    for index, reference in enumerate(references):
        if not isinstance(reference, dict):
            raise MetricCalibrationConfigError("scale reference 형식이 올바르지 않습니다.")
        name = str(reference.get("name", "")).strip()
        if not name:
            raise MetricCalibrationConfigError("scale reference name이 비어 있습니다.")
        names.append(name)
        _finite_positive(reference.get("scene_distance"), "references[{}].scene_distance".format(index))
        _finite_positive(reference.get("real_distance_m"), "references[{}].real_distance_m".format(index))
        _finite_positive(reference.get("weight", 1.0), "references[{}].weight".format(index))
    if len(names) != len(set(names)):
        raise MetricCalibrationConfigError("scale reference name이 중복됩니다.")

    frame = settings["coordinate_frame"]
    if frame["source_up"].get("type") != "envelope_scene_up_vector":
        raise MetricCalibrationConfigError("source_up은 envelope scene up을 사용해야 합니다.")
    target = np.asarray(frame.get("target_up"), dtype=float)
    if target.shape != (3,) or not np.all(np.isfinite(target)) or np.linalg.norm(target) <= 1e-12:
        raise MetricCalibrationConfigError("target_up은 유한한 영벡터가 아닌 3차원 벡터여야 합니다.")
    if not np.allclose(target / np.linalg.norm(target), [0.0, 0.0, 1.0], atol=1e-12):
        raise MetricCalibrationConfigError("현재 canonical target_up은 +Z만 지원합니다.")
    if frame["origin"].get("type") != "envelope_bottom_corner":
        raise MetricCalibrationConfigError("origin은 envelope bottom corner여야 합니다.")
    _corner_index(frame["origin"].get("corner_index"), "origin.corner_index")
    if frame["x_axis"].get("type") != "envelope_bottom_edge":
        raise MetricCalibrationConfigError("X축은 envelope bottom edge여야 합니다.")
    start = _corner_index(frame["x_axis"].get("start_corner"), "x_axis.start_corner")
    end = _corner_index(frame["x_axis"].get("end_corner"), "x_axis.end_corner")
    if start == end:
        raise MetricCalibrationConfigError("X축 시작점과 끝점은 달라야 합니다.")
    if frame["x_axis"].get("remove_up_component") is not True:
        raise MetricCalibrationConfigError("X축에서는 scene up 성분을 제거해야 합니다.")
    if frame.get("handedness") != "right" or frame.get("require_proper_rotation") is not True:
        raise MetricCalibrationConfigError("오른손 좌표계의 proper rotation만 지원합니다.")

    validation = settings["validation"]
    for key, value in validation.items():
        if key == "topology_must_match_source":
            if value is not True:
                raise MetricCalibrationConfigError("topology_must_match_source는 true여야 합니다.")
        else:
            _finite_positive(value, "validation.{}".format(key))
    if float(validation["maximum_reference_spread_failure"]) <= float(
        validation["maximum_reference_spread_warning"]
    ):
        raise MetricCalibrationConfigError("배율 failure 기준은 warning 기준보다 커야 합니다.")
    for key, value in settings["output"].items():
        if not isinstance(value, bool):
            raise MetricCalibrationConfigError("output.{}는 true 또는 false여야 합니다.".format(key))
    return config


def load_metric_config(path: Path) -> Dict[str, Any]:
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise MetricCalibrationConfigError("실제 크기 보정 설정을 찾을 수 없습니다: {}".format(config_path))
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise MetricCalibrationConfigError("실제 크기 보정 설정을 읽을 수 없습니다: {}".format(exc)) from exc
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise MetricCalibrationConfigError("설정 최상위 값은 키와 값의 모음이어야 합니다.")
    return validate_metric_config(_deep_merge(DEFAULT_METRIC_CONFIG, loaded))
