"""Small GUI-only configuration; never mixed into scenario YAML."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict

import yaml


DEFAULTS = {
    "autosave": {"interval_seconds": 60, "command_interval": 10},
    "reference": {
        "opacity": 0.12,
        "wireframe": False,
        "point_size": 2.0,
        "point_cloud_visible": True,
        "proxy_mesh_visible": True,
        "pgsr_output_mesh_visible": True,
    },
    "navigation": {
        "initial_camera": {
            "mode": "origin",
            "eye_offset_m": [3.0, 3.0, 2.2],
            "target_offset_m": [0.5, 0.5, 0.5],
        },
        "fps": {
            "enabled": True,
            "mouse_sensitivity_deg_per_pixel": 0.15,
            "maximum_pitch_deg": 85.0,
            "movement_speed_mps": 1.5,
            "sprint_multiplier": 3.0,
            "max_frame_delta_seconds": 0.05,
            "horizontal_only": False,
        }
    },
    "external_commands": {"sionna_environment": {"type": "conda", "name": "sionna"}},
}


def _merged(default: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = {}
    for key, value in default.items():
        result[key] = _merged(value, {}) if isinstance(value, dict) else value
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merged(result[key], value)
        else:
            result[key] = value
    return result


def _positive_finite(value: Any, label: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError("{}은 finite 양수여야 합니다.".format(label))
    return number


def _finite_vector3(value: Any, label: str) -> list:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError("{}은 숫자 3개의 목록이어야 합니다.".format(label))
    result = [float(item) for item in value]
    if not all(math.isfinite(item) for item in result):
        raise ValueError("{}은 finite 숫자여야 합니다.".format(label))
    return result


def load_editor_config(path: Path = None) -> Dict[str, Any]:
    if path is None:
        value = {}
    else:
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise ValueError("Editor config를 찾을 수 없습니다: {}".format(source))
        value = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Editor config는 mapping이어야 합니다.")
    result = _merged(DEFAULTS, value)
    environment = result.get("external_commands", {}).get("sionna_environment", {})
    if environment.get("type") not in {"conda", "current"}:
        raise ValueError("sionna_environment.type은 conda/current여야 합니다.")
    if environment.get("type") == "conda" and not environment.get("name"):
        raise ValueError("conda environment name이 비어 있습니다.")
    fps = result.get("navigation", {}).get("fps", {})
    initial_camera = result.get("navigation", {}).get("initial_camera", {})
    if initial_camera.get("mode") not in {"origin", "room"}:
        raise ValueError("navigation.initial_camera.mode는 origin/room이어야 합니다.")
    for key in ("eye_offset_m", "target_offset_m"):
        initial_camera[key] = _finite_vector3(
            initial_camera.get(key), "navigation.initial_camera.{}".format(key)
        )
    if initial_camera["eye_offset_m"] == initial_camera["target_offset_m"]:
        raise ValueError("초기 카메라 eye와 target은 서로 달라야 합니다.")
    if not isinstance(fps.get("enabled"), bool):
        raise ValueError("navigation.fps.enabled는 bool이어야 합니다.")
    if not isinstance(fps.get("horizontal_only"), bool):
        raise ValueError("navigation.fps.horizontal_only는 bool이어야 합니다.")
    for key in (
        "mouse_sensitivity_deg_per_pixel",
        "maximum_pitch_deg",
        "movement_speed_mps",
        "sprint_multiplier",
        "max_frame_delta_seconds",
    ):
        fps[key] = _positive_finite(fps.get(key), "navigation.fps.{}".format(key))
    if fps["maximum_pitch_deg"] >= 90.0:
        raise ValueError("navigation.fps.maximum_pitch_deg는 90 미만이어야 합니다.")
    reference = result.get("reference", {})
    reference["point_size"] = _positive_finite(
        reference.get("point_size"), "reference.point_size"
    )
    configured_reference = value.get("reference", {})
    legacy_mode = reference.get("display_mode")
    if legacy_mode is not None:
        if legacy_mode not in {"both", "point_cloud", "proxy_mesh"}:
            raise ValueError(
                "reference.display_mode는 both/point_cloud/proxy_mesh여야 합니다."
            )
        if "point_cloud_visible" not in configured_reference:
            reference["point_cloud_visible"] = legacy_mode in {
                "both",
                "point_cloud",
            }
        if "proxy_mesh_visible" not in configured_reference:
            reference["proxy_mesh_visible"] = legacy_mode in {
                "both",
                "proxy_mesh",
            }
    legacy_visible = reference.get("visible")
    if legacy_visible is not None:
        if not isinstance(legacy_visible, bool):
            raise ValueError("reference.visible은 bool이어야 합니다.")
        if "point_cloud_visible" not in configured_reference:
            reference["point_cloud_visible"] = legacy_visible
    for key in (
        "point_cloud_visible",
        "proxy_mesh_visible",
        "pgsr_output_mesh_visible",
    ):
        if not isinstance(reference.get(key), bool):
            raise ValueError("reference.{}는 bool이어야 합니다.".format(key))
    return result
