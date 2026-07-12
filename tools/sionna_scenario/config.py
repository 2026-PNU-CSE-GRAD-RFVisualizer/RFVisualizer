"""Phase 2-B scenario and A/B experiment configuration loading."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import yaml


class ScenarioConfigError(ValueError):
    """Raised when a Phase 2-B YAML document is invalid."""


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUPPORTED_MATERIAL_CATEGORIES = {"concrete", "wood", "metal", "glass"}


def _load_yaml(path: Path) -> Dict[str, Any]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ScenarioConfigError("설정 파일을 찾을 수 없습니다: {}".format(source))
    try:
        document = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ScenarioConfigError("YAML을 읽을 수 없습니다: {}".format(exc)) from exc
    if not isinstance(document, dict):
        raise ScenarioConfigError("YAML 최상위 값은 키와 값의 모음이어야 합니다.")
    document = deepcopy(document)
    document["_source_path"] = str(source)
    return document


def resolve_project_path(value: Any, field: str, require_file: bool = True) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ScenarioConfigError("{} 경로가 비어 있습니다.".format(field))
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path = path.resolve()
    if require_file and not path.is_file():
        raise ScenarioConfigError("{} 파일을 찾을 수 없습니다: {}".format(field, path))
    return path


def _finite(value: Any, field: str, minimum: float = None) -> float:
    if isinstance(value, bool):
        raise ScenarioConfigError("{}는 숫자여야 합니다.".format(field))
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ScenarioConfigError("{}는 숫자여야 합니다.".format(field)) from exc
    if not np.isfinite(number) or (minimum is not None and number < minimum):
        suffix = "이고 {} 이상".format(minimum) if minimum is not None else ""
        raise ScenarioConfigError("{}는 유한한 숫자{}여야 합니다.".format(field, suffix))
    return number


def _integer(value: Any, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool):
        raise ScenarioConfigError("{}는 정수여야 합니다.".format(field))
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ScenarioConfigError("{}는 정수여야 합니다.".format(field)) from exc
    try:
        exact = float(value) == float(number)
    except (TypeError, ValueError, OverflowError):
        exact = False
    if number < minimum or not exact:
        raise ScenarioConfigError("{}는 {} 이상의 정수여야 합니다.".format(field, minimum))
    return number


def _require_bool(mapping: Dict[str, Any], key: str, field: str) -> bool:
    value = mapping.get(key)
    if not isinstance(value, bool):
        raise ScenarioConfigError("{}.{}는 true 또는 false여야 합니다.".format(field, key))
    return value


def _validate_status(value: Dict[str, Any], field: str) -> None:
    if value.get("status") != "provisional":
        raise ScenarioConfigError("{} status는 provisional이어야 합니다.".format(field))
    if value.get("physically_validated") is not False:
        raise ScenarioConfigError("{} physically_validated는 false여야 합니다.".format(field))


def _obstacle_identity(obstacle: Dict[str, Any], index: int) -> str:
    value = obstacle.get("id")
    if not isinstance(value, str) or not value.strip():
        raise ScenarioConfigError("obstacles[{}].id가 비어 있습니다.".format(index))
    return value.strip()


def _validate_obstacle_metadata(obstacle: Dict[str, Any], index: int) -> None:
    field = "obstacles[{}]".format(index)
    _require_bool(obstacle, "enabled", field)
    for key in ("semantic_class", "purpose", "confidence"):
        if not isinstance(obstacle.get(key), str) or not obstacle[key].strip():
            raise ScenarioConfigError("{}.{}가 비어 있습니다.".format(field, key))
    if not isinstance(obstacle.get("physical_object"), bool):
        raise ScenarioConfigError("{}.physical_object는 true 또는 false여야 합니다.".format(field))
    if obstacle.get("purpose") == "validation_only":
        if obstacle.get("physical_object") is not False or obstacle.get("confidence") != "synthetic":
            raise ScenarioConfigError(
                "validation_only obstacle은 physical_object=false, confidence=synthetic이어야 합니다."
            )
    if not obstacle["enabled"]:
        return
    geometry = obstacle.get("geometry")
    if not isinstance(geometry, dict):
        raise ScenarioConfigError("{}.geometry가 필요합니다.".format(field))
    geometry_type = geometry.get("type")
    if geometry_type not in {"box", "thin_panel", "mesh"}:
        raise ScenarioConfigError("{}.geometry.type이 지원되지 않습니다.".format(field))
    material = obstacle.get("material")
    if not isinstance(material, dict):
        raise ScenarioConfigError("{}.material이 필요합니다.".format(field))
    category = material.get("category")
    preset = material.get("preset")
    if category is not None and preset is not None and category != preset:
        raise ScenarioConfigError(
            "{}.material category와 preset은 같은 Sionna ITU type이어야 합니다.".format(field)
        )
    category = category if category is not None else preset
    if category not in SUPPORTED_MATERIAL_CATEGORIES:
        raise ScenarioConfigError(
            "{}.material category는 {} 중 하나여야 합니다.".format(
                field, sorted(SUPPORTED_MATERIAL_CATEGORIES)
            )
        )
    source = material.get("source", "sionna_preset")
    if source != "sionna_preset":
        raise ScenarioConfigError("이번 단계는 sionna_preset material source만 지원합니다.")


def validate_scenario(document: Dict[str, Any]) -> Dict[str, Any]:
    if document.get("schema_version") != "1.0":
        raise ScenarioConfigError("Scenario schema_version은 1.0이어야 합니다.")
    scenario = document.get("scenario")
    if not isinstance(scenario, dict):
        raise ScenarioConfigError("scenario 설정이 필요합니다.")
    _validate_status(scenario, "scenario")
    scenario_id = scenario.get("id")
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        raise ScenarioConfigError("scenario.id가 비어 있습니다.")
    base = scenario.get("base_scene")
    if not isinstance(base, dict):
        raise ScenarioConfigError("scenario.base_scene이 필요합니다.")
    phase2a_config = resolve_project_path(
        base.get("phase2a_config"), "scenario.base_scene.phase2a_config"
    )
    obstacles = scenario.get("obstacles", [])
    if not isinstance(obstacles, list):
        raise ScenarioConfigError("scenario.obstacles는 목록이어야 합니다.")
    identifiers: List[str] = []
    for index, obstacle in enumerate(obstacles):
        if not isinstance(obstacle, dict):
            raise ScenarioConfigError("obstacles[{}]는 키와 값의 모음이어야 합니다.".format(index))
        identifiers.append(_obstacle_identity(obstacle, index))
        _validate_obstacle_metadata(obstacle, index)
    if len(identifiers) != len(set(identifiers)):
        raise ScenarioConfigError("Obstacle ID는 서로 달라야 합니다.")
    synthetic = scenario.get("synthetic_validation", False)
    if not isinstance(synthetic, bool):
        raise ScenarioConfigError("scenario.synthetic_validation은 true 또는 false여야 합니다.")
    enabled = [value for value in obstacles if value.get("enabled")]
    if synthetic and not any(value.get("purpose") == "validation_only" for value in enabled):
        raise ScenarioConfigError("synthetic_validation scenario에는 활성 validation_only obstacle이 필요합니다.")
    scenario["_phase2a_config_path"] = str(phase2a_config)
    return document


def load_scenario(path: Path) -> Dict[str, Any]:
    return validate_scenario(_load_yaml(path))


def _validate_solver(solver: Dict[str, Any]) -> None:
    if solver.get("reuse_phase2a_settings") is not True:
        raise ScenarioConfigError("Phase 2-B solver.reuse_phase2a_settings는 true여야 합니다.")
    _finite(solver.get("carrier_frequency_hz"), "solver.carrier_frequency_hz", 1.0)
    _integer(solver.get("max_depth"), "solver.max_depth", 0)
    for key in (
        "enable_los",
        "enable_reflection",
        "enable_refraction",
        "enable_diffraction",
        "enable_scattering",
    ):
        _require_bool(solver, key, "solver")
    _integer(solver.get("path_samples"), "solver.path_samples", 1)
    _integer(solver.get("coverage_samples"), "solver.coverage_samples", 1)
    _integer(solver.get("path_seed"), "solver.path_seed", 0)
    _integer(solver.get("coverage_seed"), "solver.coverage_seed", 0)


def validate_experiment(document: Dict[str, Any]) -> Dict[str, Any]:
    if document.get("schema_version") != "1.0":
        raise ScenarioConfigError("Experiment schema_version은 1.0이어야 합니다.")
    experiment = document.get("experiment")
    if not isinstance(experiment, dict):
        raise ScenarioConfigError("experiment 설정이 필요합니다.")
    _validate_status(experiment, "experiment")
    if not isinstance(experiment.get("id"), str) or not experiment["id"].strip():
        raise ScenarioConfigError("experiment.id가 비어 있습니다.")
    baseline = experiment.get("baseline")
    if not isinstance(baseline, dict):
        raise ScenarioConfigError("experiment.baseline이 필요합니다.")
    baseline_path = resolve_project_path(baseline.get("scenario"), "baseline.scenario")
    variants = experiment.get("variants")
    if not isinstance(variants, list) or not variants:
        raise ScenarioConfigError("experiment.variants가 하나 이상 필요합니다.")
    variant_paths = []
    for index, value in enumerate(variants):
        if not isinstance(value, dict):
            raise ScenarioConfigError("variants[{}]가 유효하지 않습니다.".format(index))
        variant_paths.append(resolve_project_path(value.get("scenario"), "variants[{}].scenario".format(index)))
    _validate_solver(experiment.get("solver", {}))
    comparison = experiment.get("comparison", {})
    if comparison.get("coverage_delta_unit") != "dB":
        raise ScenarioConfigError("comparison.coverage_delta_unit은 dB여야 합니다.")
    _finite(comparison.get("changed_cell_threshold_db"), "changed_cell_threshold_db", 0.0)
    _require_bool(comparison, "require_common_grid", "comparison")
    _require_bool(comparison, "require_common_valid_mask", "comparison")
    reproducibility = experiment.get("reproducibility", {})
    rerun = _require_bool(reproducibility, "rerun_baseline", "reproducibility")
    count = _integer(reproducibility.get("baseline_repeat_count"), "baseline_repeat_count", 1)
    if not rerun:
        raise ScenarioConfigError("Phase 2-B는 reproducibility.rerun_baseline=true가 필요합니다.")
    if count < 2:
        raise ScenarioConfigError("Baseline 재현성 검증에는 최소 두 번의 실행이 필요합니다.")
    experiment["_baseline_scenario_path"] = str(baseline_path)
    experiment["_variant_scenario_paths"] = [str(value) for value in variant_paths]
    return document


def load_experiment(path: Path) -> Dict[str, Any]:
    return validate_experiment(_load_yaml(path))


def public_document(document: Dict[str, Any]) -> Dict[str, Any]:
    """Remove loader-only absolute path annotations before exporting YAML/JSON."""

    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items() if not key.startswith("_")}
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    return clean(document)
