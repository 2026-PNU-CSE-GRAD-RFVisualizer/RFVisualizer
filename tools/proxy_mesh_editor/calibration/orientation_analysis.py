"""Room Envelope의 상하 관계와 +Z 정렬 proper rotation을 진단한다."""

from __future__ import annotations

from typing import Any, Dict, Tuple

import numpy as np


class OrientationAnalysisError(ValueError):
    """Up vector 또는 Envelope 상하 관계를 분석할 수 없을 때 발생한다."""


def normalize_direction(values: np.ndarray, field: str) -> np.ndarray:
    vector = np.asarray(values, dtype=float)
    if vector.shape != (3,) or not np.all(np.isfinite(vector)):
        raise OrientationAnalysisError("{}는 유한한 숫자 3개여야 합니다.".format(field))
    length = float(np.linalg.norm(vector))
    if length <= 1e-12:
        raise OrientationAnalysisError("{}는 영벡터일 수 없습니다.".format(field))
    return vector / length


def proper_rotation_between(
    source_direction: np.ndarray, target_direction: np.ndarray
) -> Tuple[np.ndarray, Dict[str, Any]]:
    source = normalize_direction(source_direction, "source_up")
    target = normalize_direction(target_direction, "target_up")
    cosine = float(np.clip(np.dot(source, target), -1.0, 1.0))
    if cosine >= 1.0 - 1e-12:
        axis = np.asarray([1.0, 0.0, 0.0])
        angle = 0.0
        rotation = np.eye(3)
    elif cosine <= -1.0 + 1e-12:
        basis = np.eye(3)
        seed = basis[int(np.argmin(np.abs(basis @ source)))]
        axis = np.cross(source, seed)
        axis = axis / np.linalg.norm(axis)
        angle = np.pi
        rotation = 2.0 * np.outer(axis, axis) - np.eye(3)
    else:
        cross = np.cross(source, target)
        sine = float(np.linalg.norm(cross))
        axis = cross / sine
        angle = float(np.arctan2(sine, cosine))
        skew = np.asarray(
            [
                [0.0, -axis[2], axis[1]],
                [axis[2], 0.0, -axis[0]],
                [-axis[1], axis[0], 0.0],
            ]
        )
        rotation = np.eye(3) + np.sin(angle) * skew + (1.0 - np.cos(angle)) * (
            skew @ skew
        )
    determinant = float(np.linalg.det(rotation))
    orthogonality_error = float(
        np.max(np.abs(rotation.T @ rotation - np.eye(3)))
    )
    alignment_error = float(np.linalg.norm(rotation @ source - target))
    return rotation, {
        "source_up": source.tolist(),
        "target_up": target.tolist(),
        "rotation_axis": axis.tolist(),
        "rotation_angle_deg": float(np.degrees(angle)),
        "rotation_matrix": rotation.tolist(),
        "determinant": determinant,
        "orthogonality_error": orthogonality_error,
        "up_alignment_error": alignment_error,
    }


def _normalized_plane(equation: Any, label: str) -> np.ndarray:
    model = np.asarray(equation, dtype=float)
    if model.shape != (4,) or not np.all(np.isfinite(model)):
        raise OrientationAnalysisError("{} 평면식이 유효하지 않습니다.".format(label))
    length = float(np.linalg.norm(model[:3]))
    if length <= 1e-12:
        raise OrientationAnalysisError("{} 평면의 법선 길이가 0입니다.".format(label))
    return model / length


def analyze_envelope_orientation(
    envelope: Dict[str, Any], minimum_positive_height: float
) -> Dict[str, Any]:
    up = normalize_direction(envelope.get("up_vector"), "scene up vector")
    bottom = np.asarray(envelope.get("bottom_corners"), dtype=float)
    top = np.asarray(envelope.get("top_corners"), dtype=float)
    if (
        bottom.ndim != 2
        or bottom.shape[1] != 3
        or top.shape != bottom.shape
        or len(bottom) < 3
        or not np.all(np.isfinite(bottom))
        or not np.all(np.isfinite(top))
    ):
        raise OrientationAnalysisError("bottom/top corner 배열이 유효하지 않습니다.")
    floor_center = np.mean(bottom, axis=0)
    ceiling_center = np.mean(top, axis=0)
    center_offset = float(np.dot(ceiling_center - floor_center, up))
    heights = np.einsum("ij,j->i", top - bottom, up)
    corner_records = []
    for index, height in enumerate(heights):
        corner_records.append(
            {
                "corner_index": index,
                "bottom_coordinate": bottom[index].tolist(),
                "top_coordinate": top[index].tolist(),
                "height_along_scene_up": float(height),
                "euclidean_distance": float(np.linalg.norm(top[index] - bottom[index])),
                "positive_height": bool(height > minimum_positive_height),
            }
        )

    all_positive = bool(np.all(heights > minimum_positive_height))
    all_negative = bool(np.all(heights < -minimum_positive_height))
    if center_offset > minimum_positive_height and all_positive:
        orientation_status = "pass"
        orientation_diagnosis = "geometry_internal_up_consistent"
        viewer_diagnosis = (
            "Geometry 내부 상하 관계는 정상입니다. MeshLab에서 뒤집혀 보인다면 "
            "viewer 축 convention과 scene up 축 차이일 가능성이 높습니다."
        )
    elif center_offset < -minimum_positive_height or all_negative:
        orientation_status = "failure"
        orientation_diagnosis = "scene_up_sign_suspect"
        viewer_diagnosis = (
            "scene up vector 부호가 반대이거나 floor/ceiling 선택이 뒤바뀌었을 가능성이 있습니다."
        )
    else:
        orientation_status = "failure"
        orientation_diagnosis = "corner_correspondence_or_geometry_suspect"
        viewer_diagnosis = (
            "일부 corner의 상하 관계가 일치하지 않습니다. Phase 1.5-B 결과를 다시 확인해야 합니다."
        )

    diagnosis_checks = {
        "geometry_internal_up_consistent": bool(
            center_offset > minimum_positive_height and all_positive
        ),
        "viewer_axis_convention_may_differ": bool(
            center_offset > minimum_positive_height and all_positive
        ),
        "scene_up_sign_suspect": bool(
            center_offset < -minimum_positive_height or all_negative
        ),
        "floor_ceiling_or_corner_correspondence_suspect": bool(
            not all_positive and not all_negative
        ),
    }

    equations = envelope.get("normalized_plane_equations", {})
    floor = _normalized_plane(equations.get("floor"), "floor")
    ceiling = _normalized_plane(equations.get("ceiling"), "ceiling")
    normal_cosine = float(np.clip(abs(np.dot(floor[:3], ceiling[:3])), 0.0, 1.0))
    floor_residuals = np.abs(bottom @ floor[:3] + floor[3])
    ceiling_residuals = np.abs(top @ ceiling[:3] + ceiling[3])
    return {
        "scene_up_vector": up.tolist(),
        "floor_center": floor_center.tolist(),
        "ceiling_center": ceiling_center.tolist(),
        "vertical_center_offset": center_offset,
        "corner_heights": corner_records,
        "all_corner_heights_positive": all_positive,
        "all_corner_heights_negative": all_negative,
        "orientation_status": orientation_status,
        "orientation_diagnosis": orientation_diagnosis,
        "diagnosis_checks": diagnosis_checks,
        "viewer_convention_diagnosis": viewer_diagnosis,
        "floor_plane": {
            "normalized_equation": floor.tolist(),
            "normal": floor[:3].tolist(),
            "absolute_normal_up_dot": float(abs(np.dot(floor[:3], up))),
            "corner_residuals": floor_residuals.tolist(),
            "maximum_corner_residual": float(np.max(floor_residuals)),
        },
        "ceiling_plane": {
            "normalized_equation": ceiling.tolist(),
            "normal": ceiling[:3].tolist(),
            "absolute_normal_up_dot": float(abs(np.dot(ceiling[:3], up))),
            "corner_residuals": ceiling_residuals.tolist(),
            "maximum_corner_residual": float(np.max(ceiling_residuals)),
        },
        "floor_ceiling_normal_angle_deg": float(np.degrees(np.arccos(normal_cosine))),
        "bottom_corners": bottom.tolist(),
        "top_corners": top.tolist(),
    }


def rotation_validation(
    rotation: np.ndarray,
    vertices: np.ndarray,
    diagnostics: Dict[str, Any],
    settings: Dict[str, Any],
    determinant_range: Tuple[float, float],
) -> Dict[str, Any]:
    points = np.asarray(vertices, dtype=float)
    round_trip = (points @ rotation.T) @ rotation
    round_trip_error = float(np.max(np.linalg.norm(round_trip - points, axis=1)))
    success = bool(
        determinant_range[0] <= diagnostics["determinant"] <= determinant_range[1]
        and diagnostics["up_alignment_error"]
        <= float(settings["maximum_up_alignment_error"])
        and diagnostics["orthogonality_error"]
        <= float(settings["maximum_orthogonality_error"])
        and round_trip_error <= float(settings["maximum_round_trip_error"])
    )
    return {
        **diagnostics,
        "round_trip_error": round_trip_error,
        "proper_rotation_success": success,
    }
