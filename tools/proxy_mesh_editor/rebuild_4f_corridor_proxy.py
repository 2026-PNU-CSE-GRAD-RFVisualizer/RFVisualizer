"""PGSR 벽 분포와 사용자 도면을 결합해 4층 복도 Proxy Mesh를 재생성한다.

사용자 도면은 복도 위상(붉은 뒤집힌 ㄷ자와 파란 연결 복도)을 정하고,
수치 좌표는 PGSR 수직면 점군의 밀도 피크를 우선 사용한다.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Sequence, Tuple

import numpy as np

from tools.proxy_mesh_editor.io.metadata_io import read_json, write_json
from tools.proxy_mesh_editor.models import PlaneCandidate, PlaneRectangle


PROXY_HEIGHT_M = 2.6141115140447138
X_MAX_M = 11.80
Y_MAX_M = 16.342453098095195

# PGSR 수직면 점군을 metric 좌표로 변환한 뒤 2 cm bin으로 집계한 피크다.
X_RED_OUTER_M = 0.07
Y_RED_INNER_M = 13.33
X_BLUE_INNER_M = 3.29
Y_CONNECTOR_BOTTOM_M = 9.03

FOOTPRINT_XY: Tuple[Tuple[float, float], ...] = (
    (0.0, 0.0),
    (X_MAX_M, 0.0),
    (X_MAX_M, Y_MAX_M),
    (X_RED_OUTER_M, Y_MAX_M),
    (X_RED_OUTER_M, Y_RED_INNER_M),
    (X_BLUE_INNER_M, Y_RED_INNER_M),
    (X_BLUE_INNER_M, Y_CONNECTOR_BOTTOM_M),
    (0.0, Y_CONNECTOR_BOTTOM_M),
)

WALL_IDS: Tuple[str, ...] = (
    "metric_y_min",
    "metric_x_max",
    "metric_y_max",
    "metric_x_red_outer",
    "metric_y_red_inner",
    "metric_x_blue_inner",
    "metric_y_connector_bottom",
    "metric_x_min_lower",
)

BOUNDARY_EVIDENCE: Dict[str, Dict[str, Any]] = {
    "x_red_outer": {
        "coordinate_m": X_RED_OUTER_M,
        "vertical_surface_samples_near_peak": 796,
        "mesh_support": "strong",
        "role": "red_reverse_u_outer_left",
    },
    "y_red_inner": {
        "coordinate_m": Y_RED_INNER_M,
        "vertical_surface_samples_near_peak": 89,
        "mesh_support": "secondary",
        "role": "red_reverse_u_inner_bottom",
        "notes": "사용자 도면이 위상을 지정하고 PGSR의 보조 수직면 피크가 좌표를 보정함",
    },
    "x_blue_inner": {
        "coordinate_m": X_BLUE_INNER_M,
        "vertical_surface_samples_near_peak": 314,
        "mesh_support": "strong",
        "role": "blue_elevator_connector_left",
    },
    "y_connector_bottom": {
        "coordinate_m": Y_CONNECTOR_BOTTOM_M,
        "vertical_surface_samples_near_peak": 1666,
        "mesh_support": "very_strong",
        "role": "blue_connector_to_lower_corridor",
    },
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _polygon_area_and_centroid(
    points: Sequence[Tuple[float, float]],
) -> Tuple[float, np.ndarray]:
    xy = np.asarray(points, dtype=float)
    shifted = np.roll(xy, -1, axis=0)
    cross = xy[:, 0] * shifted[:, 1] - shifted[:, 0] * xy[:, 1]
    signed_twice_area = float(np.sum(cross))
    if abs(signed_twice_area) <= 1.0e-12:
        raise ValueError("4층 복도 footprint의 면적이 0입니다.")
    centroid = np.array(
        [
            np.sum((xy[:, 0] + shifted[:, 0]) * cross),
            np.sum((xy[:, 1] + shifted[:, 1]) * cross),
        ],
        dtype=float,
    ) / (3.0 * signed_twice_area)
    return abs(signed_twice_area) * 0.5, centroid


def _horizontal_candidate(candidate_id: str, z_m: float, semantic: str) -> PlaneCandidate:
    area, centroid_xy = _polygon_area_and_centroid(FOOTPRINT_XY)
    corners = np.asarray([[x, y, z_m] for x, y in FOOTPRINT_XY], dtype=float)
    rectangle = PlaneRectangle(
        origin=np.array([centroid_xy[0], centroid_xy[1], z_m], dtype=float),
        basis_u=np.array([1.0, 0.0, 0.0], dtype=float),
        basis_v=np.array([0.0, 1.0, 0.0], dtype=float),
        bounds_2d={
            "u_min": -float(centroid_xy[0]),
            "u_max": X_MAX_M - float(centroid_xy[0]),
            "v_min": -float(centroid_xy[1]),
            "v_max": Y_MAX_M - float(centroid_xy[1]),
        },
        corners=corners,
        width=X_MAX_M,
        height=Y_MAX_M,
        area=area,
    )
    return PlaneCandidate(
        candidate_id=candidate_id,
        plane_equation=np.array([0.0, 0.0, 1.0, -z_m], dtype=float),
        normal=np.array([0.0, 0.0, 1.0], dtype=float),
        centroid=np.array([centroid_xy[0], centroid_xy[1], z_m], dtype=float),
        inlier_count=0,
        raw_ransac_inlier_count=0,
        inlier_ratio=0.0,
        remaining_inlier_ratio=0.0,
        fitting_rmse=0.0,
        mean_absolute_distance=0.0,
        rectangle=rectangle,
        orientation="horizontal",
        suggested_semantic=semantic,
        semantic_confidence=1.0,
        semantic_reason="PGSR 벽 피크로 보정한 4층 복도 metric footprint",
        color=np.array([0.30, 0.60, 0.90], dtype=float),
        source_pass="plane_extraction",
        extraction_details={
            "provenance": "user_topology_plus_pgsr_vertical_surface_peaks",
            "footprint_xy_m": [list(point) for point in FOOTPRINT_XY],
        },
    )


def _wall_candidate(
    candidate_id: str,
    start_xy: Tuple[float, float],
    end_xy: Tuple[float, float],
    index: int,
) -> PlaneCandidate:
    start = np.asarray(start_xy, dtype=float)
    end = np.asarray(end_xy, dtype=float)
    tangent_xy = end - start
    length = float(np.linalg.norm(tangent_xy))
    if length <= 1.0e-12:
        raise ValueError("길이가 0인 벽 edge가 있습니다: {}".format(candidate_id))
    tangent_xy /= length
    # CCW footprint의 오른쪽이 바깥쪽이다.
    normal_xy = np.array([tangent_xy[1], -tangent_xy[0]], dtype=float)
    normal = np.array([normal_xy[0], normal_xy[1], 0.0], dtype=float)
    plane = np.array(
        [normal[0], normal[1], 0.0, -float(np.dot(normal_xy, start))],
        dtype=float,
    )
    midpoint_xy = 0.5 * (start + end)
    centroid = np.array(
        [midpoint_xy[0], midpoint_xy[1], 0.5 * PROXY_HEIGHT_M], dtype=float
    )
    corners = np.array(
        [
            [start[0], start[1], 0.0],
            [end[0], end[1], 0.0],
            [end[0], end[1], PROXY_HEIGHT_M],
            [start[0], start[1], PROXY_HEIGHT_M],
        ],
        dtype=float,
    )
    rectangle = PlaneRectangle(
        origin=centroid,
        basis_u=np.array([tangent_xy[0], tangent_xy[1], 0.0], dtype=float),
        basis_v=np.array([0.0, 0.0, 1.0], dtype=float),
        bounds_2d={
            "u_min": -0.5 * length,
            "u_max": 0.5 * length,
            "v_min": -0.5 * PROXY_HEIGHT_M,
            "v_max": 0.5 * PROXY_HEIGHT_M,
        },
        corners=corners,
        width=length,
        height=PROXY_HEIGHT_M,
        area=length * PROXY_HEIGHT_M,
    )
    return PlaneCandidate(
        candidate_id=candidate_id,
        plane_equation=plane,
        normal=normal,
        centroid=centroid,
        inlier_count=0,
        raw_ransac_inlier_count=0,
        inlier_ratio=0.0,
        remaining_inlier_ratio=0.0,
        fitting_rmse=0.0,
        mean_absolute_distance=0.0,
        rectangle=rectangle,
        orientation="vertical",
        suggested_semantic="wall",
        semantic_confidence=1.0,
        semantic_reason="PGSR 벽 피크로 보정한 4층 복도 footprint edge",
        color=np.array([0.30, 0.60, 0.90], dtype=float),
        source_pass="wall_extraction",
        extraction_details={
            "provenance": "user_topology_plus_pgsr_vertical_surface_peaks",
            "edge_index": index,
            "start_xy_m": start.tolist(),
            "end_xy_m": end.tolist(),
        },
    )


def _scene_metadata() -> Dict[str, Any]:
    bounds_min = np.array([0.0, 0.0, 0.0], dtype=float)
    bounds_max = np.array([X_MAX_M, Y_MAX_M, PROXY_HEIGHT_M], dtype=float)
    extent = bounds_max - bounds_min
    return {
        "up_vector": [0.0, 0.0, 1.0],
        "bounds": {
            "min": bounds_min.tolist(),
            "max": bounds_max.tolist(),
            "extent": extent.tolist(),
        },
        "estimated_extent": float(np.linalg.norm(extent)),
        "scale_status": "metric_pgsr_aligned",
    }


def _write_candidates(repo_root: Path, output_root: Path) -> None:
    timestamp = _utc_now()
    source = {
        "source_floorplan": str(
            (output_root / "source" / "IMG_2810.jpg").resolve()
        ),
        "source_revision_image": str(
            (output_root / "source" / "image-1.png").resolve()
        ),
        "source_pgsr_mesh": str(
            (repo_root / "PGSR/output/pnu_4f_corridor_v2/mesh/tsdf_fusion_post.ply").resolve()
        ),
        "vertical_wall_diagnostic": str(
            (
                repo_root
                / "scenes/pnu_4f_corridor/proxy_mesh/diagnostics/revision2_vertical_wall_density.png"
            ).resolve()
        ),
    }
    scene = _scene_metadata()
    plane_candidates = [
        _horizontal_candidate("metric_floor", 0.0, "floor"),
        _horizontal_candidate("metric_ceiling", PROXY_HEIGHT_M, "ceiling"),
    ]
    walls = [
        _wall_candidate(
            candidate_id,
            FOOTPRINT_XY[index],
            FOOTPRINT_XY[(index + 1) % len(FOOTPRINT_XY)],
            index,
        )
        for index, candidate_id in enumerate(WALL_IDS)
    ]
    common_algorithm = {
        "name": "rfvisualizer_pgsr_guided_4f_corridor_proxy",
        "version": "2.0",
    }
    candidate_dir = output_root / "metric_candidates"
    write_json(
        candidate_dir / "plane_candidates.json",
        {
            "schema_version": "1.0",
            "algorithm": common_algorithm,
            "created_at": timestamp,
            "input": source,
            "scene": scene,
            "revision": {
                "boundary_interpretation": "colored_strokes_are_corridor_outer_boundaries",
                "drawing_usage": "topology_only",
                "numeric_coordinate_source": "PGSR_vertical_surface_density_peaks",
                "boundary_evidence": BOUNDARY_EVIDENCE,
            },
            "plane_candidates": [candidate.to_dict() for candidate in plane_candidates],
        },
    )
    write_json(
        candidate_dir / "wall_candidates.json",
        {
            "schema_version": "1.0",
            "algorithm": common_algorithm,
            "created_at": timestamp,
            "input": source,
            "scene": scene,
            "candidate_ids": list(WALL_IDS),
            "wall_candidates": [candidate.to_dict() for candidate in walls],
            "floorplan_metric": {
                "footprint_xy_m": [list(point) for point in FOOTPRINT_XY],
                "height_m": PROXY_HEIGHT_M,
                "boundary_evidence": BOUNDARY_EVIDENCE,
            },
        },
    )


def _anchor_fit_from_calibration(calibration: Dict[str, Any]) -> Dict[str, Any]:
    geometry = calibration.get("geometry", {})
    existing = geometry.get("transform_anchor_fit")
    if isinstance(existing, dict):
        return dict(existing)
    keys = (
        "scene_bottom_corners_mapped_to_metric",
        "target_metric_bottom_corners",
        "corner_fit_errors_m",
        "maximum_corner_fit_error_m",
        "mean_corner_fit_error_m",
    )
    return {key: geometry[key] for key in keys if key in geometry}


def _remove_explicit_y_reflection(transform: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    forward = np.asarray(transform["T_metric_from_scene"], dtype=float)
    if float(np.linalg.det(forward[:3, :3])) > 0.0:
        return dict(transform), False
    y_flip = np.eye(4)
    y_flip[1, 1] = -1.0
    y_flip[1, 3] = Y_MAX_M
    forward = y_flip @ forward
    inverse = np.linalg.inv(forward)
    corrected = dict(transform)
    corrected.pop("reflection_reason", None)
    corrected.update(
        {
            "alignment_type": "orthogonal_similarity_proper_rotation",
            "T_metric_from_scene": forward.tolist(),
            "T_scene_from_metric": inverse.tolist(),
            "linear_determinant": float(np.linalg.det(forward[:3, :3])),
            "orthogonal_basis_determinant": 1.0,
            "origin_scene_coordinate": inverse[:3, 3].tolist(),
        }
    )
    if "source_y_axis" in corrected:
        corrected["source_y_axis"] = (-np.asarray(corrected["source_y_axis"])).tolist()
    return corrected, True


def _finalize_metadata(output_root: Path) -> None:
    room_path = output_root / "room" / "room_envelope.json"
    topology_path = output_root / "room" / "topology_report.json"
    calibration_path = output_root / "calibration.json"
    room = read_json(room_path)
    topology_document = read_json(topology_path)
    calibration = read_json(calibration_path)
    transform, parity_corrected = _remove_explicit_y_reflection(calibration["transform"])
    calibration["transform"] = transform
    matrix = np.asarray(transform["T_metric_from_scene"], dtype=float)
    inverse = np.asarray(transform["T_scene_from_metric"], dtype=float)
    round_trip = float(
        max(
            np.max(np.abs(matrix @ inverse - np.eye(4))),
            np.max(np.abs(inverse @ matrix - np.eye(4))),
        )
    )
    anchor_fit = _anchor_fit_from_calibration(calibration)
    if parity_corrected:
        for key in ("scene_bottom_corners_mapped_to_metric", "target_metric_bottom_corners"):
            if key in anchor_fit:
                points = np.asarray(anchor_fit[key], dtype=float)
                points[:, 1] = Y_MAX_M - points[:, 1]
                anchor_fit[key] = points.tolist()
    footprint = [list(point) + [0.0] for point in FOOTPRINT_XY]
    coordinate_contract = {
        "id": "pnu_4f_corridor",
        "unit": "meter",
        "origin": "green (0,0) point in IMG_2810.jpg",
        "up_axis": "+Z",
        "handedness": "right",
        "T_metric_from_scene": transform["T_metric_from_scene"],
        "T_scene_from_metric": transform["T_scene_from_metric"],
    }
    revision = {
        "boundary_interpretation": "colored_strokes_are_corridor_outer_boundaries",
        "interpretation_confirmed_by_user": True,
        "drawing_usage": "topology_only",
        "numeric_coordinate_source": "PGSR_vertical_surface_density_peaks",
        "red_reverse_u_included": True,
        "blue_elevator_connector_included": True,
        "footprint_xy_m": [list(point) for point in FOOTPRINT_XY],
        "boundary_evidence": BOUNDARY_EVIDENCE,
        "confidence": "medium",
        "limitations": [
            "PGSR Mesh의 누락·노이즈 때문에 실제 벽선과 수 cm 이상 차이가 날 수 있음",
            "Y=13.33 m 붉은 안쪽 경계는 사용자 도면과 약한 PGSR 보조 피크를 함께 사용함",
            "레이저 실측으로 검증되지 않음",
        ],
    }
    room.update(
        {
            "status": "provisional",
            "confidence": "medium",
            "bounds": _scene_metadata()["bounds"],
            "coordinate_system": coordinate_contract,
            "source_revision": revision,
            "transform": transform,
        }
    )
    write_json(room_path, room)

    calibration["created_at"] = _utc_now()
    calibration["status"] = "provisional"
    calibration["confidence"] = "medium"
    calibration["is_provisional"] = True
    calibration["warning_banner"] = (
        "PGSR MESH-GUIDED PROXY - NOT VALIDATED BY ON-SITE LASER MEASUREMENT"
    )
    calibration.setdefault("source", {}).update(
        {
            "revision_image": str((output_root / "source" / "image-1.png").resolve()),
            "pgsr_mesh": str(
                (
                    output_root.parents[3]
                    / "PGSR/output/pnu_4f_corridor_v2/mesh/tsdf_fusion_post.ply"
                ).resolve()
            ),
            "drawing_usage": "topology_only",
            "numeric_coordinate_source": "PGSR_vertical_surface_density_peaks",
        }
    )
    calibration["geometry"] = {
        "transform_anchor_fit": anchor_fit,
        "revised_proxy_footprint": revision,
        "proxy_floor_flattened": True,
        "proxy_height_m": PROXY_HEIGHT_M,
    }
    calibration["round_trip_error"] = round_trip
    calibration["validation_success"] = bool(
        topology_document["success"] and round_trip <= 1.0e-8
    )
    calibration["warnings"] = revision["limitations"]
    write_json(calibration_path, calibration)

    alignment = {
        "schema_version": "1.0",
        "created_at": _utc_now(),
        "success": bool(topology_document["success"] and round_trip <= 1.0e-8),
        "status": "provisional",
        "matrix_round_trip_error": round_trip,
        "transform_anchor_fit": anchor_fit,
        "footprint_revision": revision,
        "room_topology": topology_document["topology"],
        "room_geometry_validation": topology_document["geometry"],
        "coordinate_contract": coordinate_contract,
        "proxy_dimensions": {
            "x_min_m": 0.0,
            "x_max_m": X_MAX_M,
            "y_min_m": 0.0,
            "y_max_m": Y_MAX_M,
            "floor_z_m": 0.0,
            "ceiling_z_m": PROXY_HEIGHT_M,
            "bottom_corners": footprint,
        },
    }
    write_json(output_root / "alignment_validation.json", alignment)


def _copy_sources(repo_root: Path, output_root: Path, revision_image: Path | None) -> None:
    source_dir = output_root / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    floorplan_source = (
        repo_root
        / "scenes/pnu_4f_corridor/proxy_mesh/floorplan_aligned/source/IMG_2810.jpg"
    )
    floorplan_target = source_dir / "IMG_2810.jpg"
    if floorplan_source.is_file() and floorplan_source.resolve() != floorplan_target.resolve():
        shutil.copy2(floorplan_source, floorplan_target)
    if revision_image is not None:
        revision_image = revision_image.expanduser().resolve()
        if not revision_image.is_file():
            raise FileNotFoundError("수정 도면을 찾을 수 없습니다: {}".format(revision_image))
        revision_target = source_dir / "image-1.png"
        if revision_image != revision_target.resolve():
            shutil.copy2(revision_image, revision_target)
    elif not (source_dir / "image-1.png").is_file():
        raise FileNotFoundError("--revision-image가 필요합니다.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--revision-image",
        type=Path,
        help="붉은/파란 복도 경계를 표시한 사용자 도면. 첫 실행 뒤 source에 복사됩니다.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("scenes/pnu_4f_corridor/proxy_mesh/final_editor_proxy"),
    )
    parser.add_argument(
        "--envelope-config",
        type=Path,
        default=Path("scenes/pnu_4f_corridor/configs/proxy_mesh/plan_metric_envelope.yaml"),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    output_root = (
        args.output if args.output.is_absolute() else repo_root / args.output
    ).resolve()
    envelope_config = (
        args.envelope_config
        if args.envelope_config.is_absolute()
        else repo_root / args.envelope_config
    ).resolve()
    _copy_sources(repo_root, output_root, args.revision_image)
    _write_candidates(repo_root, output_root)
    command = [
        sys.executable,
        "-m",
        "tools.proxy_mesh_editor.main",
        "build-envelope",
        "--plane-candidates",
        str(output_root / "metric_candidates" / "plane_candidates.json"),
        "--wall-candidates",
        str(output_root / "metric_candidates" / "wall_candidates.json"),
        "--envelope-config",
        str(envelope_config),
        "--output",
        str(output_root / "room"),
    ]
    subprocess.run(command, cwd=repo_root, check=True)
    _finalize_metadata(output_root)
    print("4층 복도 Proxy Mesh 재생성 완료: {}".format(output_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
