"""Phase 2-B obstacle, path, and coverage comparison exporters."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

import numpy as np

from tools.sionna_smoke_test.io_utils import atomic_write_text, write_json


class ScenarioExportError(RuntimeError):
    """Raised when a Phase 2-B artifact cannot be written."""


def _bounds(points: np.ndarray) -> Dict[str, List[float]]:
    values = np.asarray(points, dtype=float)
    minimum = np.min(values, axis=0)
    maximum = np.max(values, axis=0)
    return {
        "min": minimum.tolist(),
        "max": maximum.tolist(),
        "extent": (maximum - minimum).tolist(),
    }


def _write_csv(path: Path, fields: Sequence[str], rows: Iterable[Dict[str, Any]]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(fields))
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(destination)
    except OSError as exc:
        raise ScenarioExportError("CSV를 저장할 수 없습니다: {}".format(exc)) from exc


def write_obstacle_obj(records: Sequence[Dict[str, Any]], output: Path) -> Dict[str, str]:
    directory = Path(output)
    directory.mkdir(parents=True, exist_ok=True)
    obj_path = directory / "obstacles_combined.obj"
    mtl_path = directory / "obstacles_combined.mtl"
    obj = [
        "# RFVisualizer Phase 2-B obstacle layer\n",
        "# {}PROVISIONAL - NOT PHYSICALLY VALIDATED\n".format(
            "SYNTHETIC/" if any(
                value.get("purpose") == "validation_only" for value in records
            ) else ""
        ),
        "mtllib obstacles_combined.mtl\n",
    ]
    material_colors = {
        "concrete": (0.55, 0.55, 0.55),
        "wood": (0.53, 0.28, 0.12),
        "metal": (0.35, 0.38, 0.43),
        "glass": (0.30, 0.55, 0.75),
    }
    mtl = ["# Preview-only Wavefront materials; RF values live in scene.xml\n"]
    offset = 1
    for record in records:
        obstacle_id = record["id"]
        object_name = record.get("object_name", obstacle_id)
        vertices = np.asarray(record["vertices"], dtype=float)
        faces = np.asarray(record["faces"], dtype=int)
        material = record["material"]
        material_name = material["actual_sionna_material_name"]
        group = record.get("group_name", record.get("semantic_class", "obstacle"))
        obj.extend(
            [
                "\n# obstacle_id: {}\n".format(obstacle_id),
                "o {}\n".format(object_name),
                "g {}\n".format(group),
                "usemtl {}\n".format(material_name),
            ]
        )
        obj.extend("v {:.12g} {:.12g} {:.12g}\n".format(*vertex) for vertex in vertices)
        obj.extend(
            "f {} {} {}\n".format(*[int(index) + offset for index in face])
            for face in faces
        )
        color = material_colors[material["category"]]
        mtl.extend(
            [
                "\nnewmtl {}\n".format(material_name),
                "Kd {:.6g} {:.6g} {:.6g}\n".format(*color),
                "d 1.0\n",
            ]
        )
        offset += len(vertices)
    atomic_write_text(obj_path, "".join(obj))
    atomic_write_text(mtl_path, "".join(mtl))
    return {
        "obstacles_combined_obj": str(obj_path.resolve()),
        "obstacles_combined_mtl": str(mtl_path.resolve()),
    }


def export_obstacle_coordinates(
    records: Sequence[Dict[str, Any]], bridge: Any, output: Path
) -> Dict[str, Any]:
    directory = Path(output)
    metric_objects = []
    scene_objects = []
    metric_rows = []
    scene_rows = []
    all_metric = []
    all_scene = []
    transform_metric_round_trip_errors = []
    transform_scene_round_trip_errors = []
    for record in records:
        metric = np.asarray(record["vertices"], dtype=float)
        scene = bridge.metric_to_scene(metric)
        local_to_metric = np.asarray(record.get("local_to_metric", np.eye(4)), dtype=float)
        if local_to_metric.shape != (4, 4):
            raise ScenarioExportError("Obstacle local_to_metric 행렬은 4x4여야 합니다.")
        local_to_scene = bridge.scene_from_metric @ local_to_metric
        metric_round_trip = bridge.metric_from_scene @ local_to_scene
        scene_round_trip = bridge.scene_from_metric @ metric_round_trip
        transform_metric_round_trip_errors.append(
            float(np.max(np.abs(metric_round_trip - local_to_metric)))
        )
        transform_scene_round_trip_errors.append(
            float(np.max(np.abs(scene_round_trip - local_to_scene)))
        )
        common = {
            "id": record["id"],
            "semantic_class": record.get("semantic_class"),
            "purpose": record.get("purpose"),
            "physical_object": record.get("physical_object"),
            "confidence": record.get("confidence"),
            "triangle_count": int(len(record["faces"])),
        }
        metric_objects.append(
            {
                **common,
                "coordinate_system": "metric_meter_+Z",
                "bounds": _bounds(metric),
                "vertices": metric.tolist(),
                "local_to_metric": local_to_metric.tolist(),
            }
        )
        scene_objects.append(
            {
                **common,
                "coordinate_system": "original_pgsr_scene",
                "bounds": _bounds(scene),
                "vertices": scene.tolist(),
                "local_to_scene": local_to_scene.tolist(),
            }
        )
        for index, (metric_point, scene_point) in enumerate(zip(metric, scene)):
            metric_rows.append(
                {
                    "obstacle_id": record["id"],
                    "vertex_index": index,
                    "x_m": metric_point[0],
                    "y_m": metric_point[1],
                    "z_m": metric_point[2],
                }
            )
            scene_rows.append(
                {
                    "obstacle_id": record["id"],
                    "vertex_index": index,
                    "scene_x": scene_point[0],
                    "scene_y": scene_point[1],
                    "scene_z": scene_point[2],
                    "metric_x_m": metric_point[0],
                    "metric_y_m": metric_point[1],
                    "metric_z_m": metric_point[2],
                }
            )
        all_metric.append(metric)
        all_scene.append(scene)
    if all_metric:
        metric_array = np.concatenate(all_metric, axis=0)
        scene_array = np.concatenate(all_scene, axis=0)
        point_round_trip = bridge.validation_report(metric_array, scene_array)
    else:
        point_round_trip = {
            "metric_to_scene_to_metric_max_error": 0.0,
            "scene_to_metric_to_scene_max_error": 0.0,
            "maximum_error": 0.0,
            "success": True,
        }
    transform_metric_error = max(transform_metric_round_trip_errors, default=0.0)
    transform_scene_error = max(transform_scene_round_trip_errors, default=0.0)
    transform_error = max(transform_metric_error, transform_scene_error)
    round_trip = {
        **point_round_trip,
        "point_maximum_error": point_round_trip["maximum_error"],
        "transform_metric_to_scene_to_metric_max_error": transform_metric_error,
        "transform_scene_to_metric_to_scene_max_error": transform_scene_error,
        "transform_maximum_error": transform_error,
        "maximum_error": max(point_round_trip["maximum_error"], transform_error),
        "success": bool(point_round_trip["success"] and transform_error <= 1e-8),
    }
    metric_document = {
        "schema_version": "1.0",
        "status": "provisional",
        "physically_validated": False,
        "objects": metric_objects,
        "coordinate_bridge_validation": round_trip,
    }
    scene_document = {
        "schema_version": "1.0",
        "status": "provisional",
        "physically_validated": False,
        "objects": scene_objects,
        "coordinate_bridge_validation": round_trip,
    }
    write_json(directory / "obstacles_metric.json", metric_document)
    write_json(directory / "obstacles_scene.json", scene_document)
    _write_csv(
        directory / "obstacle_vertices_metric.csv",
        ["obstacle_id", "vertex_index", "x_m", "y_m", "z_m"],
        metric_rows,
    )
    _write_csv(
        directory / "obstacle_vertices_scene.csv",
        [
            "obstacle_id",
            "vertex_index",
            "scene_x",
            "scene_y",
            "scene_z",
            "metric_x_m",
            "metric_y_m",
            "metric_z_m",
        ],
        scene_rows,
    )
    return {
        "obstacles_metric_json": str((directory / "obstacles_metric.json").resolve()),
        "obstacles_scene_json": str((directory / "obstacles_scene.json").resolve()),
        "obstacle_vertices_metric_csv": str(
            (directory / "obstacle_vertices_metric.csv").resolve()
        ),
        "obstacle_vertices_scene_csv": str(
            (directory / "obstacle_vertices_scene.csv").resolve()
        ),
        "coordinate_bridge_validation": round_trip,
    }


def write_path_records(path: Path, document: Dict[str, Any]) -> Dict[str, str]:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_json(destination, document)
    csv_path = destination.with_suffix(".csv")
    fields = [
        "path_index",
        "transmitter",
        "receiver",
        "path_type",
        "interaction_count",
        "distance_m",
        "delay_s",
        "amplitude_magnitude",
        "interaction_types",
        "interaction_object_ids",
        "interaction_object_names",
        "interaction_points_m",
    ]
    rows = []
    for record in document.get("paths", []):
        row = {key: record.get(key) for key in fields}
        for key in (
            "interaction_types",
            "interaction_object_ids",
            "interaction_object_names",
            "interaction_points_m",
        ):
            row[key] = json.dumps(row[key], ensure_ascii=False)
        rows.append(row)
    _write_csv(csv_path, fields, rows)
    return {"json": str(destination.resolve()), "csv": str(csv_path.resolve())}


def write_coverage_delta_csv(
    path: Path,
    centers: np.ndarray,
    baseline_db: np.ndarray,
    variant_db: np.ndarray,
    inside: np.ndarray,
    baseline_valid: np.ndarray,
    variant_valid: np.ndarray,
    variant_inside: np.ndarray = None,
) -> str:
    points = np.asarray(centers, dtype=float)
    baseline = np.asarray(baseline_db, dtype=float)
    variant = np.asarray(variant_db, dtype=float)
    inside_mask = np.asarray(inside, dtype=bool)
    variant_inside_mask = (
        inside_mask
        if variant_inside is None
        else np.asarray(variant_inside, dtype=bool)
    )
    common_inside = inside_mask & variant_inside_mask
    common = (
        np.asarray(baseline_valid, dtype=bool)
        & np.asarray(variant_valid, dtype=bool)
        & common_inside
        & np.isfinite(baseline)
        & np.isfinite(variant)
    )
    rows = []
    for row_index in range(baseline.shape[0]):
        for column_index in range(baseline.shape[1]):
            point = points[row_index, column_index]
            is_common = bool(common[row_index, column_index])
            rows.append(
                {
                    "x_m": point[0],
                    "y_m": point[1],
                    "z_m": point[2],
                    "baseline_db": baseline[row_index, column_index] if is_common else "",
                    "variant_db": variant[row_index, column_index] if is_common else "",
                    "delta_db": variant[row_index, column_index] - baseline[row_index, column_index]
                    if is_common
                    else "",
                    "is_inside": bool(common_inside[row_index, column_index]),
                    "is_valid_baseline": bool(baseline_valid[row_index, column_index]),
                    "is_valid_variant": bool(variant_valid[row_index, column_index]),
                    "is_common_valid": is_common,
                }
            )
    fields = [
        "x_m",
        "y_m",
        "z_m",
        "baseline_db",
        "variant_db",
        "delta_db",
        "is_inside",
        "is_valid_baseline",
        "is_valid_variant",
        "is_common_valid",
    ]
    _write_csv(path, fields, rows)
    return str(Path(path).resolve())
