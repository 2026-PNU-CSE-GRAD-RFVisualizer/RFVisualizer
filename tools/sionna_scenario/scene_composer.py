"""Compose the immutable metric Room Envelope and independent obstacle shapes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Sequence

import numpy as np

from tools.sionna_smoke_test.coordinate_bridge import CoordinateBridge
from tools.sionna_smoke_test.io_utils import atomic_write_text, write_json
from tools.sionna_smoke_test.metric_scene_loader import mesh_statistics
from tools.sionna_smoke_test.scene_exporter import export_scene, read_ascii_ply, write_ascii_ply

from .exporter import export_obstacle_coordinates, write_obstacle_obj
from .material_resolver import material_xml


class SceneCompositionError(RuntimeError):
    """Raised when room and obstacle layers cannot be kept independent."""


def _obstacle_shape_xml(record: Dict[str, Any]) -> str:
    return "".join(
        [
            '    <shape type="ply" id="mesh-{}">\n'.format(record["object_name"]),
            '        <string name="filename" value="meshes/{}.ply"/>\n'.format(
                record["object_name"]
            ),
            '        <boolean name="face_normals" value="true"/>\n',
            '        <ref id="{}" name="bsdf"/>\n'.format(
                record["material"]["actual_sionna_material_name"]
            ),
            "    </shape>\n",
        ]
    )


def _validate_unique_names(
    room_objects: Sequence[Dict[str, Any]], obstacles: Sequence[Dict[str, Any]]
) -> None:
    room_names = {value["object_name"] for value in room_objects}
    obstacle_names = [value["object_name"] for value in obstacles]
    if len(obstacle_names) != len(set(obstacle_names)):
        raise SceneCompositionError("Obstacle object_name이 중복됩니다.")
    collision = room_names.intersection(obstacle_names)
    if collision:
        raise SceneCompositionError(
            "Room object와 obstacle object 이름이 충돌합니다: {}".format(sorted(collision))
        )


def compose_scene(
    metric_scene: Any,
    settings: Dict[str, Any],
    scenario: Dict[str, Any],
    obstacles: Sequence[Dict[str, Any]],
    materials: Dict[str, Any],
    output: Path,
) -> Dict[str, Any]:
    """Write one Mitsuba/Sionna scene with separate room and obstacle PLY shapes."""

    directory = Path(output).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    # Phase 2-A writes/cleans the room mesh folder, so it must run first.
    base_manifest = export_scene(metric_scene, settings, directory)
    _validate_unique_names(base_manifest["objects"], obstacles)
    scene_directory = directory / "scene"
    mesh_directory = scene_directory / "meshes"
    obstacle_objects: List[Dict[str, Any]] = []
    for record in obstacles:
        vertices = np.asarray(record["vertices"], dtype=float)
        faces = np.asarray(record["faces"], dtype=int)
        path = mesh_directory / "{}.ply".format(record["object_name"])
        write_ascii_ply(
            path,
            vertices,
            faces,
            comment="RFVisualizer Phase 2-B proxy obstacle mesh",
        )
        loaded_vertices, loaded_faces = read_ascii_ply(path)
        if not np.allclose(loaded_vertices, vertices, atol=1e-9) or not np.array_equal(
            loaded_faces, faces
        ):
            raise SceneCompositionError(
                "Obstacle PLY '{}' round-trip 검증에 실패했습니다.".format(record["id"])
            )
        stats = mesh_statistics(vertices, faces)
        obstacle_objects.append(
            {
                "object_name": record["object_name"],
                "obstacle_id": record["id"],
                "layer": "proxy_obstacle",
                "semantic": record["semantic_class"],
                "semantic_class": record["semantic_class"],
                "purpose": record["purpose"],
                "physical_object": record["physical_object"],
                "confidence": record["confidence"],
                "geometry_type": record["geometry_type"],
                "source_material": record["material"]["category"],
                "resolved_radio_material": record["material"][
                    "actual_sionna_material_name"
                ],
                "mesh_file": str(path.resolve()),
                "vertex_count": int(len(vertices)),
                "triangle_count": int(len(faces)),
                "bounds": stats["bounds"],
                "signed_volume": stats["signed_volume"],
                "metric_transform": np.asarray(record["local_to_metric"], dtype=float).tolist(),
                "scene_space_transform": np.asarray(
                    record["local_to_scene"], dtype=float
                ).tolist(),
                "source_config": record["source_config"],
                "validation": record["validation"],
            }
        )
    scene_xml_path = Path(base_manifest["scene_xml"])
    try:
        xml = scene_xml_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SceneCompositionError("Base scene XML을 읽을 수 없습니다: {}".format(exc)) from exc
    material_blocks = "".join(material_xml(value) for value in materials["materials"])
    shape_blocks = "".join(_obstacle_shape_xml(value) for value in obstacles)
    marker = "    <!-- Metric Room Envelope shapes -->\n"
    if marker not in xml or "</scene>" not in xml:
        raise SceneCompositionError("Phase 2-A scene XML 구조가 예상과 다릅니다.")
    xml = xml.replace(
        marker,
        "    <!-- Independent Phase 2-B obstacle materials -->\n"
        + material_blocks
        + "\n"
        + marker,
        1,
    )
    xml = xml.replace(
        "</scene>",
        "\n    <!-- Independent Phase 2-B obstacle shapes -->\n" + shape_blocks + "</scene>",
        1,
    )
    atomic_write_text(scene_xml_path, xml)

    bridge = CoordinateBridge.from_calibration(metric_scene.calibration)
    coordinate_files = export_obstacle_coordinates(obstacles, bridge, directory)
    obj_files = write_obstacle_obj(obstacles, directory)
    room_objects = [{**value, "layer": "room_envelope"} for value in base_manifest["objects"]]
    enabled_ids = [value["id"] for value in obstacles]
    disabled_ids = [
        value["id"] for value in scenario.get("obstacles", []) if not value.get("enabled")
    ]
    all_objects = room_objects + obstacle_objects
    manifest = {
        "schema_version": "1.0",
        "scenario_id": scenario["id"],
        "status": "provisional",
        "physically_validated": False,
        "synthetic_validation": bool(scenario.get("synthetic_validation", False)),
        "base_scene": {
            "phase2a_config": scenario["base_scene"]["phase2a_config"],
            "metric_room_envelope": str(metric_scene.paths["metric_obj"]),
            "room_envelope_modified": False,
        },
        "scene_xml": str(scene_xml_path.resolve()),
        "enabled_obstacles": enabled_ids,
        "disabled_obstacles": disabled_ids,
        "materials": materials["materials"],
        "objects": all_objects,
        "room_object_count": len(room_objects),
        "obstacle_object_count": len(obstacle_objects),
        "total_object_count": len(all_objects),
        "room_triangle_count": sum(value["triangle_count"] for value in room_objects),
        "obstacle_triangle_count": sum(
            value["triangle_count"] for value in obstacle_objects
        ),
        "total_triangle_count": sum(value["triangle_count"] for value in all_objects),
        "object_layers_independent": True,
        "merge_shapes": False,
        "conversion_validation": {
            **base_manifest["conversion_validation"],
            "obstacle_ply_round_trip": True,
            "unique_object_names": True,
            "room_envelope_unchanged": True,
            "success": True,
        },
        "coordinate_bridge_validation": coordinate_files[
            "coordinate_bridge_validation"
        ],
        "files": {
            **{
                key: value
                for key, value in coordinate_files.items()
                if key != "coordinate_bridge_validation"
            },
            **obj_files,
            "scene_xml": str(scene_xml_path.resolve()),
        },
        "warnings": ["PROVISIONAL SCALE — NOT PHYSICALLY VALIDATED"]
        + (
            ["Synthetic validation objects are not measured classroom objects."]
            if scenario.get("synthetic_validation", False)
            else []
        ),
    }
    write_json(directory / "scenario_manifest.json", manifest)
    write_json(directory / "materials_resolved.json", materials)
    return manifest


def annotate_runtime_objects(manifest: Dict[str, Any], scene: Any, output: Path) -> Dict[str, Any]:
    """Record Sionna's runtime object IDs without changing scene geometry."""

    runtime = {
        name: int(value.object_id)
        for name, value in scene.objects.items()
        if getattr(value, "object_id", None) is not None
    }
    updated = dict(manifest)
    updated["objects"] = [
        {**value, "runtime_object_id": runtime.get(value["object_name"])}
        for value in manifest["objects"]
    ]
    missing = [
        value["object_name"]
        for value in updated["objects"]
        if value["runtime_object_id"] is None
    ]
    if missing:
        raise SceneCompositionError(
            "Sionna runtime에서 shape를 찾지 못했습니다: {}".format(missing)
        )
    updated["runtime_object_mapping"] = runtime
    updated["runtime_object_id_validation"] = {
        "all_manifest_objects_loaded": True,
        "runtime_object_count": len(runtime),
        "success": len(runtime) == len(updated["objects"]),
    }
    if not updated["runtime_object_id_validation"]["success"]:
        raise SceneCompositionError("Sionna runtime object 수가 manifest와 다릅니다.")
    write_json(Path(output) / "scenario_manifest.json", updated)
    return updated
