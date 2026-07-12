"""Resolve, validate, and export a Phase 2-B obstacle scenario."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import yaml

from tools.sionna_smoke_test.config import load_config as load_phase2a_config
from tools.sionna_smoke_test.coordinate_bridge import CoordinateBridge
from tools.sionna_smoke_test.io_utils import atomic_write_text
from tools.sionna_smoke_test.metric_scene_loader import load_metric_scene
from tools.sionna_smoke_test.placement import resolve_positions

from .config import public_document
from .material_resolver import resolve_material_request, resolve_obstacle_materials
from .obstacle_schema import ObstacleSpec, obstacles_from_document
from .obstacle_validator import validate_los_intersection, validate_obstacle
from .preview import export_scenario_preview
from .primitive_builder import build_obstacle_mesh
from .scene_composer import compose_scene


@dataclass
class PreparedScenario:
    document: Dict[str, Any]
    scenario: Dict[str, Any]
    phase2a_config: Dict[str, Any]
    settings: Dict[str, Any]
    metric_scene: Any
    room: Any
    positions: List[Dict[str, Any]]
    placement_warnings: List[str]
    obstacle_specs: List[ObstacleSpec]
    obstacle_records: List[Dict[str, Any]]
    materials: Dict[str, Any]


def _position_sets(positions: List[Dict[str, Any]]):
    transmitter = next(
        value for value in positions if value["kind"] == "transmitter"
    )
    receivers = [value for value in positions if value["kind"] == "receiver"]
    return transmitter, receivers


def prepare_scenario(document: Dict[str, Any]) -> PreparedScenario:
    scenario = document["scenario"]
    config_path = Path(scenario["_phase2a_config_path"])
    phase2a_config = load_phase2a_config(config_path)
    settings = phase2a_config["sionna_smoke_test"]
    metric_scene = load_metric_scene(settings)
    room, positions, placement_warnings = resolve_positions(
        settings, metric_scene.metric_metadata
    )
    source_path = Path(document["_source_path"])
    specs = obstacles_from_document(document, source_path=source_path)
    transmitter, receivers = _position_sets(positions)
    bridge = CoordinateBridge.from_calibration(metric_scene.calibration)
    obstacle_records = []
    enabled_sources = []
    for spec in specs:
        if not spec.enabled:
            continue
        mesh = build_obstacle_mesh(spec, room=room)
        require_los = bool(
            scenario.get("synthetic_validation", False)
            and spec.purpose == "validation_only"
        )
        validation = validate_obstacle(
            mesh,
            room,
            transmitter=transmitter,
            receivers=receivers,
            require_los_intersection=False,
        )
        if require_los:
            target = next(
                (value for value in receivers if value["name"] == "rx_los"), None
            )
            if target is None:
                raise ValueError(
                    "Synthetic blocker 검증에는 이름이 'rx_los'인 receiver가 필요합니다."
                )
            target_validation = validate_los_intersection(mesh, transmitter, target)
            validation["checks"]["required_los_intersection"] = bool(
                target_validation["success"]
            )
            validation["los"]["required"] = True
            validation["los"]["required_receiver"] = "rx_los"
            validation["los"]["required_target_intersection"] = bool(
                target_validation["success"]
            )
            validation["los"]["required_target_validation"] = target_validation
        source = spec.to_dict()
        enabled_sources.append(source)
        material = resolve_material_request(source)
        local_to_metric = np.asarray(mesh.transform, dtype=float)
        obstacle_records.append(
            {
                "id": spec.id,
                "object_name": spec.object_name,
                "group_name": spec.group_name,
                "semantic_class": spec.semantic_class,
                "purpose": spec.purpose,
                "physical_object": spec.physical_object,
                "confidence": spec.confidence,
                "geometry_type": spec.geometry.type,
                "vertices": mesh.vertices,
                "faces": mesh.faces,
                "local_to_metric": local_to_metric,
                "local_to_scene": bridge.scene_from_metric @ local_to_metric,
                "material": material,
                "validation": validation,
                "source_config": source,
            }
        )
    materials = resolve_obstacle_materials(enabled_sources)
    material_by_id = {
        value["obstacle_id"]: value for value in materials["materials"]
    }
    for record in obstacle_records:
        record["material"] = material_by_id[record["id"]]
    return PreparedScenario(
        document=document,
        scenario=scenario,
        phase2a_config=phase2a_config,
        settings=settings,
        metric_scene=metric_scene,
        room=room,
        positions=positions,
        placement_warnings=placement_warnings,
        obstacle_specs=specs,
        obstacle_records=obstacle_records,
        materials=materials,
    )


def validation_summary(prepared: PreparedScenario) -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "scenario_id": prepared.scenario["id"],
        "status": "provisional",
        "physically_validated": False,
        "synthetic_validation": bool(
            prepared.scenario.get("synthetic_validation", False)
        ),
        "metric_input_valid": True,
        "room_closed_manifold": bool(
            prepared.metric_scene.metric_metadata["topology_summary"][
                "closed_manifold_success"
            ]
        ),
        "position_count": len(prepared.positions),
        "enabled_obstacle_count": len(prepared.obstacle_records),
        "disabled_obstacle_count": sum(
            not value.enabled for value in prepared.obstacle_specs
        ),
        "obstacles": [
            {
                "id": value["id"],
                "geometry_type": value["geometry_type"],
                "bounds": value["validation"]["bounds"],
                "validation": value["validation"],
                "material": value["material"],
            }
            for value in prepared.obstacle_records
        ],
        "placement_warnings": prepared.placement_warnings,
        "success": all(
            value["validation"]["success"]
            for value in prepared.obstacle_records
        ),
    }


def build_scenario(prepared: PreparedScenario, output: Path) -> Dict[str, Any]:
    directory = Path(output).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    manifest = compose_scene(
        prepared.metric_scene,
        prepared.settings,
        prepared.scenario,
        prepared.obstacle_records,
        prepared.materials,
        directory,
    )
    preview = export_scenario_preview(
        prepared.metric_scene,
        prepared.obstacle_records,
        prepared.positions,
        directory,
    )
    resolved = public_document(prepared.document)
    resolved["scenario"]["resolved_positions"] = prepared.positions
    resolved["scenario"]["placement_warnings"] = prepared.placement_warnings
    atomic_write_text(
        directory / "resolved_scenario.yaml",
        yaml.safe_dump(resolved, allow_unicode=True, sort_keys=False),
    )
    manifest["files"]["scenario_preview_png"] = preview
    manifest["files"]["resolved_scenario_yaml"] = str(
        (directory / "resolved_scenario.yaml").resolve()
    )
    from tools.sionna_smoke_test.io_utils import write_json

    write_json(directory / "scenario_manifest.json", manifest)
    return manifest
