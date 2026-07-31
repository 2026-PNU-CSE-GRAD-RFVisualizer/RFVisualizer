"""실측 치수로 논문 실험용 기본 Metric Room Envelope를 만든다.

기존 PGSR Envelope는 천장 여유 높이와 표시용 정렬의 참고 자료일 뿐이다.
가로·깊이·바닥 높이차는 실험 Scene 계약의 현장 측정값을 우선한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Mapping, Sequence, Tuple

import numpy as np

from tools.proxy_mesh_editor.envelope.validator import analyze_topology
from tools.sionna_smoke_test.io_utils import atomic_write_text, write_json
from tools.sionna_smoke_test.metric_scene_loader import mesh_statistics

from .contracts import load_json, resolve_path, validate_scene_document


class ProxySceneError(ValueError):
    """실측 기본 Envelope를 안전하게 만들 수 없을 때 발생한다."""


FACES = np.asarray(
    [
        [3, 1, 0],
        [1, 3, 2],
        [7, 4, 5],
        [5, 6, 7],
        [0, 1, 5],
        [0, 5, 4],
        [1, 2, 6],
        [1, 6, 5],
        [2, 3, 7],
        [2, 7, 6],
        [3, 0, 4],
        [3, 4, 7],
    ],
    dtype=int,
)

OBJECTS: Tuple[Tuple[str, str, str, Tuple[int, int]], ...] = (
    ("floor_000", "floor", "floor", (0, 2)),
    ("ceiling_000", "ceiling", "ceiling", (2, 4)),
    ("wall_000", "wall", "wall", (4, 6)),
    ("wall_001", "wall", "wall", (6, 8)),
    ("wall_002", "wall", "wall", (8, 10)),
    ("wall_003", "wall", "wall", (10, 12)),
)


@dataclass(frozen=True)
class ProxyEnvelope:
    vertices: np.ndarray
    faces: np.ndarray
    bottom: np.ndarray
    top: np.ndarray
    interior: np.ndarray
    planes: Dict[str, Any]
    topology: Dict[str, Any]
    statistics: Dict[str, Any]
    calibration: Dict[str, Any]
    assumptions: Dict[str, Any]


def _array(value: Any, field: str, shape: Tuple[int, ...]) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.shape != shape or not np.all(np.isfinite(array)):
        raise ProxySceneError("{} 형식이 유효하지 않습니다.".format(field))
    return array


def _normalized_plane(points: Sequence[Sequence[float]]) -> List[float]:
    values = np.asarray(points, dtype=float)
    if values.shape[0] < 3 or values.shape[1:] != (3,):
        raise ProxySceneError("평면 계산에는 3차원 점이 세 개 이상 필요합니다.")
    origin = values[0]
    normal = None
    for first in range(1, len(values) - 1):
        candidate = np.cross(values[first] - origin, values[first + 1] - origin)
        length = float(np.linalg.norm(candidate))
        if length > 1.0e-12:
            normal = candidate / length
            break
    if normal is None:
        raise ProxySceneError("서로 일직선이 아닌 평면 점을 찾지 못했습니다.")
    offset = -float(np.dot(normal, origin))
    return [float(item) for item in normal] + [offset]


def _planes(bottom: np.ndarray, top: np.ndarray) -> Dict[str, Any]:
    walls = []
    wall_centroids = []
    for index in range(4):
        following = (index + 1) % 4
        quad = [bottom[index], bottom[following], top[following], top[index]]
        walls.append(_normalized_plane(quad))
        wall_centroids.append(np.mean(quad, axis=0).tolist())
    return {
        "equations": {
            "floor": _normalized_plane(bottom),
            "ceiling": _normalized_plane(top),
            "walls": walls,
        },
        "centroids": {
            "floor": np.mean(bottom, axis=0).tolist(),
            "ceiling": np.mean(top, axis=0).tolist(),
            "walls": wall_centroids,
        },
    }


def _anchored_affine_fit(
    source: np.ndarray,
    target: np.ndarray,
    anchor_index: int,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    if source.shape != target.shape or source.ndim != 2 or source.shape[1] != 3:
        raise ProxySceneError("기존 장면과 실험 장면의 대응점 형식이 유효하지 않습니다.")
    if anchor_index < 0 or anchor_index >= len(source):
        raise ProxySceneError("원점 anchor 대응점 번호가 범위를 벗어납니다.")
    source_anchor = source[anchor_index]
    target_anchor = target[anchor_index]
    source_relative = source - source_anchor
    target_relative = target - target_anchor
    coefficients, _, rank, _ = np.linalg.lstsq(
        source_relative, target_relative, rcond=None
    )
    if rank < 3:
        raise ProxySceneError("기존 장면과 실험 장면 사이 anchored affine fit의 rank가 부족합니다.")
    transform = np.eye(4, dtype=float)
    transform[:3, :3] = coefficients.T
    transform[:3, 3] = target_anchor - coefficients.T @ source_anchor
    linear_determinant = float(np.linalg.det(transform[:3, :3]))
    if abs(linear_determinant) <= 1.0e-12:
        raise ProxySceneError("기존 장면과 실험 장면 사이 affine transform이 역변환 불가능합니다.")
    predicted = source_relative @ coefficients + target_anchor
    errors = np.linalg.norm(predicted - target, axis=1)
    anchored_position = (
        transform @ np.asarray([*source_anchor, 1.0], dtype=float)
    )[:3]
    anchor_error = float(np.linalg.norm(anchored_position - target_anchor))
    if anchor_error > 1.0e-9:
        raise ProxySceneError("문 시작점 anchor를 실험 원점에 정확히 고정하지 못했습니다.")
    return transform, {
        "source_target_point_count": int(len(source)),
        "fit_rank": int(rank),
        "linear_determinant": linear_determinant,
        "anchor_correspondence_index": int(anchor_index),
        "anchor_source_position_m": source_anchor.tolist(),
        "anchor_target_position_m": target_anchor.tolist(),
        "anchor_resolved_position_m": anchored_position.tolist(),
        "anchor_error_m": anchor_error,
        "corner_fit_errors_m": errors.tolist(),
        "mean_corner_fit_error_m": float(np.mean(errors)),
        "maximum_corner_fit_error_m": float(np.max(errors)),
    }


def _reference_alignment(scene_document: Mapping[str, Any]) -> Tuple[np.ndarray, int]:
    try:
        alignment = scene_document["scene"]["proxy_scene"]["reference_alignment"]
    except (KeyError, TypeError) as exc:
        raise ProxySceneError(
            "scene.proxy_scene.reference_alignment 설정이 필요합니다."
        ) from exc
    if alignment.get("method") != "anchored_affine_corner_fit":
        raise ProxySceneError(
            "reference_alignment.method는 anchored_affine_corner_fit이어야 합니다."
        )
    order = np.asarray(
        alignment.get("legacy_bottom_corner_order_for_field"), dtype=int
    )
    if order.shape != (4,) or sorted(order.tolist()) != [0, 1, 2, 3]:
        raise ProxySceneError(
            "legacy_bottom_corner_order_for_field는 0~3의 중복 없는 순서여야 합니다."
        )
    origin_legacy = int(alignment.get("origin_legacy_bottom_corner_index", -1))
    origin_field = int(alignment.get("origin_field_corner_index", -1))
    if origin_field != 0 or origin_legacy != int(order[0]):
        raise ProxySceneError(
            "문 시작점은 field corner 0이며 legacy 순서의 첫 모서리여야 합니다."
        )
    return order, origin_field


def _calibration(
    legacy_bottom: np.ndarray,
    legacy_top: np.ndarray,
    field_bottom: np.ndarray,
    field_top: np.ndarray,
    legacy_calibration: Mapping[str, Any],
    coordinate_system_id: str,
    legacy_corner_order: np.ndarray,
    origin_field_corner_index: int,
) -> Dict[str, Any]:
    legacy_transform = legacy_calibration.get("transform", {})
    legacy_metric_from_scene = _array(
        legacy_transform.get("T_metric_from_scene"),
        "legacy calibration T_metric_from_scene",
        (4, 4),
    )
    ordered_legacy_bottom = legacy_bottom[legacy_corner_order]
    ordered_legacy_top = legacy_top[legacy_corner_order]
    field_from_legacy, fit = _anchored_affine_fit(
        np.vstack([ordered_legacy_bottom, ordered_legacy_top]),
        np.vstack([field_bottom, field_top]),
        anchor_index=origin_field_corner_index,
    )
    field_from_scene = field_from_legacy @ legacy_metric_from_scene
    scene_from_field = np.linalg.inv(field_from_scene)
    inverse_error = max(
        float(np.max(np.abs(field_from_scene @ scene_from_field - np.eye(4)))),
        float(np.max(np.abs(scene_from_field @ field_from_scene - np.eye(4)))),
    )
    return {
        "schema_version": "1.0",
        "algorithm": {
            "name": "rfvisualizer_measured_proxy_envelope",
            "version": "1.0.0",
        },
        "status": "provisional",
        "confidence": "medium",
        "is_provisional": True,
        "warning_banner": "MEASURED XY BOUNDS; STEPS, CEILING HEIGHT, AND OBSTACLES NOT FULLY VALIDATED",
        "coordinate_system_id": coordinate_system_id,
        "transform": {
            "type": "affine_reference_alignment",
            "T_metric_from_scene": field_from_scene.tolist(),
            "T_scene_from_metric": scene_from_field.tolist(),
            "T_field_from_legacy_metric": field_from_legacy.tolist(),
            "legacy_bottom_corner_order_for_field": legacy_corner_order.tolist(),
            "origin_legacy_bottom_corner_index": int(
                legacy_corner_order[origin_field_corner_index]
            ),
            "origin_field_corner_index": int(origin_field_corner_index),
            "inverse_error": inverse_error,
            "reference_corner_fit": fit,
        },
        "warnings": [
            "문 시작점 legacy bottom corner {}를 실험 원점에 정확히 고정했다.".format(
                int(legacy_corner_order[origin_field_corner_index])
            ),
            "나머지 PGSR reference 정렬은 기존 8개 Room corner의 anchored affine 최소제곱 근사다.",
            "Reference 정렬 오차는 실험 좌표 입력 오차로 사용하지 말고 표시 보조로만 사용한다.",
        ],
    }


def build_proxy_envelope(
    scene_document: Mapping[str, Any],
    legacy_metadata: Mapping[str, Any],
    legacy_calibration: Mapping[str, Any],
) -> ProxyEnvelope:
    scene_report = validate_scene_document(scene_document)
    dimensions = scene_report["dimensions_m"]
    width = dimensions["width_x"]
    depth = dimensions["depth_y"]
    elevation = dimensions["floor_elevation_change"]
    legacy_corner_order, origin_field_corner_index = _reference_alignment(
        scene_document
    )

    legacy_bottom = _array(legacy_metadata.get("bottom_corners"), "legacy bottom_corners", (4, 3))
    legacy_top = _array(legacy_metadata.get("top_corners"), "legacy top_corners", (4, 3))
    clearances = legacy_top[:, 2] - legacy_bottom[:, 2]
    if np.any(clearances <= 0.0):
        raise ProxySceneError("기존 Room Envelope의 천장 여유 높이가 양수가 아닙니다.")

    bottom = np.asarray(
        [[0.0, 0.0, 0.0], [width, 0.0, 0.0], [width, depth, elevation], [0.0, depth, elevation]],
        dtype=float,
    )
    field_order_clearances = clearances[legacy_corner_order]
    front_clearance = float(np.mean(field_order_clearances[:2]))
    back_clearance = float(np.mean(field_order_clearances[2:]))
    top = np.asarray(
        [
            [0.0, 0.0, front_clearance],
            [width, 0.0, front_clearance],
            [width, depth, elevation + back_clearance],
            [0.0, depth, elevation + back_clearance],
        ],
        dtype=float,
    )
    vertices = np.vstack([bottom, top])
    interior = np.mean(vertices, axis=0)
    topology = analyze_topology(
        SimpleNamespace(vertices=vertices, faces=FACES, interior_point=interior),
        tolerance=1.0e-9,
    )
    if not topology["closed_manifold_success"] or topology["signed_volume"] <= 0.0:
        raise ProxySceneError("생성된 기본 Envelope가 양의 부피를 가진 닫힌 manifold가 아닙니다.")
    planes = _planes(bottom, top)
    statistics = mesh_statistics(vertices, FACES)
    calibration = _calibration(
        legacy_bottom,
        legacy_top,
        bottom,
        top,
        legacy_calibration,
        scene_report["coordinate_system_id"],
        legacy_corner_order,
        origin_field_corner_index,
    )
    assumptions = {
        "measured_values": {
            "width_x_m": width,
            "depth_y_m": depth,
            "floor_elevation_change_m": elevation,
            "door_width_m": dimensions["door_width"],
            "door_height_m": dimensions["door_height"],
        },
        "floor_model": "single_slope_placeholder",
        "floor_model_ready_for_final_experiment": False,
        "ceiling_model": "planar_front_back_clearance_from_legacy_pgsr_envelope",
        "legacy_corner_clearances_m": clearances.tolist(),
        "legacy_bottom_corner_order_for_field": legacy_corner_order.tolist(),
        "origin_legacy_bottom_corner_index": int(
            legacy_corner_order[origin_field_corner_index]
        ),
        "origin_field_corner_index": int(origin_field_corner_index),
        "resolved_front_clearance_m": front_clearance,
        "resolved_back_clearance_m": back_clearance,
        "remaining_geometry": [
            "stair_step_boundaries",
            "door placement/material handling",
            "major desks",
            "access point marker",
        ],
    }
    return ProxyEnvelope(
        vertices=vertices,
        faces=FACES.copy(),
        bottom=bottom,
        top=top,
        interior=interior,
        planes=planes,
        topology=topology,
        statistics=statistics,
        calibration=calibration,
        assumptions=assumptions,
    )


def _obj_text(envelope: ProxyEnvelope) -> str:
    lines = [
        "# RFVisualizer measured-base Metric Proxy Envelope\n",
        "# PROVISIONAL: step boundaries and obstacles are pending\n",
        "mtllib room_envelope_metric.mtl\n\n",
    ]
    for vertex in envelope.vertices:
        lines.append("v {:.12g} {:.12g} {:.12g}\n".format(*vertex))
    lines.append("\n")
    for object_name, semantic, material, face_range in OBJECTS:
        lines.extend(
            [
                "o {}\n".format(object_name),
                "g {}\n".format(semantic),
                "usemtl {}\n".format(material),
            ]
        )
        for face in envelope.faces[face_range[0] : face_range[1]]:
            lines.append("f {} {} {}\n".format(*(face + 1)))
        lines.append("\n")
    return "".join(lines)


def _mtl_text() -> str:
    return """# RFVisualizer Room Envelope materials

newmtl floor
Ka 0 0 0
Kd 0.550000 0.550000 0.550000
Ks 0 0 0
d 1.0
illum 1

newmtl ceiling
Ka 0 0 0
Kd 0.920000 0.920000 0.880000
Ks 0 0 0
d 1.0
illum 1

newmtl wall
Ka 0 0 0
Kd 0.820000 0.800000 0.740000
Ks 0 0 0
d 1.0
illum 1
"""


def _metadata(
    envelope: ProxyEnvelope,
    scene_report: Mapping[str, Any],
    scene_path: Path,
    legacy_metadata_path: Path,
    output_files: Mapping[str, str],
) -> Dict[str, Any]:
    bounds = envelope.statistics["bounds"]
    bounds["diagonal"] = float(
        np.linalg.norm(np.asarray(bounds["max"]) - np.asarray(bounds["min"]))
    )
    heights = envelope.top[:, 2] - envelope.bottom[:, 2]
    edge_lengths = [
        float(np.linalg.norm(envelope.bottom[(index + 1) % 4] - envelope.bottom[index]))
        for index in range(4)
    ]
    walls = []
    for index, equation in enumerate(envelope.planes["equations"]["walls"]):
        walls.append(
            {
                "object_name": "wall_{:03d}".format(index),
                "candidate_id": None,
                "metric_plane_equation": equation,
                "metric_centroid": envelope.planes["centroids"]["walls"][index],
                "bottom_corner_indices": [index, (index + 1) % 4],
                "top_corner_indices": [index, (index + 1) % 4],
            }
        )
    return {
        "schema_version": "1.0",
        "algorithm": {
            "name": "rfvisualizer_measured_proxy_envelope",
            "version": "1.0.0",
        },
        "status": "provisional",
        "confidence": "medium",
        "is_provisional": True,
        "warning_banner": envelope.calibration["warning_banner"],
        "source": {
            "experiment_scene_contract": str(scene_path),
            "legacy_metric_metadata": str(legacy_metadata_path),
        },
        "coordinate_system": {
            "id": scene_report["coordinate_system_id"],
            "unit": "meter",
            "origin": "door-left-bottom floor point",
            "up_axis": "+Z",
            "handedness": "right",
            "positive_bounds": True,
            "T_metric_from_scene": envelope.calibration["transform"]["T_metric_from_scene"],
            "T_scene_from_metric": envelope.calibration["transform"]["T_scene_from_metric"],
        },
        "bottom_corners": envelope.bottom.tolist(),
        "top_corners": envelope.top.tolist(),
        "interior_point": envelope.interior.tolist(),
        "plane_centroids": envelope.planes["centroids"],
        "normalized_plane_equations": envelope.planes["equations"],
        "bounds": bounds,
        "surface_area_square_meters": envelope.statistics["surface_area"],
        "signed_volume_cubic_meters": envelope.statistics["signed_volume"],
        "absolute_volume_cubic_meters": envelope.statistics["absolute_volume"],
        "floor_ceiling_height": float(np.mean(heights)),
        "height_statistics_meters": {
            "minimum": float(np.min(heights)),
            "maximum": float(np.max(heights)),
            "mean": float(np.mean(heights)),
            "values": heights.tolist(),
        },
        "polygon": {
            "bottom_xy_coordinates_meters": envelope.bottom[:, :2].tolist(),
            "ceiling_xy_coordinates_meters": envelope.top[:, :2].tolist(),
            "bottom_projected_signed_area_square_meters": float(
                scene_report["dimensions_m"]["width_x"]
                * scene_report["dimensions_m"]["depth_y"]
            ),
            "edge_lengths_meters": edge_lengths,
            "winding": "counter_clockwise_from_positive_z",
        },
        "mesh_summary": {
            "vertex_count": envelope.statistics["vertex_count"],
            "triangle_count": envelope.statistics["triangle_count"],
        },
        "topology_summary": envelope.topology,
        "wall_objects": walls,
        "assumptions": envelope.assumptions,
        "output_files": dict(output_files),
    }


def _export_previews(envelope: ProxyEnvelope, output: Path) -> Dict[str, str]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    except ImportError as exc:
        raise ProxySceneError("Proxy Scene 미리보기에는 matplotlib이 필요합니다.") from exc

    top_path = output / "preview_top.png"
    figure, axis = plt.subplots(figsize=(10, 7))
    polygon = np.vstack([envelope.bottom[:, :2], envelope.bottom[0, :2]])
    axis.fill(polygon[:, 0], polygon[:, 1], color="#dce8d2", alpha=0.55)
    axis.plot(polygon[:, 0], polygon[:, 1], color="black", linewidth=2)
    for index, point in enumerate(envelope.bottom):
        axis.scatter(point[0], point[1], color="black", s=35)
        axis.annotate("B{}  Z={:.2f}m".format(index, point[2]), point[:2], xytext=(5, 5), textcoords="offset points")
    axis.arrow(0.0, 0.0, 2.0, 0.0, color="red", width=0.025, length_includes_head=True)
    axis.arrow(0.0, 0.0, 0.0, 2.0, color="green", width=0.025, length_includes_head=True)
    axis.text(2.1, 0.0, "+X", color="red")
    axis.text(0.0, 2.1, "+Y", color="green")
    axis.set_aspect("equal")
    axis.set_xlim(-0.8, float(np.max(envelope.bottom[:, 0])) + 0.8)
    axis.set_ylim(-0.8, float(np.max(envelope.bottom[:, 1])) + 0.8)
    axis.set_xlabel("X [m]")
    axis.set_ylabel("Y [m]")
    axis.set_title("Measured-base Proxy Envelope — positive field coordinates")
    axis.grid(alpha=0.25)
    figure.tight_layout()
    figure.savefig(top_path, dpi=170)
    plt.close(figure)

    perspective_path = output / "preview_perspective.png"
    figure = plt.figure(figsize=(11, 8))
    axis = figure.add_subplot(111, projection="3d")
    colors = ["#a68562", "#72b7d2", "#b7c7a3", "#b7c7a3", "#b7c7a3", "#b7c7a3"]
    for color, (_, _, _, face_range) in zip(colors, OBJECTS):
        polygons = [envelope.vertices[face] for face in envelope.faces[face_range[0] : face_range[1]]]
        axis.add_collection3d(
            Poly3DCollection(polygons, facecolor=color, edgecolor="black", alpha=0.30)
        )
    axis.quiver(0, 0, 0, 2.5, 0, 0, color="red", linewidth=3)
    axis.quiver(0, 0, 0, 0, 2.5, 0, color="green", linewidth=3)
    axis.quiver(0, 0, 0, 0, 0, 2.5, color="blue", linewidth=3)
    axis.set_xlim(-0.5, float(np.max(envelope.vertices[:, 0])) + 0.5)
    axis.set_ylim(-0.5, float(np.max(envelope.vertices[:, 1])) + 0.5)
    axis.set_zlim(0.0, float(np.max(envelope.vertices[:, 2])) + 0.5)
    axis.set_xlabel("X [m]")
    axis.set_ylabel("Y [m]")
    axis.set_zlabel("Z [m]")
    axis.set_title("BASE ENVELOPE — stair steps and obstacles pending")
    axis.view_init(elev=24, azim=-58)
    figure.tight_layout()
    figure.savefig(perspective_path, dpi=170)
    plt.close(figure)
    return {
        "preview_top": str(top_path.resolve()),
        "preview_perspective": str(perspective_path.resolve()),
    }


def export_proxy_envelope(
    scene_path: Any,
    legacy_metadata_path: Any,
    legacy_calibration_path: Any,
    output_directory: Any,
) -> Dict[str, Any]:
    scene_source = resolve_path(scene_path)
    legacy_metadata_source = resolve_path(legacy_metadata_path)
    legacy_calibration_source = resolve_path(legacy_calibration_path)
    output = resolve_path(output_directory)
    output.mkdir(parents=True, exist_ok=True)

    scene_document = load_json(scene_source)
    scene_report = validate_scene_document(scene_document)
    envelope = build_proxy_envelope(
        scene_document,
        load_json(legacy_metadata_source),
        load_json(legacy_calibration_source),
    )
    obj_path = output / "room_envelope_metric.obj"
    mtl_path = output / "room_envelope_metric.mtl"
    metadata_path = output / "room_envelope_metric.json"
    calibration_path = output / "calibration.json"
    report_path = output / "PROXY_SCENE_BASE_REPORT.md"
    atomic_write_text(obj_path, _obj_text(envelope))
    atomic_write_text(mtl_path, _mtl_text())
    preview_files = _export_previews(envelope, output)
    output_files = {
        "metric_obj": str(obj_path.resolve()),
        "metric_mtl": str(mtl_path.resolve()),
        "metric_envelope_json": str(metadata_path.resolve()),
        "calibration_json": str(calibration_path.resolve()),
        "proxy_scene_report": str(report_path.resolve()),
        **preview_files,
    }
    metadata = _metadata(
        envelope,
        scene_report,
        scene_source,
        legacy_metadata_source,
        output_files,
    )
    write_json(metadata_path, metadata)
    write_json(calibration_path, envelope.calibration)
    fit = envelope.calibration["transform"]["reference_corner_fit"]
    report = """# 실측 기준 Proxy Scene 기본 Envelope

## 한 줄 결론

강의실 가로 15.4m, 깊이 10.8m, 전체 바닥 높이차 약 0.75m를 +X/+Y/+Z 실험 좌표에 반영한 닫힌 기본 Envelope를 생성했다. 계단 경계·문 처리·책상·AP 배치가 남아 있어 최종 Sionna 실험 장면은 아니다.

## 현재 형상

- Bounds: X 0–{width:.3f}m, Y 0–{depth:.3f}m
- 바닥: 단일 경사면 placeholder, 앞 0m → 뒤 {elevation:.3f}m
- 천장: 기존 PGSR Envelope의 앞/뒤 여유 높이를 평균해 만든 임시 평면
- 닫힌 manifold: {manifold}
- Triangle: {triangles}

## PGSR 표시 정렬

- 방식: 문 시작점을 (0, 0, 0)에 고정한 Room corner 8개의 anchored affine 최소제곱 정렬
- 문 시작점 anchor 오차: {anchor_error:.3e}m
- 평균 corner 오차: {mean_error:.4f}m
- 최대 corner 오차: {max_error:.4f}m
- 용도: 편집 화면의 참조 표시만 허용

## 남은 작업

1. 계단 경계와 단 높이 입력
2. 문 2.09m × 2.09m의 위치·재질 처리
3. 주요 책상 위치·크기·방향 입력
4. AP와 RX Marker 입력
5. Sionna Import와 2D Grid 검증
""".format(
        width=scene_report["dimensions_m"]["width_x"],
        depth=scene_report["dimensions_m"]["depth_y"],
        elevation=scene_report["dimensions_m"]["floor_elevation_change"],
        manifold=envelope.topology["closed_manifold_success"],
    triangles=envelope.statistics["triangle_count"],
    anchor_error=fit["anchor_error_m"],
    mean_error=fit["mean_corner_fit_error_m"],
        max_error=fit["maximum_corner_fit_error_m"],
    )
    atomic_write_text(report_path, report)
    return {
        "success": True,
        "status": "base_envelope_ready_obstacles_pending",
        "scene_id": scene_report["scene_id"],
        "coordinate_system_id": scene_report["coordinate_system_id"],
        "topology": envelope.topology,
        "reference_alignment": fit,
        "assumptions": envelope.assumptions,
        "files": output_files,
    }
