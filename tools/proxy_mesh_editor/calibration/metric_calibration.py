"""Phase 1.5-C 실제 크기 보정 전체 실행 흐름."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import numpy as np

from ..io.metadata_io import read_json, write_json
from .metric_exporter import export_metric_geometry
from .metric_metadata import (
    build_calibration_document,
    build_metric_envelope_metadata,
    write_calibration_report,
)
from .metric_transform import (
    build_metric_transform,
    transform_diagnostics,
    transform_points,
)
from .metric_validator import MetricValidationError, validate_metric_calibration
from .preview_exporter import load_obj_geometry
from .scale_analysis import analyze_scale_references


def resolve_scale_analysis(settings: Dict[str, Any]) -> Dict[str, Any]:
    references = []
    for source in settings["scale"]["references"]:
        reference = dict(source)
        reference["assumed_real_distance_m"] = float(source["real_distance_m"])
        references.append(reference)
    validation = settings["validation"]
    analysis_settings = {
        "supported_estimators": [
            "arithmetic_mean_of_ratios",
            "weighted_mean_of_ratios",
            "weighted_least_squares",
            "median_of_ratios",
        ],
        "recommended_estimator": settings["scale"]["method"],
        "warning_relative_spread": validation["maximum_reference_spread_warning"],
        "failure_relative_spread": validation["maximum_reference_spread_failure"],
    }
    analysis = analyze_scale_references(references, analysis_settings)
    if analysis["spread_status"] == "failure":
        raise MetricValidationError(
            "Scale reference spread가 failure 기준을 넘어 실제 크기 변환을 중단합니다."
        )
    for reference in analysis["references"]:
        reference.pop("assumed_real_distance_m", None)
    return analysis


def run_metric_calibration(
    envelope_json_path: Path,
    envelope_obj_path: Path,
    config_path: Path,
    config: Dict[str, Any],
    output_directory: Path,
    algorithm_version: str,
    created_at: str,
) -> Dict[str, Any]:
    envelope_json = Path(envelope_json_path).expanduser().resolve()
    envelope_obj = Path(envelope_obj_path).expanduser().resolve()
    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    envelope = read_json(envelope_json)
    geometry = load_obj_geometry(envelope_obj)
    settings = config["metric_calibration"]
    scale_analysis = resolve_scale_analysis(settings)
    transform = build_metric_transform(
        envelope,
        settings["coordinate_frame"],
        scale_analysis["recommended_meters_per_scene_unit"],
        settings["validation"],
    )
    bottom = np.asarray(envelope["bottom_corners"], dtype=float)
    top = np.asarray(envelope["top_corners"], dtype=float)
    interior = np.asarray(envelope["interior_point"], dtype=float)
    metric_vertices = transform_points(geometry.vertices, transform)
    metric_bottom = transform_points(bottom, transform)
    metric_top = transform_points(top, transform)
    metric_interior = transform_points(interior, transform)
    exported = export_metric_geometry(
        envelope_obj,
        geometry,
        metric_vertices,
        metric_bottom,
        metric_top,
        transform,
        output,
        settings["output"],
        settings["status"],
    )
    validation, metric_planes, warnings = validate_metric_calibration(
        envelope,
        geometry.vertices,
        geometry.faces,
        metric_vertices,
        metric_bottom,
        metric_top,
        metric_interior,
        transform,
        scale_analysis,
        exported["obj_preservation"],
        settings,
    )
    paths = {
        **exported["files"],
        "metric_envelope_json": str((output / "room_envelope_metric.json").resolve()),
        "calibration_json": str((output / "calibration.json").resolve()),
        "calibration_report": str((output / "calibration_report.md").resolve()),
        "calibration_validation_json": str((output / "calibration_validation.json").resolve()),
    }
    source_paths = {
        "envelope_json": str(envelope_json),
        "envelope_obj": str(envelope_obj),
        "config": str(Path(config_path).expanduser().resolve()),
    }
    diagnostics = transform_diagnostics(transform)
    calibration_stub = {
        "status": settings["status"],
        "confidence": settings["confidence"],
        "is_provisional": settings["status"] == "provisional",
        "warning_banner": (
            "PROVISIONAL METRIC CALIBRATION - NOT VALIDATED BY ON-SITE MEASUREMENT"
            if settings["status"] == "provisional"
            else "MEASURED METRIC CALIBRATION"
        ),
        "T_metric_from_scene": diagnostics["T_metric_from_scene"],
        "T_scene_from_metric": diagnostics["T_scene_from_metric"],
    }
    metric_metadata = build_metric_envelope_metadata(
        envelope,
        metric_bottom,
        metric_top,
        metric_interior,
        metric_planes,
        validation,
        calibration_stub,
        source_paths,
        paths,
        created_at,
        algorithm_version,
    )
    calibration = build_calibration_document(
        settings,
        source_paths,
        envelope.get("topology_summary", {}),
        scale_analysis,
        diagnostics,
        validation,
        metric_bottom,
        metric_top,
        paths,
        warnings,
        created_at,
        algorithm_version,
    )
    if settings["output"]["write_metric_metadata"]:
        write_json(output / "room_envelope_metric.json", metric_metadata)
    write_json(output / "calibration.json", calibration)
    write_json(output / "calibration_validation.json", validation)
    write_calibration_report(output / "calibration_report.md", calibration, validation)
    return {
        "calibration": calibration,
        "validation": validation,
        "metric_envelope": metric_metadata,
        "axis_preview": exported["axis_preview"],
    }
