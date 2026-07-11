"""Metric Calibration Preflight 전용 YAML 설정 로드와 검증."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict

import numpy as np
import yaml


class CalibrationPreflightConfigError(ValueError):
    """Preflight 설정에 문제가 있을 때 발생한다."""


DEFAULT_PREFLIGHT_CONFIG: Dict[str, Any] = {
    "schema_version": "1.0",
    "calibration_preflight": {
        "status": "provisional",
        "confidence": "low",
        "source": {"envelope_json": "", "envelope_obj": ""},
        "scale_references": [],
        "scale_analysis": {
            "supported_estimators": [
                "arithmetic_mean_of_ratios",
                "weighted_mean_of_ratios",
                "weighted_least_squares",
                "median_of_ratios",
            ],
            "recommended_estimator": "weighted_least_squares",
            "uniform_scale_only": True,
            "warning_relative_spread": 0.05,
            "failure_relative_spread": 0.20,
        },
        "orientation": {
            "source_up": {"type": "envelope_scene_up_vector"},
            "target_up": [0.0, 0.0, 1.0],
            "require_proper_rotation": True,
            "minimum_rotation_determinant": 0.999999,
            "maximum_rotation_determinant": 1.000001,
        },
        "frame_candidates": {
            "origin_methods": ["lowest_bottom_corner", "explicit_bottom_corner"],
            "default_origin_method": "lowest_bottom_corner",
            "x_axis_methods": [
                "longest_horizontal_envelope_edge",
                "explicit_envelope_edge",
            ],
            "default_x_axis_method": "longest_horizontal_envelope_edge",
            "remove_up_component_from_x_axis": True,
        },
        "validation": {
            "minimum_positive_height": 1.0e-6,
            "maximum_up_alignment_error": 1.0e-8,
            "maximum_orthogonality_error": 1.0e-8,
            "maximum_round_trip_error": 1.0e-8,
        },
        "preview": {
            "write_rotation_only_obj": True,
            "write_rotation_only_ply": True,
            "write_axis_gizmo_ply": True,
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


def _positive(value: Any, field: str, allow_zero: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CalibrationPreflightConfigError("{} 값은 숫자여야 합니다.".format(field)) from exc
    valid = number >= 0.0 if allow_zero else number > 0.0
    if not np.isfinite(number) or not valid:
        relation = "0 이상" if allow_zero else "0보다 큰"
        raise CalibrationPreflightConfigError(
            "{} 값은 유한하고 {} 수여야 합니다.".format(field, relation)
        )
    return number


def _vector(values: Any, field: str) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.shape != (3,) or not np.all(np.isfinite(array)):
        raise CalibrationPreflightConfigError("{}는 유한한 숫자 3개여야 합니다.".format(field))
    if float(np.linalg.norm(array)) <= 1e-12:
        raise CalibrationPreflightConfigError("{}는 영벡터일 수 없습니다.".format(field))
    return array


def validate_preflight_config(config: Dict[str, Any]) -> Dict[str, Any]:
    preflight = config["calibration_preflight"]
    if preflight["status"] != "provisional":
        raise CalibrationPreflightConfigError("preflight status는 provisional이어야 합니다.")
    references = preflight["scale_references"]
    if not isinstance(references, list) or not references:
        raise CalibrationPreflightConfigError("scale_references가 하나 이상 필요합니다.")
    names = []
    for index, reference in enumerate(references):
        if not isinstance(reference, dict):
            raise CalibrationPreflightConfigError("scale reference는 키와 값의 모음이어야 합니다.")
        name = str(reference.get("name", "")).strip()
        if not name:
            raise CalibrationPreflightConfigError("scale reference name이 비어 있습니다.")
        names.append(name)
        _positive(reference.get("scene_distance"), "scale_references[{}].scene_distance".format(index))
        _positive(
            reference.get("assumed_real_distance_m"),
            "scale_references[{}].assumed_real_distance_m".format(index),
        )
        _positive(reference.get("weight", 1.0), "scale_references[{}].weight".format(index))
    if len(set(names)) != len(names):
        raise CalibrationPreflightConfigError("scale reference name이 중복됩니다.")

    analysis = preflight["scale_analysis"]
    supported = analysis["supported_estimators"]
    required = {
        "arithmetic_mean_of_ratios",
        "weighted_mean_of_ratios",
        "weighted_least_squares",
        "median_of_ratios",
    }
    if not isinstance(supported, list) or not required.issubset(set(supported)):
        raise CalibrationPreflightConfigError("필수 scale estimator 네 가지가 모두 필요합니다.")
    if analysis["recommended_estimator"] not in supported:
        raise CalibrationPreflightConfigError("recommended_estimator가 지원 목록에 없습니다.")
    if analysis["uniform_scale_only"] is not True:
        raise CalibrationPreflightConfigError("이번 도구는 uniform_scale_only=true만 지원합니다.")
    warning = _positive(
        analysis["warning_relative_spread"], "warning_relative_spread", allow_zero=True
    )
    failure = _positive(analysis["failure_relative_spread"], "failure_relative_spread")
    if failure <= warning:
        raise CalibrationPreflightConfigError("failure spread는 warning spread보다 커야 합니다.")

    orientation = preflight["orientation"]
    _vector(orientation["target_up"], "orientation.target_up")
    if orientation["source_up"].get("type") != "envelope_scene_up_vector":
        raise CalibrationPreflightConfigError(
            "orientation.source_up.type은 envelope_scene_up_vector여야 합니다."
        )
    if orientation["require_proper_rotation"] is not True:
        raise CalibrationPreflightConfigError("proper rotation은 반드시 필요합니다.")
    minimum_det = _positive(
        orientation["minimum_rotation_determinant"],
        "orientation.minimum_rotation_determinant",
    )
    maximum_det = _positive(
        orientation["maximum_rotation_determinant"],
        "orientation.maximum_rotation_determinant",
    )
    if not minimum_det < 1.0 < maximum_det:
        raise CalibrationPreflightConfigError("rotation determinant 범위는 1을 포함해야 합니다.")

    frame = preflight["frame_candidates"]
    if frame["default_origin_method"] not in frame["origin_methods"]:
        raise CalibrationPreflightConfigError("default_origin_method가 지원 목록에 없습니다.")
    if frame["default_x_axis_method"] not in frame["x_axis_methods"]:
        raise CalibrationPreflightConfigError("default_x_axis_method가 지원 목록에 없습니다.")
    if frame["remove_up_component_from_x_axis"] is not True:
        raise CalibrationPreflightConfigError("X축 후보는 scene up 성분을 제거해야 합니다.")

    for key, value in preflight["validation"].items():
        _positive(value, "validation.{}".format(key))
    for key, value in preflight["preview"].items():
        if not isinstance(value, bool):
            raise CalibrationPreflightConfigError("preview.{}는 true 또는 false여야 합니다.".format(key))
    return config


def load_preflight_config(path: Path) -> Dict[str, Any]:
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise CalibrationPreflightConfigError("Preflight 설정 파일을 찾을 수 없습니다: {}".format(config_path))
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CalibrationPreflightConfigError("Preflight 설정을 읽을 수 없습니다: {}".format(exc)) from exc
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise CalibrationPreflightConfigError("Preflight YAML 최상위 값은 키와 값의 모음이어야 합니다.")
    return validate_preflight_config(_deep_merge(DEFAULT_PREFLIGHT_CONFIG, loaded))
