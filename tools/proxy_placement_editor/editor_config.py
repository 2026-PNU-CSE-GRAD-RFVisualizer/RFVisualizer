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
        "visible": True,
    },
    "navigation": {
        "fps": {
            "enabled": True,
            "movement_speed_mps": 1.5,
            "sprint_multiplier": 3.0,
            "max_frame_delta_seconds": 0.05,
            "horizontal_only": True,
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
    if not isinstance(fps.get("enabled"), bool):
        raise ValueError("navigation.fps.enabled는 bool이어야 합니다.")
    if not isinstance(fps.get("horizontal_only"), bool):
        raise ValueError("navigation.fps.horizontal_only는 bool이어야 합니다.")
    for key in (
        "movement_speed_mps",
        "sprint_multiplier",
        "max_frame_delta_seconds",
    ):
        fps[key] = _positive_finite(fps.get(key), "navigation.fps.{}".format(key))
    return result
