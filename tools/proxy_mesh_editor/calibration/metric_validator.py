"""실제 크기 변환의 좌표 프레임, 평면, 위상, 면적과 부피를 검증한다."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

import numpy as np

from ..envelope.validator import analyze_topology
from .metric_transform import (
    MetricTransform,
    inverse_transform_points,
    transform_plane,
    transform_points,
)


class MetricValidationError(ValueError):
    """실제 크기 결과가 안전 조건을 만족하지 않을 때 발생한다."""


TOPOLOGY_EQUAL_KEYS = (
    "vertex_count",
    "triangle_count",
    "boundary_edge_count",
    "non_manifold_edge_count",
    "connected_component_count",
    "euler_characteristic",
    "degenerate_triangle_count",
    "duplicate_face_count",
)


def _round_trip_report(
    groups: Dict[str, np.ndarray], transform: MetricTransform
) -> Dict[str, Any]:
    group_errors = {}
    maximum = 0.0
    for name, points in groups.items():
        values = np.asarray(points, dtype=float).reshape((-1, 3))
        restored = inverse_transform_points(transform_points(values, transform), transform)
        error = float(np.max(np.linalg.norm(restored - values, axis=1)))
        group_errors[name] = error
        maximum = max(maximum, error)
    return {"group_maximum_errors": group_errors, "maximum_error": maximum}


def _plane_geometry(
    envelope: Dict[str, Any], transform: MetricTransform, metric_bottom: np.ndarray, metric_top: np.ndarray
) -> Tuple[Dict[str, Any], np.ndarray]:
    equations = envelope.get("normalized_plane_equations", {})
    floor_source = np.asarray(equations.get("floor"), dtype=float)
    ceiling_source = np.asarray(equations.get("ceiling"), dtype=float)
    walls_source = [np.asarray(value, dtype=float) for value in equations.get("walls", [])]
    if len(walls_source) != len(metric_bottom):
        raise MetricValidationError("벽 평면 수와 corner 수가 일치하지 않습니다.")
    floor_metric = transform_plane(floor_source, transform)
    ceiling_metric = transform_plane(ceiling_source, transform)
    walls_metric = [transform_plane(value, transform) for value in walls_source]
    floor_residuals = np.abs(metric_bottom @ floor_metric[:3] + floor_metric[3])
    ceiling_residuals = np.abs(metric_top @ ceiling_metric[:3] + ceiling_metric[3])
    wall_records = []
    for index, model in enumerate(walls_metric):
        following = (index + 1) % len(metric_bottom)
        vertices = np.asarray(
            [metric_bottom[index], metric_bottom[following], metric_top[following], metric_top[index]]
        )
        residuals = np.abs(vertices @ model[:3] + model[3])
        wall_records.append(
            {
                "wall_index": index,
                "metric_equation": model.tolist(),
                "vertex_residuals": residuals.tolist(),
                "maximum_vertex_residual": float(np.max(residuals)),
                "metric_centroid": np.mean(vertices, axis=0).tolist(),
            }
        )
    reference_points = []
    for model in [floor_source, ceiling_source] + walls_source:
        normal = model[:3] / np.linalg.norm(model[:3])
        offset = float(model[3] / np.linalg.norm(model[:3]))
        reference_points.append(-offset * normal)
    report = {
        "metric_plane_equations": {
            "floor": floor_metric.tolist(),
            "ceiling": ceiling_metric.tolist(),
            "walls": [value.tolist() for value in walls_metric],
        },
        "plane_centroids": {
            "floor": np.mean(metric_bottom, axis=0).tolist(),
            "ceiling": np.mean(metric_top, axis=0).tolist(),
            "walls": [record["metric_centroid"] for record in wall_records],
        },
        "floor_vertex_residuals": floor_residuals.tolist(),
        "ceiling_vertex_residuals": ceiling_residuals.tolist(),
        "wall_validation": wall_records,
        "maximum_plane_residual": float(
            max(
                np.max(floor_residuals),
                np.max(ceiling_residuals),
                max(record["maximum_vertex_residual"] for record in wall_records),
            )
        ),
    }
    return report, np.asarray(reference_points)


def _bounds(points: np.ndarray) -> Dict[str, Any]:
    minimum = np.min(points, axis=0)
    maximum = np.max(points, axis=0)
    return {
        "min": minimum.tolist(),
        "max": maximum.tolist(),
        "extent": (maximum - minimum).tolist(),
        "diagonal": float(np.linalg.norm(maximum - minimum)),
    }


def validate_rotation_matrix(rotation: np.ndarray, settings: Dict[str, Any]) -> Dict[str, Any]:
    value = np.asarray(rotation, dtype=float)
    if value.shape != (3, 3) or not np.all(np.isfinite(value)):
        raise MetricValidationError("회전 행렬은 유한한 3×3 행렬이어야 합니다.")
    determinant = float(np.linalg.det(value))
    determinant_error = abs(determinant - 1.0)
    orthogonality_error = float(np.max(np.abs(value.T @ value - np.eye(3))))
    if determinant <= 0.0 or determinant_error > float(settings["maximum_rotation_determinant_error"]):
        raise MetricValidationError("음의 determinant 또는 reflection 회전은 허용하지 않습니다.")
    if orthogonality_error > float(settings["maximum_orthogonality_error"]):
        raise MetricValidationError("회전 행렬이 직교 행렬이 아닙니다.")
    return {
        "determinant": determinant,
        "determinant_error": determinant_error,
        "orthogonality_error": orthogonality_error,
    }


def validate_metric_calibration(
    envelope: Dict[str, Any],
    source_vertices: np.ndarray,
    faces: np.ndarray,
    metric_vertices: np.ndarray,
    metric_bottom: np.ndarray,
    metric_top: np.ndarray,
    metric_interior: np.ndarray,
    transform: MetricTransform,
    scale_analysis: Dict[str, Any],
    obj_preservation: Dict[str, Any],
    settings: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    validation = settings["validation"]
    source_interior = np.asarray(envelope["interior_point"], dtype=float)
    source_bottom = np.asarray(envelope["bottom_corners"], dtype=float)
    source_top = np.asarray(envelope["top_corners"], dtype=float)
    plane_report, plane_reference_points = _plane_geometry(
        envelope, transform, metric_bottom, metric_top
    )
    round_trip = _round_trip_report(
        {
            "vertices": source_vertices,
            "bottom_corners": source_bottom,
            "top_corners": source_top,
            "interior_point": source_interior[None, :],
            "plane_reference_points": plane_reference_points,
        },
        transform,
    )
    source_mesh = SimpleNamespace(
        vertices=np.asarray(source_vertices, dtype=float),
        faces=np.asarray(faces, dtype=int),
        interior_point=source_interior,
    )
    metric_mesh = SimpleNamespace(
        vertices=np.asarray(metric_vertices, dtype=float),
        faces=np.asarray(faces, dtype=int),
        interior_point=np.asarray(metric_interior, dtype=float),
    )
    topology_tolerance = min(
        float(validation["maximum_plane_residual"]),
        float(validation["maximum_round_trip_error"]),
    )
    source_topology = analyze_topology(source_mesh, topology_tolerance)
    metric_topology = analyze_topology(metric_mesh, topology_tolerance)
    topology_comparison = {
        key: {
            "source": source_topology[key],
            "metric": metric_topology[key],
            "match": source_topology[key] == metric_topology[key],
        }
        for key in TOPOLOGY_EQUAL_KEYS
    }
    face_indices_unchanged = bool(obj_preservation.get("face_indices_unchanged", True))
    signed_volume_sign_preserved = bool(
        np.sign(source_topology["signed_volume"]) == np.sign(metric_topology["signed_volume"])
    )
    topology_success = bool(
        all(value["match"] for value in topology_comparison.values())
        and face_indices_unchanged
        and signed_volume_sign_preserved
        and metric_topology["closed_manifold_success"]
    )

    expected_area = source_topology["surface_area"] * transform.scale**2
    expected_volume = source_topology["absolute_volume"] * transform.scale**3
    area_error = abs(metric_topology["surface_area"] - expected_area)
    volume_error = abs(metric_topology["absolute_volume"] - expected_volume)
    area_relative_error = area_error / max(expected_area, 1e-30)
    volume_relative_error = volume_error / max(expected_volume, 1e-30)
    scale_geometry_success = bool(
        area_relative_error <= float(validation["maximum_round_trip_error"])
        and volume_relative_error <= float(validation["maximum_round_trip_error"])
    )

    origin_metric = transform_points(transform.origin_scene, transform)
    target_up = np.asarray(settings["coordinate_frame"]["target_up"], dtype=float)
    target_up = target_up / np.linalg.norm(target_up)
    up_alignment_error = float(np.linalg.norm(transform.rotation @ transform.z_scene - target_up))
    start, end = transform.x_axis_edge
    source_edge = source_bottom[end] - source_bottom[start]
    projected_edge = source_edge - float(np.dot(source_edge, transform.z_scene)) * transform.z_scene
    metric_projected_edge = transform.scale * (transform.rotation @ projected_edge)
    projected_edge_alignment_error = float(np.linalg.norm(metric_projected_edge[1:]))
    metric_actual_edge = metric_bottom[end] - metric_bottom[start]
    coordinate_frame_success = bool(
        np.linalg.norm(origin_metric) <= float(validation["maximum_origin_error"])
        and up_alignment_error <= float(validation["maximum_axis_alignment_error"])
        and projected_edge_alignment_error <= float(validation["maximum_axis_alignment_error"])
        and metric_projected_edge[0] > 0.0
    )
    coordinate_frame = {
        "origin_metric_coordinate": origin_metric.tolist(),
        "origin_error": float(np.linalg.norm(origin_metric)),
        "up_alignment_error": up_alignment_error,
        "projected_x_edge_metric_vector": metric_projected_edge.tolist(),
        "projected_x_edge_alignment_error": projected_edge_alignment_error,
        "actual_selected_edge_metric_vector": metric_actual_edge.tolist(),
        "actual_edge_z_note": "실제 edge의 경사는 유지되므로 Z 성분이 있을 수 있습니다.",
        "right_handed_axis_error": float(
            np.linalg.norm(np.cross(transform.x_scene, transform.y_scene) - transform.z_scene)
        ),
        "success": coordinate_frame_success,
    }

    reference_errors = scale_analysis["recommended_reference_residuals"]
    maximum_reference_error = max(value["absolute_relative_error"] for value in reference_errors)
    scale_success = bool(
        maximum_reference_error <= float(validation["maximum_reference_relative_error"])
        and scale_analysis["relative_spread"]
        <= float(validation["maximum_reference_spread_failure"])
    )
    rotation = validate_rotation_matrix(transform.rotation, validation)
    plane_success = plane_report["maximum_plane_residual"] <= float(
        validation["maximum_plane_residual"]
    )
    round_trip_success = round_trip["maximum_error"] <= float(
        validation["maximum_round_trip_error"]
    )
    obj_success = bool(
        not settings["output"]["write_obj"]
        or obj_preservation.get("obj_structure_preserved", False)
    )
    validation_success = bool(
        scale_success
        and coordinate_frame_success
        and round_trip_success
        and topology_success
        and plane_success
        and scale_geometry_success
        and obj_success
    )
    warnings = []
    if settings["status"] == "provisional":
        warnings.append("PROVISIONAL METRIC CALIBRATION - NOT VALIDATED BY ON-SITE MEASUREMENT")
    if scale_analysis["relative_spread"] > float(validation["maximum_reference_spread_warning"]):
        warnings.append(
            "Scale reference spread가 warning 기준을 넘었습니다: {:.2%}".format(
                scale_analysis["relative_spread"]
            )
        )
    report = {
        "validation_success": validation_success,
        "scale_validation": {
            "maximum_reference_relative_error": maximum_reference_error,
            "allowed_maximum_reference_relative_error": validation[
                "maximum_reference_relative_error"
            ],
            "reference_spread": scale_analysis["relative_spread"],
            "spread_status": scale_analysis["spread_status"],
            "success": scale_success,
        },
        "rotation_validation": {**rotation, "success": True},
        "coordinate_frame_validation": coordinate_frame,
        "round_trip_validation": {**round_trip, "success": round_trip_success},
        "topology_validation": {
            "source": source_topology,
            "metric": metric_topology,
            "field_comparison": topology_comparison,
            "face_indices_unchanged": face_indices_unchanged,
            "signed_volume_sign_preserved": signed_volume_sign_preserved,
            "source_json_topology": envelope.get("topology_summary"),
            "success": topology_success,
        },
        "scale_geometry_validation": {
            "source_surface_area": source_topology["surface_area"],
            "metric_surface_area": metric_topology["surface_area"],
            "expected_metric_surface_area": expected_area,
            "surface_area_absolute_error": area_error,
            "surface_area_relative_error": area_relative_error,
            "source_signed_volume": source_topology["signed_volume"],
            "metric_signed_volume": metric_topology["signed_volume"],
            "source_absolute_volume": source_topology["absolute_volume"],
            "metric_absolute_volume": metric_topology["absolute_volume"],
            "expected_metric_absolute_volume": expected_volume,
            "absolute_volume_error": volume_error,
            "volume_relative_error": volume_relative_error,
            "success": scale_geometry_success,
        },
        "plane_validation": {**plane_report, "success": plane_success},
        "obj_preservation_validation": {**obj_preservation, "success": obj_success},
        "source_bounds": _bounds(np.asarray(source_vertices, dtype=float)),
        "metric_bounds": _bounds(np.asarray(metric_vertices, dtype=float)),
        "warnings": warnings,
    }
    metric_planes = plane_report["metric_plane_equations"]
    if not validation_success:
        failed = [
            name
            for name, success in (
                ("scale", scale_success),
                ("coordinate frame", coordinate_frame_success),
                ("round trip", round_trip_success),
                ("topology", topology_success),
                ("plane", plane_success),
                ("area/volume", scale_geometry_success),
                ("OBJ preservation", obj_success),
            )
            if not success
        ]
        raise MetricValidationError("실제 크기 보정 검증 실패: {}".format(", ".join(failed)))
    return report, metric_planes, warnings
