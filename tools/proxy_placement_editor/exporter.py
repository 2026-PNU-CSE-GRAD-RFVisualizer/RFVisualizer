"""Resolved placement metadata and deterministic vertex-table export."""

from __future__ import annotations

import csv
import io
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

from tools.sionna_smoke_test.io_utils import atomic_write_text, write_json

from .editor_state import EditorState
from .scenario_io import with_authoring_metadata


def _object_document(record: Dict[str, Any], coordinate: str) -> Dict[str, Any]:
    if coordinate == "metric":
        bounds, transform, vertices = (
            record["metric_bounds"],
            record["metric_transform"],
            record["metric_vertices"],
        )
    else:
        bounds, transform, vertices = (
            record["scene_bounds"],
            record["scene_transform"],
            record["scene_vertices"],
        )
    containment = record["phase2b_validation"]["containment"]
    return {
        "id": record["id"],
        "enabled": record["enabled"],
        "status": record["status"],
        "coordinate_space": coordinate,
        "bounds": bounds,
        "transform": transform,
        "vertices": vertices,
        "faces": record["faces"],
        "floor_clearance_m": containment["minimum_floor_clearance_m"],
        "ceiling_clearance_m": containment["minimum_ceiling_clearance_m"],
        "wall_clearance_m": containment["minimum_wall_clearance_m"],
        "collision_warnings": record["collision_warnings"],
        "coordinate_round_trip_error": record["coordinate_round_trip"]["maximum_error"],
        "material_category": record["material"]["category"],
        "confidence": record["source"].get("confidence"),
    }


def _vertex_csv(report: Dict[str, Any], coordinate: str) -> str:
    stream = io.StringIO()
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(["object_id", "vertex_index", "x", "y", "z", "coordinate_space"])
    key = "metric_vertices" if coordinate == "metric" else "scene_vertices"
    for record in report["objects"]:
        if not record.get("renderable"):
            continue
        for index, vertex in enumerate(record[key]):
            writer.writerow(
                [
                    record["id"],
                    index,
                    "{:.9f}".format(vertex[0]),
                    "{:.9f}".format(vertex[1]),
                    "{:.9f}".format(vertex[2]),
                    coordinate,
                ]
            )
    return stream.getvalue()


def export_resolved_outputs(
    state: EditorState,
    report: Dict[str, Any],
    output: Path,
    command_log: Any = None,
) -> Dict[str, str]:
    directory = Path(output).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    renderable = [value for value in report["objects"] if value.get("renderable")]
    resolved = with_authoring_metadata(state.document)
    resolved["authoring_resolution"] = {
        "status": "provisional",
        "physically_validated": False,
        "placement_validation": deepcopy(report),
    }
    paths = {
        "scenario_resolved": directory / "scenario_resolved.json",
        "obstacles_metric": directory / "obstacles_metric.json",
        "obstacles_scene": directory / "obstacles_scene.json",
        "vertices_metric": directory / "obstacle_vertices_metric.csv",
        "vertices_scene": directory / "obstacle_vertices_scene.csv",
        "placement_validation": directory / "placement_validation.json",
        "editor_state": directory / "editor_state.json",
        "command_log": directory / "command_log.json",
    }
    write_json(paths["scenario_resolved"], resolved)
    write_json(
        paths["obstacles_metric"],
        {
            "schema_version": "1.0",
            "coordinate_space": "metric",
            "units": "meters",
            "objects": [_object_document(value, "metric") for value in renderable],
        },
    )
    write_json(
        paths["obstacles_scene"],
        {
            "schema_version": "1.0",
            "coordinate_space": "scene",
            "units": "scene_units",
            "objects": [_object_document(value, "scene") for value in renderable],
        },
    )
    atomic_write_text(paths["vertices_metric"], _vertex_csv(report, "metric"))
    atomic_write_text(paths["vertices_scene"], _vertex_csv(report, "scene"))
    write_json(paths["placement_validation"], report)
    write_json(paths["editor_state"], state.ui_document())
    write_json(
        paths["command_log"],
        {"schema_version": "1.0", "commands": list(command_log or [])},
    )
    return {key: str(value) for key, value in paths.items()}
