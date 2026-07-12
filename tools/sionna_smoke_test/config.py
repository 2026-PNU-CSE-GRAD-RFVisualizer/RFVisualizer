"""Sionna RT 빈 강의실 연결 시험 설정 로드와 검증."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import numpy as np
import yaml


class SmokeTestConfigError(ValueError):
    """Smoke Test 설정이 유효하지 않을 때 발생한다."""


def _finite(value: Any, field: str, positive: bool = False, allow_zero: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SmokeTestConfigError("{} 값은 숫자여야 합니다.".format(field)) from exc
    valid = np.isfinite(number)
    if positive:
        valid = valid and (number >= 0.0 if allow_zero else number > 0.0)
    if not valid:
        relation = "0 이상" if allow_zero else "0보다 큰"
        raise SmokeTestConfigError(
            "{} 값은 유한한 {} 수여야 합니다.".format(field, relation if positive else "")
        )
    return number


def _positive_int(value: Any, field: str, allow_zero: bool = False) -> int:
    if isinstance(value, bool):
        raise SmokeTestConfigError("{}는 정수여야 합니다.".format(field))
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise SmokeTestConfigError("{}는 정수여야 합니다.".format(field)) from exc
    if float(value) != float(number) or number < (0 if allow_zero else 1):
        raise SmokeTestConfigError("{} 범위가 올바르지 않습니다.".format(field))
    return number


def _position(value: Any, field: str) -> None:
    vector = np.asarray(value, dtype=float)
    if vector.shape != (3,) or not np.all(np.isfinite(vector)):
        raise SmokeTestConfigError("{}는 유한한 숫자 3개여야 합니다.".format(field))


def validate_config(config: Dict[str, Any]) -> Dict[str, Any]:
    settings = config.get("sionna_smoke_test")
    if not isinstance(settings, dict):
        raise SmokeTestConfigError("sionna_smoke_test 설정이 필요합니다.")
    if settings.get("status") != "provisional" or settings.get("confidence") != "low":
        raise SmokeTestConfigError("이번 단계는 provisional/low 상태여야 합니다.")
    if settings.get("physically_validated") is not False:
        raise SmokeTestConfigError("physically_validated는 false여야 합니다.")
    for key in ("metric_obj", "metric_mtl", "metric_json", "calibration_json"):
        if not str(settings["input"].get(key, "")).strip():
            raise SmokeTestConfigError("input.{} 경로가 비어 있습니다.".format(key))
    settings["scene"]["carrier_frequency_hz"] = _finite(
        settings["scene"]["carrier_frequency_hz"],
        "carrier_frequency_hz",
        positive=True,
    )
    coordinate = settings["scene"]["coordinate_system"]
    if coordinate.get("up_axis") != "+Z" or coordinate.get("units") != "meters":
        raise SmokeTestConfigError("Sionna 장면은 meter 단위의 +Z up이어야 합니다.")
    for semantic in ("floor", "ceiling", "walls"):
        if not str(settings["materials"][semantic].get("preset", "")).strip():
            raise SmokeTestConfigError("{} material preset이 비어 있습니다.".format(semantic))
    _position(settings["transmitter"]["position_m"], "transmitter.position_m")
    receivers = settings.get("receivers")
    if not isinstance(receivers, list) or not receivers:
        raise SmokeTestConfigError("receiver가 하나 이상 필요합니다.")
    names = [str(settings["transmitter"].get("name", ""))]
    for index, receiver in enumerate(receivers):
        _position(receiver.get("position_m"), "receivers[{}].position_m".format(index))
        names.append(str(receiver.get("name", "")))
    if any(not value for value in names) or len(names) != len(set(names)):
        raise SmokeTestConfigError("TX/RX 이름은 비어 있지 않고 서로 달라야 합니다.")
    placement = settings["placement"]
    if placement.get("mode") not in {"strict", "resolved"}:
        raise SmokeTestConfigError("placement.mode는 strict 또는 resolved여야 합니다.")
    _finite(placement["clearance_m"], "placement.clearance_m", positive=True)
    _finite(
        placement["minimum_device_separation_m"],
        "placement.minimum_device_separation_m",
        positive=True,
        allow_zero=True,
    )
    for section in ("path_test", "coverage"):
        values = settings[section]
        _positive_int(values["max_depth"], "{}.max_depth".format(section), allow_zero=True)
        for key in ("enable_los", "enable_reflection", "enable_refraction", "enable_diffraction", "enable_scattering"):
            if not isinstance(values[key], bool):
                raise SmokeTestConfigError("{}.{}는 true 또는 false여야 합니다.".format(section, key))
    _positive_int(settings["path_test"]["samples_per_src"], "path_test.samples_per_src")
    coverage = settings["coverage"]
    if coverage.get("enabled") is not True:
        raise SmokeTestConfigError("Phase 2-A에서는 coverage.enabled=true가 필요합니다.")
    _finite(coverage["z_height_m"], "coverage.z_height_m")
    _finite(coverage["margin_m"], "coverage.margin_m", positive=True, allow_zero=True)
    _finite(coverage["cell_size_m"], "coverage.cell_size_m", positive=True)
    _positive_int(coverage["max_cells"], "coverage.max_cells")
    _positive_int(coverage["samples_per_tx"], "coverage.samples_per_tx")
    validation = settings["validation"]
    _positive_int(validation["minimum_path_count_los_case"], "minimum_path_count_los_case")
    _finite(validation["maximum_los_distance_error_m"], "maximum_los_distance_error_m", positive=True)
    ratio = _finite(validation["minimum_valid_coverage_ratio"], "minimum_valid_coverage_ratio", positive=True)
    if ratio > 1.0:
        raise SmokeTestConfigError("minimum_valid_coverage_ratio는 1 이하여야 합니다.")
    for key, value in settings["output"].items():
        if not isinstance(value, bool):
            raise SmokeTestConfigError("output.{}는 true 또는 false여야 합니다.".format(key))
    return config


def load_config(path: Path) -> Dict[str, Any]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise SmokeTestConfigError("Smoke Test 설정을 찾을 수 없습니다: {}".format(source))
    try:
        config = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SmokeTestConfigError("Smoke Test 설정을 읽을 수 없습니다: {}".format(exc)) from exc
    if not isinstance(config, dict):
        raise SmokeTestConfigError("설정 최상위 값은 키와 값의 모음이어야 합니다.")
    return validate_config(config)
