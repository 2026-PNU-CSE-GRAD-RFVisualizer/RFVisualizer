"""Run reproducible empty-room versus obstacle Sionna RT experiments."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List

import time

import numpy as np
import yaml

from tools.sionna_smoke_test.coordinate_bridge import CoordinateBridge
from tools.sionna_smoke_test.coverage_test import run_coverage_solver
from tools.sionna_smoke_test.environment import diagnose_environment
from tools.sionna_smoke_test.exporter import export_coverage
from tools.sionna_smoke_test.io_utils import atomic_write_text, write_json
from tools.sionna_smoke_test.main import configure_sionna_scene
from tools.sionna_smoke_test.path_test import arrays_from_paths, extract_path_records

from .config import load_scenario, public_document
from .coverage_comparator import compare_coverage, to_db
from .exporter import write_coverage_delta_csv, write_path_records
from .material_resolver import inspect_all_scene_materials
from .path_comparator import compare_paths, summarize_paths
from .preview import export_coverage_previews, export_path_previews
from .reproducibility import analyze_reproducibility
from .report import write_ab_report, write_phase2b_index
from .scenario_builder import PreparedScenario, build_scenario, prepare_scenario
from .scene_composer import annotate_runtime_objects


class ExperimentRunError(RuntimeError):
    """Raised when an A/B experiment cannot meet its validation contract."""


def _solver_settings(base: Dict[str, Any], experiment: Dict[str, Any]) -> Dict[str, Any]:
    settings = deepcopy(base)
    solver = experiment["solver"]
    settings["scene"]["carrier_frequency_hz"] = float(
        solver["carrier_frequency_hz"]
    )
    path = settings["path_test"]
    coverage = settings["coverage"]
    for target in (path, coverage):
        target["max_depth"] = int(solver["max_depth"])
        target["enable_los"] = bool(solver["enable_los"])
        target["enable_reflection"] = bool(solver["enable_reflection"])
        target["enable_refraction"] = bool(solver["enable_refraction"])
        target["enable_diffraction"] = bool(solver["enable_diffraction"])
        target["enable_scattering"] = bool(solver["enable_scattering"])
    path["samples_per_src"] = int(solver["path_samples"])
    path["seed"] = int(solver["path_seed"])
    coverage["samples_per_tx"] = int(solver["coverage_samples"])
    coverage["seed"] = int(solver["coverage_seed"])
    return settings


def _assert_common_setup(
    baseline: PreparedScenario, variant: PreparedScenario
) -> None:
    baseline_config = Path(baseline.scenario["_phase2a_config_path"]).resolve()
    variant_config = Path(variant.scenario["_phase2a_config_path"]).resolve()
    if baseline_config != variant_config:
        raise ExperimentRunError(
            "Baseline과 variant는 같은 Phase 2-A config를 사용해야 합니다."
        )
    baseline_input = baseline.settings["input"]
    variant_input = variant.settings["input"]
    if baseline_input != variant_input:
        raise ExperimentRunError("Baseline과 variant가 같은 Metric Room 입력을 사용하지 않습니다.")
    baseline_positions = [
        (value["kind"], value["name"], value["resolved_position_m"])
        for value in baseline.positions
    ]
    variant_positions = [
        (value["kind"], value["name"], value["resolved_position_m"])
        for value in variant.positions
    ]
    if baseline_positions != variant_positions:
        raise ExperimentRunError("Baseline과 variant의 TX/RX 위치가 다릅니다.")
    if baseline.obstacle_records:
        raise ExperimentRunError("Baseline scenario는 obstacle이 없는 empty room이어야 합니다.")
    if not variant.obstacle_records:
        raise ExperimentRunError("Variant scenario에는 활성 obstacle이 필요합니다.")
    if not variant.scenario.get("synthetic_validation", False) or not any(
        value.get("purpose") == "validation_only"
        for value in variant.obstacle_records
    ):
        raise ExperimentRunError(
            "Phase 2-B run-ab variant에는 synthetic validation_only obstacle이 필요합니다."
        )


def _solve_paths(scene: Any, settings: Dict[str, Any]) -> Dict[str, Any]:
    from sionna.rt import PathSolver

    options = settings["path_test"]
    solver = PathSolver()
    started = time.perf_counter()
    paths = solver(
        scene=scene,
        max_depth=int(options["max_depth"]),
        samples_per_src=int(options["samples_per_src"]),
        synthetic_array=bool(options["synthetic_array"]),
        los=bool(options["enable_los"]),
        specular_reflection=bool(options["enable_reflection"]),
        diffuse_reflection=bool(options["enable_scattering"]),
        refraction=bool(options["enable_refraction"]),
        diffraction=bool(options["enable_diffraction"]),
        edge_diffraction=False,
        seed=int(options["seed"]),
    )
    elapsed = time.perf_counter() - started
    records = extract_path_records(
        arrays_from_paths(paths),
        list(scene.transmitters.keys()),
        list(scene.receivers.keys()),
    )
    object_names = {
        int(value.object_id): name for name, value in scene.objects.items()
    }
    for record in records:
        record["interaction_object_names"] = [
            object_names.get(int(value), "unknown_object_{}".format(value))
            for value in record["interaction_object_ids"]
        ]
    return {
        "schema_version": "1.0",
        "status": "provisional",
        "physically_validated": False,
        "solver_options": {
            "max_depth": int(options["max_depth"]),
            "samples_per_src": int(options["samples_per_src"]),
            "seed": int(options["seed"]),
            "los": bool(options["enable_los"]),
            "specular_reflection": bool(options["enable_reflection"]),
            "refraction": bool(options["enable_refraction"]),
            "diffraction": bool(options["enable_diffraction"]),
            "diffuse_reflection": bool(options["enable_scattering"]),
            "synthetic_array": bool(options["synthetic_array"]),
        },
        "summary": summarize_paths(records),
        "object_id_to_name": {str(key): value for key, value in object_names.items()},
        "paths": records,
        "solve_time_seconds": elapsed,
    }


def _coverage_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "values": np.asarray(result["values"], dtype=float),
        "valid_mask": np.asarray(result["valid_mask"], dtype=bool),
        "inside_mask": np.asarray(result["inside_mask"], dtype=bool),
        "centers": np.asarray(result["centers"], dtype=float),
        "unit": "linear",
        "metadata": result["metadata"],
    }


def _run_once(
    prepared: PreparedScenario,
    manifest: Dict[str, Any],
    settings: Dict[str, Any],
    output: Path,
    annotate_manifest: bool,
) -> Dict[str, Any]:
    directory = Path(output)
    directory.mkdir(parents=True, exist_ok=True)
    scene, load_time = configure_sionna_scene(
        manifest["scene_xml"], settings, prepared.positions
    )
    runtime_manifest = (
        annotate_runtime_objects(manifest, scene, Path(manifest["scene_xml"]).parents[1])
        if annotate_manifest
        else manifest
    )
    materials = inspect_all_scene_materials(scene, runtime_manifest, prepared.materials)
    write_json(directory / "materials_resolved.json", materials)
    path_document = _solve_paths(scene, settings)
    path_files = write_path_records(
        directory / "paths" / "paths_all.json", path_document
    )
    coverage_result = run_coverage_solver(
        scene, settings, prepared.room, prepared.positions
    )
    bridge = CoordinateBridge.from_calibration(prepared.metric_scene.calibration)
    coverage_files = export_coverage(
        coverage_result, bridge, prepared.positions, directory
    )
    coverage = _coverage_payload(coverage_result)
    return {
        "paths": path_document,
        "coverage": coverage,
        "materials": materials,
        "manifest": runtime_manifest,
        "files": {"paths": path_files, "coverage": coverage_files},
        "performance": {
            "scene_load_seconds": load_time,
            "path_solve_seconds": path_document["solve_time_seconds"],
            "coverage_solve_seconds": coverage["metadata"]["solve_time_seconds"],
        },
    }


def _repeat_input(result: Dict[str, Any], solver: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "path_records": result["paths"]["paths"],
        "coverage": result["coverage"],
        "path_seed": int(solver["path_seed"]),
        "coverage_seed": int(solver["coverage_seed"]),
    }


def _receiver_paths(document: Dict[str, Any], receiver: str) -> List[Dict[str, Any]]:
    return [value for value in document["paths"] if value["receiver"] == receiver]


def _runtime_obstacle_ids(manifest: Dict[str, Any]) -> List[int]:
    return [
        int(value["runtime_object_id"])
        for value in manifest["objects"]
        if value.get("layer") == "proxy_obstacle"
    ]


def _comparison_exports(
    output: Path,
    baseline: Dict[str, Any],
    variant: Dict[str, Any],
    coverage_document: Dict[str, Any],
    prepared: PreparedScenario,
) -> Dict[str, str]:
    coverage_directory = Path(output) / "coverage"
    coverage_directory.mkdir(parents=True, exist_ok=True)
    baseline_db = to_db(baseline["coverage"]["values"], "linear")
    variant_db = to_db(variant["coverage"]["values"], "linear")
    common = (
        baseline["coverage"]["valid_mask"]
        & variant["coverage"]["valid_mask"]
        & baseline["coverage"]["inside_mask"]
        & variant["coverage"]["inside_mask"]
        & np.isfinite(baseline_db)
        & np.isfinite(variant_db)
    )
    delta = np.full(baseline_db.shape, np.nan, dtype=float)
    delta[common] = variant_db[common] - baseline_db[common]
    delta_npy = coverage_directory / "coverage_delta.npy"
    np.save(delta_npy, delta)
    delta_csv = write_coverage_delta_csv(
        coverage_directory / "coverage_delta.csv",
        baseline["coverage"]["centers"],
        baseline_db,
        variant_db,
        baseline["coverage"]["inside_mask"],
        baseline["coverage"]["valid_mask"],
        variant["coverage"]["valid_mask"],
        variant_inside=variant["coverage"]["inside_mask"],
    )
    write_json(coverage_directory / "coverage_comparison.json", coverage_document)
    images = export_coverage_previews(
        baseline["coverage"],
        variant["coverage"],
        prepared.obstacle_records,
        prepared.positions,
        coverage_directory,
    )
    return {
        "coverage_delta_npy": str(delta_npy.resolve()),
        "coverage_delta_csv": delta_csv,
        "coverage_comparison_json": str(
            (coverage_directory / "coverage_comparison.json").resolve()
        ),
        **images,
    }


def _validation_document(
    experiment_id: str,
    environment: Dict[str, Any],
    baseline: Dict[str, Any],
    variant: Dict[str, Any],
    reproducibility: Dict[str, Any],
    path_comparison: Dict[str, Any],
    rx_los_comparison: Dict[str, Any],
    coverage_comparison: Dict[str, Any],
    prepared_variant: PreparedScenario,
) -> Dict[str, Any]:
    baseline_rx = rx_los_comparison["baseline"]
    variant_rx = rx_los_comparison["variant"]
    obstacle_materials = [
        value
        for value in variant["materials"]["materials"]
        if value.get("layer") == "proxy_obstacle"
    ]
    runtime_obstacles = [
        value
        for value in variant["manifest"]["objects"]
        if value.get("layer") == "proxy_obstacle"
    ]
    checks = {
        "environment_available": environment.get("status") == "available",
        "room_envelope_unmodified": bool(
            variant["manifest"]["base_scene"]["room_envelope_modified"] is False
        ),
        "independent_obstacle_layer": bool(
            variant["manifest"]["object_layers_independent"]
        ),
        "scene_object_count_increased_by_obstacles": bool(
            variant["manifest"]["total_object_count"]
            - baseline["manifest"]["total_object_count"]
            == len(runtime_obstacles)
        ),
        "runtime_obstacle_shape_loaded": bool(
            runtime_obstacles
            and all(value.get("runtime_object_id") is not None for value in runtime_obstacles)
        ),
        "strict_material_resolution": bool(
            variant["materials"]["strict_resolution"]
            and variant["materials"]["fallback_policy"] == "none"
            and obstacle_materials
            and all(
                value["is_used"] and not value["fallback_used"]
                for value in obstacle_materials
            )
        ),
        "baseline_repeated": reproducibility["repeat_count"] >= 2,
        "baseline_reproducible_within_tolerance": bool(
            reproducibility["reproducible_within_tolerance"]
        ),
        "synthetic_blocker_geometry_valid": all(
            value["validation"]["success"]
            for value in prepared_variant.obstacle_records
        ),
        "synthetic_blocker_intersects_configured_los": all(
            value["validation"]["los"].get(
                "required_target_intersection", False
            )
            for value in prepared_variant.obstacle_records
            if value["purpose"] == "validation_only"
        ),
        "baseline_rx_los_exists": bool(baseline_rx["los_path_exists"]),
        "variant_rx_los_blocked": not bool(variant_rx["los_path_exists"]),
        "blocker_related_path_evidence": bool(
            rx_los_comparison["obstacle_evidence"]["blocker_related_change"]
        ),
        "path_configuration_changed": bool(
            path_comparison["path_configuration_changed"]
        ),
        "coverage_grid_matches": bool(
            coverage_comparison["grid_validation"]["matches"]
        ),
        "coverage_valid_mask_matches": bool(
            coverage_comparison["valid_mask_validation"]["matches"]
        ),
        "coverage_delta_finite": coverage_comparison["common_valid_cell_count"] > 0,
        "coverage_change_exceeds_repeat_noise": bool(
            coverage_comparison["ab_change_exceeds_noise_floor"]
        ),
        "coverage_has_nonzero_change": bool(
            coverage_comparison["maximum_absolute_delta_db"] > 0.0
        ),
        "coordinate_bridge_round_trip": bool(
            variant["manifest"]["coordinate_bridge_validation"]["success"]
        ),
        "provisional_marking": True,
        "physically_validated_false": True,
    }
    return {
        "schema_version": "1.0",
        "experiment_id": experiment_id,
        "status": "provisional",
        "physically_validated": False,
        "synthetic_validation": True,
        "checks": checks,
        "overall_success": all(checks.values()),
        "warnings": [
            "SYNTHETIC BLOCKER — VALIDATION ONLY",
            "PROVISIONAL SCALE — NOT PHYSICALLY VALIDATED",
            "Coverage values are solver A/B evidence, not measured RSSI accuracy.",
        ],
    }


def run_ab_experiment(document: Dict[str, Any], output: Path) -> Dict[str, Any]:
    experiment = document["experiment"]
    if len(experiment["_variant_scenario_paths"]) != 1:
        raise ExperimentRunError("현재 run-ab 명령은 한 번에 variant 하나를 비교합니다.")
    baseline_document = load_scenario(Path(experiment["_baseline_scenario_path"]))
    variant_document = load_scenario(Path(experiment["_variant_scenario_paths"][0]))
    baseline_prepared = prepare_scenario(baseline_document)
    variant_prepared = prepare_scenario(variant_document)
    _assert_common_setup(baseline_prepared, variant_prepared)
    settings = _solver_settings(baseline_prepared.settings, experiment)
    directory = Path(output).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    environment = diagnose_environment()
    write_json(directory / "environment.json", environment)
    if environment.get("status") != "available":
        raise ExperimentRunError(
            "Sionna RT 환경을 사용할 수 없습니다: {}".format(environment.get("reason"))
        )

    total_start = time.perf_counter()
    baseline_manifest = build_scenario(baseline_prepared, directory / "baseline")
    variant_manifest = build_scenario(variant_prepared, directory / "variant")
    repeat_count = int(experiment["reproducibility"]["baseline_repeat_count"])
    if not experiment["reproducibility"]["rerun_baseline"]:
        repeat_count = 1
    baseline_runs = []
    for index in range(repeat_count):
        result_directory = (
            directory / "baseline"
            if index == 0
            else directory / "baseline_repeat_{:02d}".format(index + 1)
        )
        baseline_runs.append(
            _run_once(
                baseline_prepared,
                baseline_manifest,
                settings,
                result_directory,
                annotate_manifest=index == 0,
            )
        )
    variant_run = _run_once(
        variant_prepared,
        variant_manifest,
        settings,
        directory / "variant",
        annotate_manifest=True,
    )
    if repeat_count < 2:
        raise ExperimentRunError("A/B 실행 전에 empty baseline을 최소 두 번 실행해야 합니다.")
    solver = experiment["solver"]
    comparison_started = time.perf_counter()
    reproducibility = analyze_reproducibility(
        [_repeat_input(value, solver) for value in baseline_runs],
        coverage_unit="linear",
        require_common_grid=experiment["comparison"]["require_common_grid"],
        require_common_valid_mask=experiment["comparison"][
            "require_common_valid_mask"
        ],
        coverage_tolerance_db=1.0e-4,
        path_tolerances={
            "path_distance_m": 1.0e-4,
            "delay_s": 1.0e-10,
            "amplitude_magnitude": 1.0e-8,
            "path_gain_linear": 1.0e-8,
            "path_gain_db": 1.0e-4,
            "interaction_point_displacement_m": 1.0e-4,
        },
    )
    write_json(directory / "reproducibility.json", reproducibility)
    baseline_first = baseline_runs[0]
    obstacle_ids = _runtime_obstacle_ids(variant_run["manifest"])
    path_comparison = compare_paths(
        baseline_first["paths"]["paths"],
        variant_run["paths"]["paths"],
        obstacle_object_ids=obstacle_ids,
        numerical_noise_floors=reproducibility["noise_floor"]["paths"],
    )
    rx_los_comparison = compare_paths(
        _receiver_paths(baseline_first["paths"], "rx_los"),
        _receiver_paths(variant_run["paths"], "rx_los"),
        obstacle_object_ids=obstacle_ids,
        numerical_noise_floors=reproducibility["noise_floor"]["paths"],
    )
    path_comparison["rx_los"] = rx_los_comparison
    write_json(directory / "path_comparison.json", path_comparison)
    coverage_comparison = compare_coverage(
        baseline_first["coverage"],
        variant_run["coverage"],
        baseline_unit="linear",
        variant_unit="linear",
        require_common_grid=experiment["comparison"]["require_common_grid"],
        require_common_valid_mask=experiment["comparison"][
            "require_common_valid_mask"
        ],
        changed_cell_threshold_db=float(
            experiment["comparison"]["changed_cell_threshold_db"]
        ),
        noise_floor_db=reproducibility["noise_floor"]["coverage_db"],
    )
    write_json(directory / "coverage_comparison.json", coverage_comparison)
    comparison_compute_seconds = time.perf_counter() - comparison_started
    comparison_export_started = time.perf_counter()
    comparison_files = _comparison_exports(
        directory,
        baseline_first,
        variant_run,
        coverage_comparison,
        variant_prepared,
    )
    preview_files = export_path_previews(
        variant_prepared.metric_scene,
        baseline_first["paths"]["paths"],
        variant_run["paths"]["paths"],
        variant_prepared.obstacle_records,
        variant_prepared.positions,
        directory / "previews",
    )
    comparison_export_seconds = time.perf_counter() - comparison_export_started
    validation = _validation_document(
        experiment["id"],
        environment,
        baseline_first,
        variant_run,
        reproducibility,
        path_comparison,
        rx_los_comparison,
        coverage_comparison,
        variant_prepared,
    )
    validation["performance"] = {
        "baseline_runs": [value["performance"] for value in baseline_runs],
        "variant": variant_run["performance"],
        "comparison_compute_seconds": comparison_compute_seconds,
        "comparison_export_seconds": comparison_export_seconds,
        "total_seconds_before_report": time.perf_counter() - total_start,
        "gpu_snapshot": environment.get("gpu"),
    }
    validation["files"] = {
        "environment_json": str((directory / "environment.json").resolve()),
        "reproducibility_json": str((directory / "reproducibility.json").resolve()),
        "path_comparison_json": str((directory / "path_comparison.json").resolve()),
        "coverage_comparison_json": str(
            (directory / "coverage_comparison.json").resolve()
        ),
        **comparison_files,
        **preview_files,
    }
    write_json(directory / "experiment_validation.json", validation)
    resolved = public_document(document)
    resolved["experiment"]["resolved_solver_settings"] = settings
    atomic_write_text(
        directory / "resolved_experiment.yaml",
        yaml.safe_dump(resolved, allow_unicode=True, sort_keys=False),
    )
    result = {
        "environment": environment,
        "baseline_prepared": baseline_prepared,
        "variant_prepared": variant_prepared,
        "baseline_runs": baseline_runs,
        "variant_run": variant_run,
        "reproducibility": reproducibility,
        "path_comparison": path_comparison,
        "coverage_comparison": coverage_comparison,
        "validation": validation,
        "output": directory,
    }
    report = write_ab_report(result, directory / "PHASE2B_AB_REPORT.md")
    validation["files"]["report_markdown"] = report
    if directory.parent.name == "experiments":
        phase_index = write_phase2b_index(
            result, directory.parent.parent / "PHASE2B_VALIDATION.md", report
        )
        validation["files"]["phase2b_validation_markdown"] = phase_index
    write_json(directory / "experiment_validation.json", validation)
    return result
