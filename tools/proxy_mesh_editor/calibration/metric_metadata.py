"""실제 크기 Room Envelope 메타데이터와 사람이 읽는 보고서를 생성한다."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import numpy as np


class MetricMetadataError(RuntimeError):
    """실제 크기 메타데이터나 보고서를 만들 수 없을 때 발생한다."""


def _polygon_signed_area(coordinates: np.ndarray) -> float:
    following = np.roll(coordinates, -1, axis=0)
    return float(0.5 * np.sum(coordinates[:, 0] * following[:, 1] - following[:, 0] * coordinates[:, 1]))


def build_metric_envelope_metadata(
    envelope: Dict[str, Any],
    metric_bottom: np.ndarray,
    metric_top: np.ndarray,
    metric_interior: np.ndarray,
    metric_planes: Dict[str, Any],
    validation: Dict[str, Any],
    calibration_summary: Dict[str, Any],
    source_paths: Dict[str, str],
    output_files: Dict[str, Any],
    created_at: str,
    algorithm_version: str,
) -> Dict[str, Any]:
    bottom = np.asarray(metric_bottom, dtype=float)
    top = np.asarray(metric_top, dtype=float)
    heights = top[:, 2] - bottom[:, 2]
    edge_lengths = [
        float(np.linalg.norm(bottom[(index + 1) % len(bottom)] - bottom[index]))
        for index in range(len(bottom))
    ]
    wall_objects = []
    source_walls = envelope.get("wall_objects", [])
    wall_centroids = validation["plane_validation"]["plane_centroids"]["walls"]
    for index, equation in enumerate(metric_planes["walls"]):
        source = source_walls[index] if index < len(source_walls) else {}
        wall_objects.append(
            {
                "object_name": source.get("object_name", "wall_{:03d}".format(index)),
                "candidate_id": source.get("candidate_id"),
                "metric_plane_equation": equation,
                "metric_centroid": wall_centroids[index],
                "bottom_corner_indices": [index, (index + 1) % len(bottom)],
                "top_corner_indices": [index, (index + 1) % len(bottom)],
            }
        )
    return {
        "schema_version": "1.0",
        "algorithm": {
            "name": "rfvisualizer_metric_room_envelope",
            "version": algorithm_version,
        },
        "created_at": created_at,
        "status": calibration_summary["status"],
        "confidence": calibration_summary["confidence"],
        "is_provisional": calibration_summary["is_provisional"],
        "warning_banner": calibration_summary["warning_banner"],
        "source": source_paths,
        "coordinate_system": {
            "unit": "meter",
            "origin": "configured envelope bottom corner",
            "up_axis": "+Z",
            "handedness": "right",
            "T_metric_from_scene": calibration_summary["T_metric_from_scene"],
            "T_scene_from_metric": calibration_summary["T_scene_from_metric"],
        },
        "bottom_corners": bottom.tolist(),
        "top_corners": top.tolist(),
        "interior_point": np.asarray(metric_interior, dtype=float).tolist(),
        "plane_centroids": validation["plane_validation"]["plane_centroids"],
        "normalized_plane_equations": metric_planes,
        "bounds": validation["metric_bounds"],
        "surface_area_square_meters": validation["scale_geometry_validation"][
            "metric_surface_area"
        ],
        "signed_volume_cubic_meters": validation["scale_geometry_validation"][
            "metric_signed_volume"
        ],
        "absolute_volume_cubic_meters": validation["scale_geometry_validation"][
            "metric_absolute_volume"
        ],
        "floor_ceiling_height": float(np.mean(heights)),
        "height_statistics_meters": {
            "minimum": float(np.min(heights)),
            "maximum": float(np.max(heights)),
            "mean": float(np.mean(heights)),
            "values": heights.tolist(),
        },
        "polygon": {
            "bottom_xy_coordinates_meters": bottom[:, :2].tolist(),
            "ceiling_xy_coordinates_meters": top[:, :2].tolist(),
            "bottom_projected_signed_area_square_meters": _polygon_signed_area(bottom[:, :2]),
            "edge_lengths_meters": edge_lengths,
            "winding": "counter_clockwise_from_positive_z",
        },
        "mesh_summary": {
            "vertex_count": validation["topology_validation"]["metric"]["vertex_count"],
            "triangle_count": validation["topology_validation"]["metric"]["triangle_count"],
        },
        "topology_summary": validation["topology_validation"]["metric"],
        "wall_objects": wall_objects,
        "output_files": output_files,
    }


def build_calibration_document(
    settings: Dict[str, Any],
    source_paths: Dict[str, str],
    source_topology: Dict[str, Any],
    scale_analysis: Dict[str, Any],
    transform_diagnostics: Dict[str, Any],
    validation: Dict[str, Any],
    metric_bottom: np.ndarray,
    metric_top: np.ndarray,
    output_files: Dict[str, Any],
    warnings: List[str],
    created_at: str,
    algorithm_version: str,
) -> Dict[str, Any]:
    is_provisional = settings["status"] == "provisional"
    heights = np.asarray(metric_top)[:, 2] - np.asarray(metric_bottom)[:, 2]
    return {
        "schema_version": "1.0",
        "algorithm": {
            "name": "rfvisualizer_provisional_metric_calibration",
            "version": algorithm_version,
        },
        "created_at": created_at,
        "status": settings["status"],
        "confidence": settings["confidence"],
        "is_provisional": is_provisional,
        "warning_banner": (
            "PROVISIONAL METRIC CALIBRATION - NOT VALIDATED BY ON-SITE MEASUREMENT"
            if is_provisional
            else "MEASURED METRIC CALIBRATION"
        ),
        "source": {
            **source_paths,
            "topology_summary": source_topology,
        },
        "scale": {
            "method": scale_analysis["recommended_estimator"],
            "uniform_scale_only": True,
            "references": scale_analysis["references"],
            "individual_reference_scales": {
                item["name"]: item["individual_meters_per_scene_unit"]
                for item in scale_analysis["references"]
            },
            "resolved_meters_per_scene_unit": scale_analysis[
                "recommended_meters_per_scene_unit"
            ],
            "reference_spread": scale_analysis["relative_spread"],
            "spread_status": scale_analysis["spread_status"],
            "reference_residuals": scale_analysis["recommended_reference_residuals"],
        },
        "source_up_vector": transform_diagnostics["source_z_axis"],
        "target_up_vector": [0.0, 0.0, 1.0],
        "transform": transform_diagnostics,
        "geometry": {
            "source_bounds": validation["source_bounds"],
            "metric_bounds": validation["metric_bounds"],
            "source_surface_area": validation["scale_geometry_validation"]["source_surface_area"],
            "metric_surface_area": validation["scale_geometry_validation"]["metric_surface_area"],
            "expected_metric_surface_area": validation["scale_geometry_validation"][
                "expected_metric_surface_area"
            ],
            "source_absolute_volume": validation["scale_geometry_validation"][
                "source_absolute_volume"
            ],
            "metric_absolute_volume": validation["scale_geometry_validation"][
                "metric_absolute_volume"
            ],
            "expected_metric_absolute_volume": validation["scale_geometry_validation"][
                "expected_metric_absolute_volume"
            ],
            "metric_bottom_corners": np.asarray(metric_bottom).tolist(),
            "metric_top_corners": np.asarray(metric_top).tolist(),
            "metric_corner_heights": heights.tolist(),
            "metric_height_statistics": {
                "minimum": float(np.min(heights)),
                "mean": float(np.mean(heights)),
                "maximum": float(np.max(heights)),
            },
        },
        "validation_success": validation["validation_success"],
        "round_trip_error": validation["round_trip_validation"]["maximum_error"],
        "maximum_plane_residual": validation["plane_validation"]["maximum_plane_residual"],
        "warnings": warnings,
        "output_files": output_files,
    }


def write_calibration_report(path: Path, calibration: Dict[str, Any], validation: Dict[str, Any]) -> None:
    scale = calibration["scale"]
    transform = calibration["transform"]
    geometry = calibration["geometry"]
    lines = [
        "# Phase 1.5-C Metric Calibration 결과\n\n",
        "> **{}**\n\n".format(calibration["warning_banner"]),
        "## 결론\n\n",
        "- 전체 검증: **{}**\n".format("통과" if calibration["validation_success"] else "실패"),
        "- 상태: `{}` / 신뢰도: `{}`\n".format(calibration["status"], calibration["confidence"]),
        "- 단일 배율: `{:.12g} m/scene unit`\n".format(scale["resolved_meters_per_scene_unit"]),
        "- 기준 간 차이: `{:.4%}` (`{}`)\n\n".format(scale["reference_spread"], scale["spread_status"]),
        "## 표준 좌표 프레임\n\n",
        "- 원점 corner: `{}`\n".format(transform["origin_corner_index"]),
        "- X축 edge: `{}`\n".format(transform["x_axis_edge_indices"]),
        "- 회전 행렬식: `{:.12g}`\n".format(transform["rotation_determinant"]),
        "- 행렬 역변환 오차: `{:.6g}`\n".format(transform["matrix_inverse_error"]),
        "- 점 왕복 오차: `{:.6g}`\n\n".format(calibration["round_trip_error"]),
        "## 실제 크기 형상\n\n",
        "- Bounds min: `{}`\n".format(geometry["metric_bounds"]["min"]),
        "- Bounds max: `{}`\n".format(geometry["metric_bounds"]["max"]),
        "- 표면적: `{:.9g} m²`\n".format(geometry["metric_surface_area"]),
        "- 부피: `{:.9g} m³`\n".format(geometry["metric_absolute_volume"]),
        "- 높이 min/mean/max: `{:.9g} / {:.9g} / {:.9g} m`\n\n".format(
            geometry["metric_height_statistics"]["minimum"],
            geometry["metric_height_statistics"]["mean"],
            geometry["metric_height_statistics"]["maximum"],
        ),
        "## 기준별 오차\n\n",
    ]
    for residual in scale["reference_residuals"]:
        lines.append(
            "- `{}`: `{:+.9g} m` (`{:+.4%}`)\n".format(
                residual["reference_name"], residual["signed_error_m"], residual["relative_error"]
            )
        )
    lines.extend(
        [
            "\n## 검증\n\n",
            "- 최대 평면 오차: `{:.6g}`\n".format(calibration["maximum_plane_residual"]),
            "- 위상 보존: `{}`\n".format(validation["topology_validation"]["success"]),
            "- 면적·부피 배율 검증: `{}`\n".format(validation["scale_geometry_validation"]["success"]),
            "- OBJ 객체·그룹·재질·면 보존: `{}`\n\n".format(
                validation["obj_preservation_validation"]["success"]
            ),
            "## 경고\n\n",
        ]
    )
    for warning in calibration["warnings"]:
        lines.append("- {}\n".format(warning))
    lines.append("\n## 생성 파일\n\n")
    for name, value in calibration["output_files"].items():
        lines.append("- `{}`: `{}`\n".format(name, value))
    output = Path(path)
    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        temporary.write_text("".join(lines), encoding="utf-8")
        temporary.replace(output)
    except OSError as exc:
        raise MetricMetadataError("Calibration 보고서를 저장할 수 없습니다: {}".format(exc)) from exc
