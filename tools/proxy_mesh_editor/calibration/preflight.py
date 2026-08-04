"""Calibration Preflight 전체 진단과 산출물 생성을 조정한다."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import numpy as np

from ..io.metadata_io import read_json, write_json
from .frame_analysis import analyze_frame_candidates
from .orientation_analysis import (
    analyze_envelope_orientation,
    proper_rotation_between,
    rotation_validation,
)
from .preview_exporter import (
    load_obj_geometry,
    topology_preservation_report,
    write_axis_gizmo_ply,
    write_rotation_only_obj,
    write_rotation_only_ply,
)
from .report import write_metric_calibration_draft, write_preflight_markdown
from .scale_analysis import analyze_scale_references, write_scale_analysis_csv


class CalibrationPreflightError(ValueError):
    """Preflight 입력이나 필수 진단 결과가 유효하지 않을 때 발생한다."""


def run_preflight(
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
    settings = config["calibration_preflight"]
    validation = settings["validation"]

    orientation = analyze_envelope_orientation(
        envelope, float(validation["minimum_positive_height"])
    )
    target_up = np.asarray(settings["orientation"]["target_up"], dtype=float)
    rotation, rotation_diagnostics = proper_rotation_between(
        np.asarray(orientation["scene_up_vector"]), target_up
    )
    determinant_range = (
        float(settings["orientation"]["minimum_rotation_determinant"]),
        float(settings["orientation"]["maximum_rotation_determinant"]),
    )
    rotation_analysis = rotation_validation(
        rotation,
        geometry.vertices,
        rotation_diagnostics,
        validation,
        determinant_range,
    )
    scale = analyze_scale_references(
        settings["scale_references"], settings["scale_analysis"]
    )
    origin, x_axis, frame_warnings = analyze_frame_candidates(
        np.asarray(orientation["bottom_corners"]),
        np.asarray(orientation["scene_up_vector"]),
        tie_tolerance=float(validation["maximum_round_trip_error"]),
    )

    preview = settings["preview"]
    files: Dict[str, Any] = {}
    aligned_obj_path = output / "room_envelope_up_aligned.obj"
    if preview["write_rotation_only_obj"]:
        transformed_vertices = write_rotation_only_obj(
            geometry, rotation, aligned_obj_path
        )
        files["rotation_only_obj"] = str(aligned_obj_path.resolve())
    else:
        transformed_vertices = geometry.vertices @ rotation.T
        files["rotation_only_obj"] = None
    aligned_ply_path = output / "room_envelope_up_aligned.ply"
    if preview["write_rotation_only_ply"]:
        write_rotation_only_ply(transformed_vertices, geometry.faces, aligned_ply_path)
        files["rotation_only_ply"] = str(aligned_ply_path.resolve())
    else:
        files["rotation_only_ply"] = None
    axes_path = output / "coordinate_axes.ply"
    if preview["write_axis_gizmo_ply"]:
        axis_gizmo = write_axis_gizmo_ply(
            axes_path,
            np.asarray(orientation["scene_up_vector"]),
            target_up,
            np.asarray(orientation["bottom_corners"]),
            np.asarray(orientation["top_corners"]),
        )
        files["coordinate_axes_ply"] = str(axes_path.resolve())
    else:
        axis_gizmo = None
        files["coordinate_axes_ply"] = None

    topology_preservation = topology_preservation_report(
        geometry.vertices,
        transformed_vertices,
        geometry.faces,
        tolerance=float(validation["maximum_round_trip_error"]),
    )
    csv_path = output / "scale_analysis.csv"
    write_scale_analysis_csv(csv_path, scale)
    files["scale_analysis_csv"] = str(csv_path.resolve())
    draft_path = output / "metric_calibration_draft.yaml"
    report_path = output / "calibration_preflight_report.md"
    json_path = output / "calibration_preflight.json"
    files["metric_calibration_draft"] = str(draft_path.resolve())
    files["markdown_report"] = str(report_path.resolve())
    files["preflight_json"] = str(json_path.resolve())

    warnings = [
        "Scale references are estimated and must be replaced after on-site measurement."
    ]
    warnings.extend(frame_warnings)
    if scale["spread_status"] == "warning":
        warnings.append(
            "Scale reference spread가 warning 기준을 넘었습니다: {:.2%}".format(
                scale["relative_spread"]
            )
        )
    elif scale["spread_status"] == "failure":
        warnings.append(
            "Scale reference spread가 failure 기준을 넘어서 provisional scale을 적용하면 안 됩니다."
        )
    if orientation["orientation_status"] == "pass":
        warnings.append(orientation["viewer_convention_diagnosis"])

    source_topology = envelope.get("topology_summary", {})
    source_topology_valid = bool(source_topology.get("closed_manifold_success", False))
    preflight_success = bool(
        orientation["orientation_status"] == "pass"
        and rotation_analysis["proper_rotation_success"]
        and topology_preservation["topology_preserved"]
        and scale["spread_status"] != "failure"
        and source_topology_valid
    )
    write_metric_calibration_draft(
        draft_path,
        config,
        scale,
        orientation["scene_up_vector"],
        rotation_analysis["target_up"],
        origin,
        x_axis,
        warnings,
    )
    document: Dict[str, Any] = {
        "schema_version": "1.0",
        "algorithm": {
            "name": "rfvisualizer_metric_calibration_preflight",
            "version": algorithm_version,
        },
        "created_at": created_at,
        "source": {
            "envelope_json": str(envelope_json),
            "envelope_obj": str(envelope_obj),
            "envelope_topology_summary": source_topology,
            "envelope_geometry_validation": envelope.get("geometry_validation"),
            "envelope_interior_point": envelope.get("interior_point"),
            "envelope_normalized_wall_order": envelope.get("selected_candidates", {}).get(
                "normalized_ordered_walls"
            ),
        },
        "config_path": str(Path(config_path).expanduser().resolve()),
        "preflight_status": settings["status"],
        "confidence": settings["confidence"],
        "orientation_analysis": orientation,
        "rotation_analysis": rotation_analysis,
        "scale_analysis": scale,
        "frame_analysis": {
            "origin_candidate": origin,
            "x_axis_candidate": x_axis,
        },
        "rotation_only_topology_preservation": topology_preservation,
        "axis_gizmo": axis_gizmo,
        "preflight_success": preflight_success,
        "generated_files": files,
        "unresolved_warnings": warnings,
    }
    write_json(json_path, document)
    write_preflight_markdown(report_path, document)
    return document
