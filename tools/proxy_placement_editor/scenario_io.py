"""Loss-minimizing deterministic Phase 2-B YAML load/save."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

import yaml

from tools.sionna_scenario.config import validate_scenario
from tools.sionna_scenario.obstacle_schema import obstacles_from_document
from tools.sionna_smoke_test.io_utils import atomic_write_text


class ScenarioIOError(ValueError):
    pass


class StableDumper(yaml.SafeDumper):
    pass


def _represent_float(dumper: yaml.Dumper, value: float):
    return dumper.represent_scalar(
        "tag:yaml.org,2002:float", format(float(value), ".9f")
    )


StableDumper.add_representer(float, _represent_float)


def load_editor_scenario(path: Path) -> Dict[str, Any]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ScenarioIOError("Scenario YAML을 찾을 수 없습니다: {}".format(source))
    try:
        document = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ScenarioIOError(
            "Scenario YAML을 읽을 수 없습니다: {}".format(exc)
        ) from exc
    if not isinstance(document, dict):
        raise ScenarioIOError("Scenario YAML 최상위 값은 mapping이어야 합니다.")
    validate_editor_document(document, source)
    return document


def validate_editor_document(
    document: Dict[str, Any], source_path: Path = None
) -> None:
    checked = validate_scenario(deepcopy(document))
    obstacles_from_document(checked, source_path=source_path)


def with_authoring_metadata(document: Dict[str, Any]) -> Dict[str, Any]:
    result = deepcopy(document)
    scenario = result.setdefault("scenario", {})
    scenario.setdefault("confidence", "low")
    provenance = scenario.setdefault("provenance", {})
    provenance.setdefault("authoring_method", "interactive_proxy_placement")
    provenance.setdefault("metric_calibration_status", "provisional")
    provenance.setdefault("on_site_measurement_complete", False)
    return result


def dump_scenario(document: Dict[str, Any]) -> str:
    return yaml.dump(
        document,
        Dumper=StableDumper,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=120,
    )


def save_editor_scenario(
    document: Dict[str, Any], path: Path, add_provenance: bool = True
) -> Path:
    destination = Path(path).expanduser().resolve()
    value = with_authoring_metadata(document) if add_provenance else deepcopy(document)
    validate_editor_document(value, destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(destination, dump_scenario(value))
    return destination
