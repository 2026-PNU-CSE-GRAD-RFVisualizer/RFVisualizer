"""Resolved 위치, Coverage 배열·표·그림과 장면 미리보기를 저장한다."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import yaml

from .coordinate_bridge import CoordinateBridge
from .io_utils import atomic_write_text, write_json


class SmokeTestExportError(RuntimeError):
    """Phase 2-A 결과 파일을 저장하지 못했을 때 발생한다."""


def export_resolved_configuration(
    config: Dict[str, Any],
    positions: List[Dict[str, Any]],
    bridge: CoordinateBridge,
    bridge_validation: Dict[str, Any],
    warnings: List[str],
    output: Path,
) -> Dict[str, Any]:
    output = Path(output)
    metric_document = {
        "schema_version": "1.0",
        "status": config["status"],
        "confidence": config["confidence"],
        "physically_validated": config["physically_validated"],
        "placement_mode": config["placement"]["mode"],
        "clearance_m": config["placement"]["clearance_m"],
        "positions": positions,
        "warnings": warnings,
    }
    scene_positions = []
    for value in positions:
        scene_position = bridge.metric_to_scene(np.asarray(value["resolved_position_m"]))
        scene_positions.append(
            {
                "kind": value["kind"],
                "name": value["name"],
                "metric_position_m": value["resolved_position_m"],
                "original_scene_position": scene_position.tolist(),
            }
        )
    scene_document = {
        "schema_version": "1.0",
        "status": config["status"],
        "positions": scene_positions,
        "coordinate_bridge_validation": bridge_validation,
    }
    write_json(output / "resolved_positions.json", metric_document)
    write_json(output / "resolved_positions_scene.json", scene_document)
    resolved = {"schema_version": "1.0", "sionna_smoke_test": dict(config)}
    resolved["sionna_smoke_test"]["resolved_positions"] = [
        {
            "kind": value["kind"],
            "name": value["name"],
            "position_m": value["resolved_position_m"],
            "used_fallback": value["used_fallback"],
        }
        for value in positions
    ]
    atomic_write_text(
        output / "resolved_config.yaml",
        yaml.safe_dump(resolved, allow_unicode=True, sort_keys=False),
    )
    return {"metric": metric_document, "scene": scene_document}


def _write_csv(path: Path, fieldnames: List[str], rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)
    except OSError as exc:
        raise SmokeTestExportError("CSV를 저장할 수 없습니다: {}".format(exc)) from exc


def export_coverage(
    result: Dict[str, Any],
    bridge: CoordinateBridge,
    positions: List[Dict[str, Any]],
    output: Path,
) -> Dict[str, str]:
    directory = Path(output) / "coverage"
    directory.mkdir(parents=True, exist_ok=True)
    values = np.asarray(result["values"], dtype=float)
    centers = np.asarray(result["centers"], dtype=float)
    inside = np.asarray(result["inside_mask"], dtype=bool)
    valid = np.asarray(result["valid_mask"], dtype=bool)
    masked = np.where(valid, values, np.nan)
    np.save(directory / "coverage_values.npy", masked)
    np.save(directory / "coverage_valid_mask.npy", valid)
    value_rows = []
    metric_rows = []
    flat_scene = bridge.metric_to_scene(centers.reshape((-1, 3))).reshape(centers.shape)
    scene_rows = []
    for row in range(values.shape[0]):
        for column in range(values.shape[1]):
            value_rows.append(
                {
                    "row": row,
                    "column": column,
                    "value_path_gain_linear": values[row, column],
                    "is_inside": bool(inside[row, column]),
                    "is_valid": bool(valid[row, column]),
                }
            )
            point = centers[row, column]
            common = {
                "x_m": point[0],
                "y_m": point[1],
                "z_m": point[2],
                "value_path_gain_linear": values[row, column],
                "is_inside": bool(inside[row, column]),
                "is_valid": bool(valid[row, column]),
            }
            metric_rows.append(common)
            scene_point = flat_scene[row, column]
            scene_rows.append(
                {
                    "scene_x": scene_point[0],
                    "scene_y": scene_point[1],
                    "scene_z": scene_point[2],
                    **common,
                }
            )
    _write_csv(
        directory / "coverage_values.csv",
        ["row", "column", "value_path_gain_linear", "is_inside", "is_valid"],
        value_rows,
    )
    metric_fields = ["x_m", "y_m", "z_m", "value_path_gain_linear", "is_inside", "is_valid"]
    _write_csv(directory / "coverage_points_metric.csv", metric_fields, metric_rows)
    _write_csv(
        directory / "coverage_points_scene.csv",
        ["scene_x", "scene_y", "scene_z"] + metric_fields,
        scene_rows,
    )
    write_json(directory / "coverage_metadata.json", result["metadata"])
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        display = np.full(values.shape, np.nan)
        display[valid] = 10.0 * np.log10(values[valid])
        x_values, y_values = centers[:, :, 0], centers[:, :, 1]
        extent = [
            float(np.min(x_values)),
            float(np.max(x_values)),
            float(np.min(y_values)),
            float(np.max(y_values)),
        ]
        figure, axis = plt.subplots(figsize=(10, 7))
        image = axis.imshow(display, origin="lower", extent=extent, aspect="equal", cmap="viridis")
        figure.colorbar(image, ax=axis, label="Path gain (dB)")
        for value in positions:
            point = value["resolved_position_m"]
            marker = "P" if value["kind"] == "transmitter" else "x"
            color = "red" if value["kind"] == "transmitter" else "white"
            axis.scatter(point[0], point[1], marker=marker, color=color, s=90)
            axis.annotate(value["name"], (point[0], point[1]), xytext=(5, 5), textcoords="offset points", color=color)
        axis.set_xlabel("X (m)")
        axis.set_ylabel("Y (m)")
        axis.set_title("PROVISIONAL Sionna RT path-gain map — not physically validated")
        figure.tight_layout()
        figure.savefig(directory / "coverage_map.png", dpi=170)
        plt.close(figure)
    except Exception as exc:
        raise SmokeTestExportError("Coverage PNG를 저장할 수 없습니다: {}".format(exc)) from exc
    return {
        "coverage_values_npy": str((directory / "coverage_values.npy").resolve()),
        "coverage_values_csv": str((directory / "coverage_values.csv").resolve()),
        "coverage_valid_mask_npy": str((directory / "coverage_valid_mask.npy").resolve()),
        "coverage_metadata_json": str((directory / "coverage_metadata.json").resolve()),
        "coverage_map_png": str((directory / "coverage_map.png").resolve()),
        "coverage_points_metric_csv": str((directory / "coverage_points_metric.csv").resolve()),
        "coverage_points_scene_csv": str((directory / "coverage_points_scene.csv").resolve()),
    }


def export_scene_preview(metric_scene, positions: List[Dict[str, Any]], output: Path) -> str:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection

        colors = {"floor": "#a68562", "ceiling": "#72b7d2", "wall": "#b7c7a3"}
        figure = plt.figure(figsize=(11, 8))
        axis = figure.add_subplot(111, projection="3d")
        for obj in metric_scene.objects:
            polygons = [metric_scene.vertices[face] for face in obj.faces]
            axis.add_collection3d(
                Poly3DCollection(polygons, facecolor=colors[obj.semantic], edgecolor="black", alpha=0.35)
            )
        for value in positions:
            point = value["resolved_position_m"]
            color = "red" if value["kind"] == "transmitter" else "green"
            marker = "P" if value["kind"] == "transmitter" else "x"
            axis.scatter(*point, color=color, marker=marker, s=100)
            axis.text(*point, " " + value["name"], color=color)
        minimum = np.min(metric_scene.vertices, axis=0)
        maximum = np.max(metric_scene.vertices, axis=0)
        extent = maximum - minimum
        center = (minimum + maximum) / 2.0
        half = max(extent) / 2.0
        axis.set_xlim(center[0] - half, center[0] + half)
        axis.set_ylim(center[1] - half, center[1] + half)
        axis.set_zlim(minimum[2] - 0.5, maximum[2] + 3.0)
        axis.quiver(0, 0, 0, 3, 0, 0, color="r", linewidth=3)
        axis.quiver(0, 0, 0, 0, 3, 0, color="g", linewidth=3)
        axis.quiver(0, 0, 0, 0, 0, 3, color="b", linewidth=3)
        axis.set_xlabel("X (m)")
        axis.set_ylabel("Y (m)")
        axis.set_zlabel("Z (m)")
        axis.set_title("PROVISIONAL Sionna RT empty-room scene")
        axis.view_init(elev=24, azim=-55)
        figure.tight_layout()
        path = Path(output) / "scene_preview.png"
        figure.savefig(path, dpi=170)
        plt.close(figure)
        return str(path.resolve())
    except Exception as exc:
        raise SmokeTestExportError("Scene preview를 저장할 수 없습니다: {}".format(exc)) from exc
