"""Real-time validation adapter over the existing Phase 2-B implementation."""

from __future__ import annotations

from copy import deepcopy
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from tools.sionna_scenario.config import validate_scenario
from tools.sionna_scenario.material_resolver import resolve_material_request
from tools.sionna_scenario.obstacle_schema import parse_obstacle
from tools.sionna_scenario.obstacle_validator import inspect_obstacle
from tools.sionna_scenario.primitive_builder import build_obstacle_mesh
from tools.sionna_smoke_test.config import load_config as load_phase2a_config
from tools.sionna_smoke_test.placement import resolve_positions

from .coordinate_bridge import PlacementCoordinateBridge
from .scene_loader import PlacementScene


class PlacementValidationError(ValueError):
    pass


def _resolved_devices(document: Dict[str, Any], scene: PlacementScene):
    checked = validate_scenario(deepcopy(document))
    phase2a_path = Path(checked["scenario"]["_phase2a_config_path"])
    settings = load_phase2a_config(phase2a_path)["sionna_smoke_test"]
    _, positions, warnings = resolve_positions(settings, scene.room_metadata)
    transmitter = next(value for value in positions if value["kind"] == "transmitter")
    receivers = [value for value in positions if value["kind"] == "receiver"]
    return transmitter, receivers, positions, warnings


def _enabled_copy(obstacle: Dict[str, Any]) -> Dict[str, Any]:
    value = deepcopy(obstacle)
    value["enabled"] = True
    return value


def _allowed_overlap(first: Dict[str, Any], second: Dict[str, Any]) -> bool:
    for source, target in ((first, second), (second, first)):
        patterns = source.get("validation", {}).get("allow_overlap_with", [])
        if isinstance(patterns, list) and any(
            fnmatch(str(target.get("id")), str(pattern)) for pattern in patterns
        ):
            return True
    return False


def _aabb_overlap(
    first: Dict[str, Any], second: Dict[str, Any], tolerance: float = 1.0e-9
) -> bool:
    first_min = np.asarray(first["bounds"]["min"], dtype=float)
    first_max = np.asarray(first["bounds"]["max"], dtype=float)
    second_min = np.asarray(second["bounds"]["min"], dtype=float)
    second_max = np.asarray(second["bounds"]["max"], dtype=float)
    overlap = np.minimum(first_max, second_max) - np.maximum(first_min, second_min)
    return bool(np.all(overlap > tolerance))


def validate_document(
    document: Dict[str, Any],
    scene: PlacementScene,
    include_disabled_geometry: bool = True,
    wall_warning_distance_m: float = 0.02,
) -> Dict[str, Any]:
    """Inspect all renderable obstacles without rejecting disabled drafts."""

    try:
        transmitter, receivers, positions, placement_warnings = _resolved_devices(
            document, scene
        )
    except Exception as exc:
        raise PlacementValidationError(
            "TX/RX 기준 위치를 읽을 수 없습니다: {}".format(exc)
        ) from exc
    bridge = PlacementCoordinateBridge.from_calibration(scene.calibration)
    scenario = document.get("scenario", {})
    synthetic = bool(scenario.get("synthetic_validation", False))
    records: List[Dict[str, Any]] = []
    meshes: Dict[str, Any] = {}
    record_by_id: Dict[str, Dict[str, Any]] = {}
    for obstacle in scenario.get("obstacles", []):
        object_id = str(obstacle.get("id", "<missing>"))
        enabled = obstacle.get("enabled") is True
        record: Dict[str, Any] = {
            "id": object_id,
            "enabled": enabled,
            "renderable": False,
            "status": "DISABLED_INCOMPLETE" if not enabled else "INVALID",
            "errors": [],
            "warnings": [],
            "collision_warnings": [],
            "source": deepcopy(obstacle),
        }
        try:
            value = obstacle if enabled else _enabled_copy(obstacle)
            spec = parse_obstacle(value)
            mesh = build_obstacle_mesh(spec, room=scene.containment)
            required_los = synthetic and spec.purpose == "validation_only"
            target_receivers = receivers
            if required_los:
                target_receivers = [
                    value for value in receivers if value.get("name") == "rx_los"
                ]
                if len(target_receivers) != 1:
                    raise PlacementValidationError(
                        "Synthetic validation에는 rx_los receiver 하나가 필요합니다."
                    )
            phase2b = inspect_obstacle(
                mesh,
                scene.containment,
                transmitter=transmitter,
                receivers=target_receivers if required_los else receivers,
                require_los_intersection=required_los,
            )
            material = resolve_material_request(value)
            coordinate = bridge.report(mesh.vertices, mesh.transform)
            scene_vertices = bridge.metric_vertices_to_scene(mesh.vertices)
            record.update(
                {
                    "renderable": True,
                    "geometry_type": spec.geometry.type,
                    "metric_vertices": mesh.vertices.tolist(),
                    "faces": mesh.faces.tolist(),
                    "metric_transform": np.asarray(
                        mesh.transform, dtype=float
                    ).tolist(),
                    "scene_vertices": scene_vertices.tolist(),
                    "scene_transform": coordinate["scene_transform"],
                    "metric_bounds": phase2b["bounds"],
                    "scene_bounds": {
                        "min": np.min(scene_vertices, axis=0).tolist(),
                        "max": np.max(scene_vertices, axis=0).tolist(),
                    },
                    "bounds": phase2b["bounds"],
                    "phase2b_validation": phase2b,
                    "material": material,
                    "coordinate_round_trip": coordinate,
                }
            )
            record["errors"].extend(phase2b["errors"])
            if not coordinate["success"]:
                record["errors"].append(
                    "Metric/scene coordinate round trip이 허용 오차를 넘었습니다."
                )
            containment = phase2b["containment"]
            if (
                phase2b["success"]
                and containment["minimum_wall_clearance_m"] < wall_warning_distance_m
            ):
                record["warnings"].append(
                    "Obstacle이 벽에 {:.4f} m보다 가깝습니다.".format(
                        wall_warning_distance_m
                    )
                )
            if enabled:
                record["status"] = "VALID" if not record["errors"] else "INVALID"
            else:
                record["status"] = (
                    "DISABLED" if not record["errors"] else "DISABLED_INVALID"
                )
            meshes[object_id] = mesh
        except Exception as exc:
            record["errors"].append(str(exc))
            if enabled:
                record["status"] = "INVALID"
        if enabled or include_disabled_geometry or record["renderable"]:
            records.append(record)
            record_by_id[object_id] = record

    enabled_renderable = [
        value for value in records if value["enabled"] and value["renderable"]
    ]
    for index, first in enumerate(enabled_renderable):
        for second in enabled_renderable[index + 1 :]:
            if _allowed_overlap(first["source"], second["source"]):
                continue
            if _aabb_overlap(first, second):
                first["collision_warnings"].append(second["id"])
                second["collision_warnings"].append(first["id"])
    for record in records:
        if record["collision_warnings"]:
            record["warnings"].append(
                "AABB overlap: {}".format(
                    ", ".join(sorted(record["collision_warnings"]))
                )
            )
        if record["enabled"] and record["status"] == "VALID" and record["warnings"]:
            record["status"] = "WARNING"

    enabled_errors = [
        {"id": value["id"], "errors": value["errors"]}
        for value in records
        if value["enabled"] and value["errors"]
    ]
    maximum_round_trip = max(
        (
            value["coordinate_round_trip"]["maximum_error"]
            for value in records
            if value["renderable"]
        ),
        default=0.0,
    )
    return {
        "schema_version": "1.0",
        "status": "provisional",
        "physically_validated": False,
        "warning_banner": "PROVISIONAL GEOMETRY - DO NOT INTERPRET AS REAL RSSI ACCURACY",
        "scenario_id": scenario.get("id"),
        "room_inputs": {
            "room_obj": str(scene.room_obj_path),
            "room_json": str(scene.room_json_path),
            "calibration": str(scene.calibration_path),
            **scene.source_hashes,
        },
        "resolved_positions": positions,
        "placement_warnings": placement_warnings,
        "enabled_obstacle_count": sum(value["enabled"] for value in records),
        "renderable_obstacle_count": sum(value["renderable"] for value in records),
        "maximum_coordinate_round_trip_error": maximum_round_trip,
        "objects": records,
        "enabled_errors": enabled_errors,
        "success": not enabled_errors,
    }


def renderable_meshes(report: Dict[str, Any], include_disabled: bool = True):
    result = []
    for record in report["objects"]:
        if not record.get("renderable") or (
            not include_disabled and not record.get("enabled")
        ):
            continue
        result.append(
            (
                record["id"],
                np.asarray(record["metric_vertices"], dtype=float),
                np.asarray(record["faces"], dtype=int),
                record,
            )
        )
    return result
