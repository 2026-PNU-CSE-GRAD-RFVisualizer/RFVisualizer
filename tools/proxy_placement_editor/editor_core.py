"""Headless authoring core shared by CLI, tests, and Open3D UI."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Dict, Optional, Type

import numpy as np

from tools.rf_experiment.contracts import validate_marker_document
from tools.sionna_smoke_test.io_utils import atomic_write_text, write_json
from tools.sionna_scenario.obstacle_schema import parse_obstacle
from tools.sionna_scenario.primitive_builder import (
    TriangleMesh,
    build_obstacle_mesh,
    create_box_mesh,
    transform_mesh,
)

from .candidate_library import (
    CandidateTemplate,
    instantiate_candidate,
    load_candidate_library,
    materialize_draft_placeholders,
)
from .coordinate_bridge import PlacementCoordinateBridge
from .command_stack import (
    AddObjectCommand,
    ChangePropertyCommand,
    CommandStack,
    DeleteObjectCommand,
    DuplicateObjectCommand,
    EnableObjectCommand,
    ResizeObjectCommand,
    StateCommand,
    TransformObjectCommand,
)
from .editor_state import EditorState
from .exporter import export_resolved_outputs
from .preview_exporter import export_preview
from .reference_loader import ReferenceGeometry
from .scenario_io import (
    dump_scenario,
    load_editor_scenario,
    save_editor_scenario,
    with_authoring_metadata,
)
from .scene_loader import PlacementScene, load_placement_scene
from .transform_controller import resize_obstacle, rotate_obstacle, translate_obstacle
from .validation_bridge import validate_document


class EditorCoreError(ValueError):
    pass


class EditorCore:
    def __init__(
        self,
        scene: PlacementScene,
        state: EditorState,
        candidates: list,
        output: Path,
        reference: Optional[ReferenceGeometry] = None,
        point_cloud: Optional[ReferenceGeometry] = None,
        pgsr_output_mesh: Optional[ReferenceGeometry] = None,
    ):
        self.scene = scene
        self.state = state
        self.candidates = candidates
        self.output = Path(output).expanduser().resolve()
        # `reference` remains a read-compatible constructor argument for older
        # callers. New code keeps the two PGSR products as distinct layers.
        self.point_cloud = point_cloud or reference
        self.pgsr_output_mesh = pgsr_output_mesh
        self.commands = CommandStack()
        self.last_validation: Optional[Dict[str, Any]] = None
        self.commands_since_autosave = 0

    def materialize_draft_placeholders(self) -> list:
        """Make matching null drafts visible without touching the source file."""

        changed = materialize_draft_placeholders(
            self.state.obstacles, self.candidates, self.scene.containment
        )
        if changed:
            self.last_validation = None
        return changed

    @classmethod
    def from_paths(
        cls,
        room_json: Path,
        calibration: Path,
        scenario: Path,
        output: Path,
        candidates: Path,
        room_obj: Optional[Path] = None,
        reference: Optional[ReferenceGeometry] = None,
        point_cloud: Optional[ReferenceGeometry] = None,
        pgsr_output_mesh: Optional[ReferenceGeometry] = None,
    ) -> "EditorCore":
        scene = load_placement_scene(room_json, calibration, room_obj=room_obj)
        source = Path(scenario).expanduser().resolve()
        state = EditorState(load_editor_scenario(source), source_path=source)
        return cls(
            scene,
            state,
            load_candidate_library(candidates),
            output,
            reference=reference,
            point_cloud=point_cloud,
            pgsr_output_mesh=pgsr_output_mesh,
        )

    def _commit(
        self,
        before: Dict[str, Any],
        command_type: Type[StateCommand],
        object_id: Optional[str],
    ) -> None:
        command = self.commands.commit(
            self.state, before, command_type=command_type, object_id=object_id
        )
        if command:
            self.commands_since_autosave += 1
            self.last_validation = None
            if self.commands_since_autosave >= 10:
                self.autosave()

    def commit_preview(
        self,
        before: Dict[str, Any],
        command_type: Type[StateCommand],
        object_id: Optional[str],
    ) -> None:
        """Commit a GUI drag after all preview frames have already been applied."""

        self._commit(before, command_type, object_id)

    def candidate(self, candidate_id: str) -> CandidateTemplate:
        for value in self.candidates:
            if value.id == candidate_id:
                return value
        raise EditorCoreError("Candidate '{}'를 찾지 못했습니다.".format(candidate_id))

    def next_object_id(self, candidate_id: str) -> str:
        existing = {str(value.get("id")) for value in self.state.all_objects}
        index = 0
        while True:
            value = "{}_{:03d}".format(candidate_id, index)
            if value not in existing:
                return value
            index += 1

    def add_candidate(self, candidate_id: str) -> Dict[str, Any]:
        if candidate_id == "ap_tx" and self.state.marker_document is None:
            raise EditorCoreError(
                "AP/TX를 추가하려면 편집기를 --markers TX_RX_JSON과 함께 실행해야 합니다."
            )
        before = self.state.snapshot_document()
        object_id = self.next_object_id(candidate_id)
        obstacle = instantiate_candidate(
            self.candidate(candidate_id), object_id, self.scene.containment
        )
        self.state.add_object(obstacle)
        self._commit(before, AddObjectCommand, object_id)
        return obstacle

    def add_receiver(self, role: str) -> Dict[str, Any]:
        if self.state.marker_document is None:
            raise EditorCoreError(
                "RX를 추가하려면 편집기를 --markers TX_RX_JSON과 함께 실행해야 합니다."
            )
        if role not in {"calibration", "test"}:
            raise EditorCoreError("RX 역할은 calibration 또는 test여야 합니다.")
        before = self.state.snapshot_document()
        prefix = "cal" if role == "calibration" else "test"
        object_id = self.next_object_id("{}_rx".format(prefix))
        existing_points = {str(value.get("point_id")) for value in self.state.receivers}
        index = 1
        while True:
            point_id = "{}-{:02d}".format(prefix, index)
            if point_id not in existing_points:
                break
            index += 1
        center = np.asarray(self.scene.containment.interior_point, dtype=float)
        floor_z, ceiling_z = self.scene.containment.floor_ceiling_z(
            float(center[0]), float(center[1])
        )
        receiver = {
            "id": object_id,
            "point_id": point_id,
            "name": "{} RX {}".format(
                "보정" if role == "calibration" else "Test", index
            ),
            "role": role,
            "position_m": [
                float(center[0]),
                float(center[1]),
                float((floor_z + ceiling_z) / 2.0),
            ],
        }
        self.state.add_receiver(receiver)
        self._commit(before, AddObjectCommand, object_id)
        return receiver

    def delete(self, object_id: str) -> None:
        before = self.state.snapshot_document()
        self.state.delete_object(object_id)
        self._commit(before, DeleteObjectCommand, object_id)

    def rename(self, object_id: str, new_id: str) -> None:
        value = str(new_id).strip()
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", value) or value in {
            ".",
            "..",
        }:
            raise EditorCoreError(
                "Object ID에는 영문자, 숫자, '_', '-', '.'만 사용할 수 있습니다."
            )
        if value != object_id and any(
            item.get("id") == value for item in self.state.all_objects
        ):
            raise EditorCoreError("Object ID '{}'가 이미 존재합니다.".format(value))
        before = self.state.snapshot_document()
        editable = self.state.get_object(object_id)
        editable["id"] = value
        if self.state.object_kind(value) != "rx":
            export = editable.setdefault("export", {})
            if export.get("object_name", object_id) == object_id:
                export["object_name"] = value
        visible = self.state.object_visibility.pop(object_id, True)
        self.state.object_visibility[value] = visible
        self.state.rename_selection(object_id, value)
        if value not in self.state.selected_object_ids:
            self.state.select(value)
        self.state.dirty = True
        self._commit(before, ChangePropertyCommand, value)

    def reorder(self, object_id: str, offset: int) -> None:
        values = (
            self.state.receivers
            if self.state.object_kind(object_id) == "rx"
            else self.state.obstacles
        )
        current = next(
            index for index, value in enumerate(values) if value.get("id") == object_id
        )
        target = max(0, min(len(values) - 1, current + int(offset)))
        if target == current:
            return
        before = self.state.snapshot_document()
        value = values.pop(current)
        values.insert(target, value)
        self.state.dirty = True
        self._commit(before, ChangePropertyCommand, object_id)

    def duplicate(self, object_id: str) -> Dict[str, Any]:
        before = self.state.snapshot_document()
        value = self.state.duplicate_object(object_id)
        self._commit(before, DuplicateObjectCommand, value["id"])
        return value

    def set_enabled(self, object_id: str, enabled: bool) -> None:
        if self.state.object_kind(object_id) == "rx":
            raise EditorCoreError("RX는 Sionna 장애물 활성화 대상이 아닙니다.")
        before = self.state.snapshot_document()
        self.state.get_object(object_id)["enabled"] = bool(enabled)
        self.state.dirty = True
        self._commit(before, EnableObjectCommand, object_id)

    def replace_object(
        self,
        object_id: str,
        value: Dict[str, Any],
        command_type: Type[StateCommand] = ChangePropertyCommand,
    ) -> None:
        before = self.state.snapshot_document()
        values = (
            self.state.receivers
            if self.state.object_kind(object_id) == "rx"
            else self.state.obstacles
        )
        for index, editable in enumerate(values):
            if editable.get("id") == object_id:
                values[index] = deepcopy(value)
                self.state.dirty = True
                self._commit(before, command_type, object_id)
                return
        raise EditorCoreError("객체 '{}'를 찾지 못했습니다.".format(object_id))

    def translate(
        self,
        object_id: str,
        delta_m,
        axis: Optional[str] = None,
        snap: Optional[bool] = None,
    ) -> None:
        source = self.state.get_object(object_id)
        if self.state.object_kind(object_id) == "rx":
            delta = np.asarray(delta_m, dtype=float)
            if delta.shape == ():
                direction = {"x": 0, "y": 1, "z": 2}.get(axis or "")
                if direction is None:
                    raise EditorCoreError("스칼라 RX 이동에는 X/Y/Z축이 필요합니다.")
                vector = np.zeros(3, dtype=float)
                vector[direction] = float(delta)
                delta = vector
            value = deepcopy(source)
            position = np.asarray(value.get("position_m"), dtype=float) + delta
            if self.state.snap.enabled if snap is None else snap:
                increment = float(self.state.snap.translation_m)
                position = np.round(position / increment) * increment
            value["position_m"] = position.tolist()
        else:
            value = translate_obstacle(
                source,
                delta_m,
                axis=axis,
                snap_increment_m=self.state.snap.translation_m,
                snap_enabled=self.state.snap.enabled if snap is None else snap,
            )
        self.replace_object(object_id, value, TransformObjectCommand)

    def rotate(
        self,
        object_id: str,
        delta_deg: float,
        axis: str = "z",
        snap: Optional[bool] = None,
    ) -> None:
        if self.state.object_kind(object_id) == "rx":
            raise EditorCoreError("RX는 점 객체이므로 회전할 수 없습니다.")
        value = rotate_obstacle(
            self.state.get_object(object_id),
            delta_deg,
            axis=axis,
            snap_increment_deg=self.state.snap.rotation_deg,
            snap_enabled=self.state.snap.enabled if snap is None else snap,
        )
        self.replace_object(object_id, value, TransformObjectCommand)

    def resize(
        self,
        object_id: str,
        factor: float,
        axis: Optional[str] = None,
        snap: Optional[bool] = None,
    ) -> None:
        if self.state.object_kind(object_id) == "rx":
            raise EditorCoreError("RX는 점 객체이므로 크기를 조절할 수 없습니다.")
        value = resize_obstacle(
            self.state.get_object(object_id),
            factor,
            axis=axis,
            snap_increment_m=self.state.snap.size_m,
            snap_enabled=self.state.snap.enabled if snap is None else snap,
        )
        self.replace_object(object_id, value, ResizeObjectCommand)

    def validate(self) -> Dict[str, Any]:
        self.last_validation = validate_document(self.state.document, self.scene)
        self._append_rf_validation(self.last_validation)
        return self.last_validation

    @staticmethod
    def _marker_mesh(marker: Dict[str, Any]) -> TriangleMesh:
        position = np.asarray(marker.get("position_m"), dtype=float)
        if position.shape != (3,) or not np.all(np.isfinite(position)):
            raise EditorCoreError("RX 위치에는 유한한 X/Y/Z 숫자 3개가 필요합니다.")
        transform = np.eye(4, dtype=float)
        transform[:3, 3] = position
        return transform_mesh(
            create_box_mesh((0.18, 0.18, 0.18), obstacle_id=str(marker.get("id"))),
            transform,
        )

    def _append_rf_validation(self, report: Dict[str, Any]) -> None:
        bridge = PlacementCoordinateBridge.from_calibration(self.scene.calibration)
        marker_errors = []
        for receiver in self.state.receivers:
            object_id = str(receiver.get("id", "<missing>"))
            record = {
                "id": object_id,
                "object_kind": "rx",
                "enabled": True,
                "renderable": False,
                "status": "INVALID",
                "errors": [],
                "warnings": [],
                "collision_warnings": [],
                "source": deepcopy(receiver),
                "material": {"category": "{}_rx".format(receiver.get("role", "test"))},
            }
            try:
                if receiver.get("role") not in {"calibration", "test"}:
                    raise EditorCoreError("RX 역할은 calibration 또는 test여야 합니다.")
                if not str(receiver.get("point_id", "")).strip():
                    raise EditorCoreError("RX point_id가 비어 있습니다.")
                mesh = self._marker_mesh(receiver)
                position = np.asarray(receiver["position_m"], dtype=float)
                bounds_min = np.asarray(self.scene.containment.bounds_min, dtype=float)
                bounds_max = np.asarray(self.scene.containment.bounds_max, dtype=float)
                if np.any(position[:2] < bounds_min[:2]) or np.any(
                    position[:2] > bounds_max[:2]
                ):
                    raise EditorCoreError("RX의 X/Y 위치가 Room 범위를 벗어났습니다.")
                floor_z, ceiling_z = self.scene.containment.floor_ceiling_z(
                    float(position[0]), float(position[1])
                )
                if position[2] < floor_z or position[2] > ceiling_z:
                    raise EditorCoreError("RX 높이가 바닥과 천장 사이에 있지 않습니다.")
                coordinate = bridge.report(mesh.vertices, mesh.transform)
                scene_vertices = bridge.metric_vertices_to_scene(mesh.vertices)
                record.update(
                    {
                        "renderable": True,
                        "status": "VALID",
                        "metric_vertices": mesh.vertices.tolist(),
                        "faces": mesh.faces.tolist(),
                        "metric_transform": mesh.transform.tolist(),
                        "scene_vertices": scene_vertices.tolist(),
                        "scene_transform": coordinate["scene_transform"],
                        "coordinate_round_trip": coordinate,
                    }
                )
            except Exception as exc:
                record["errors"].append(str(exc))
                marker_errors.append({"id": object_id, "errors": record["errors"]})
            report["objects"].append(record)
        for record in report["objects"]:
            record.setdefault(
                "object_kind",
                "ap_tx" if isinstance(record.get("source", {}).get("rf_transmitter"), dict) else "obstacle",
            )
            if record["object_kind"] == "ap_tx":
                transmitter = record["source"].get("rf_transmitter", {})
                try:
                    frequency = float(transmitter.get("frequency_hz"))
                    power = float(transmitter.get("power_dbm"))
                    if not np.isfinite(frequency) or frequency <= 0.0 or not np.isfinite(power):
                        raise ValueError
                except (TypeError, ValueError):
                    record["errors"].append(
                        "AP/TX 주파수는 양수, 송신 세기는 유한한 숫자여야 합니다."
                    )
                    record["status"] = "INVALID"
                    marker_errors.append({"id": record["id"], "errors": record["errors"]})
        point_ids = [str(value.get("point_id", "")) for value in self.state.receivers]
        if len(point_ids) != len(set(point_ids)):
            marker_errors.append(
                {"id": "rf_markers", "errors": ["RX point_id는 서로 달라야 합니다."]}
            )
        counts = {
            "transmitter_count": sum(
                self.state.object_kind(str(value.get("id"))) == "ap_tx"
                for value in self.state.obstacles
            ),
            "calibration_receiver_count": sum(
                value.get("role") == "calibration" for value in self.state.receivers
            ),
            "test_receiver_count": sum(
                value.get("role") == "test" for value in self.state.receivers
            ),
        }
        if self.state.marker_document is not None:
            try:
                marker_report = validate_marker_document(
                    self._resolved_marker_document(),
                    {
                        "scene_id": self.state.marker_document.get("scene_id"),
                        "coordinate_system_id": self.state.marker_document.get(
                            "coordinate_system_id"
                        ),
                        "bounds_m": {
                            "x": [
                                float(self.scene.containment.bounds_min[0]),
                                float(self.scene.containment.bounds_max[0]),
                            ],
                            "y": [
                                float(self.scene.containment.bounds_min[1]),
                                float(self.scene.containment.bounds_max[1]),
                            ],
                        },
                    },
                )
                report["placement_warnings"].extend(marker_report["warnings"])
            except Exception as exc:
                marker_errors.append({"id": "rf_markers", "errors": [str(exc)]})
        report["enabled_errors"].extend(marker_errors)
        report["success"] = report["success"] and not marker_errors
        report["rf_marker_count"] = {
            "tx": counts["transmitter_count"],
            "calibration_rx": counts["calibration_receiver_count"],
            "test_rx": counts["test_receiver_count"],
        }

    def preview_mesh_value(self, object_id: str, value: Dict[str, Any]):
        """Build an arbitrary object value for interactive transform previews."""

        value = deepcopy(value)
        if self.state.object_kind(object_id) == "rx":
            return self._marker_mesh(value)
        value["enabled"] = True
        spec = parse_obstacle(value, source_path=self.state.source_path)
        return build_obstacle_mesh(spec, room=self.scene.containment)

    def preview_mesh(self, object_id: str):
        """Build one complete object for interactive drag without full validation."""

        return self.preview_mesh_value(object_id, self.state.get_object(object_id))

    def _scenario_document_without_transmitters(self) -> Dict[str, Any]:
        """Keep RF endpoint markers out of the physical obstacle contract."""

        document = deepcopy(self.state.document)
        scenario = document.get("scenario", {})
        obstacles = scenario.get("obstacles", [])
        scenario["obstacles"] = [
            value
            for value in obstacles
            if not isinstance(value.get("rf_transmitter"), dict)
        ]
        return document

    def save(self, path: Optional[Path] = None) -> Dict[str, Any]:
        report = self.validate()
        if not report["success"]:
            raise EditorCoreError(
                "활성 INVALID obstacle이 있어 headless save를 차단했습니다."
            )
        destination = (
            Path(path).expanduser().resolve() if path else self.state.source_path
        )
        if destination is None:
            raise EditorCoreError("Save As 경로가 필요합니다.")
        saved = save_editor_scenario(
            self._scenario_document_without_transmitters(), destination
        )
        marker_saved = None
        if self.state.marker_document is not None:
            marker_destination = self.state.marker_source_path
            if marker_destination is None:
                marker_destination = self.output / "tx_rx.json"
            self.state.marker_document = self._resolved_marker_document()
            write_json(marker_destination, self.state.marker_document)
            self.state.marker_source_path = Path(marker_destination).resolve()
            marker_saved = str(self.state.marker_source_path)
        self.state.document = with_authoring_metadata(self.state.document)
        self.state.source_path = saved
        self.state.dirty = False
        files = export_resolved_outputs(
            self.state, report, self.output, self.commands.log
        )
        return {
            "scenario": str(saved),
            "markers": marker_saved,
            "validation": report,
            "files": files,
        }

    def _transmitter_records(self) -> list:
        records = []
        for obstacle in self.state.obstacles:
            transmitter = obstacle.get("rf_transmitter")
            if not isinstance(transmitter, dict):
                continue
            geometry = obstacle.get("geometry", {})
            position = geometry.get("position_m", {})
            if not isinstance(position, dict) or not all(
                axis in position for axis in ("x", "y", "z")
            ):
                raise EditorCoreError("AP/TX는 자유 3차원 중심 위치를 사용해야 합니다.")
            records.append(
                {
                    "id": str(obstacle.get("id")),
                    "name": str(obstacle.get("display_name", obstacle.get("id"))),
                    "position_m": [float(position[axis]) for axis in ("x", "y", "z")],
                    "frequency_hz": float(transmitter.get("frequency_hz")),
                    "power_dbm": float(transmitter.get("power_dbm")),
                }
            )
        return records

    def _resolved_marker_document(self) -> Dict[str, Any]:
        if self.state.marker_document is None:
            raise EditorCoreError("TX/RX 문서가 열려 있지 않습니다.")
        document = deepcopy(self.state.marker_document)
        document["tx"] = self._transmitter_records()
        return document

    def export_preview(
        self, output: Optional[Path] = None, include_reference: bool = True
    ) -> Dict[str, str]:
        report = self.validate()
        destination = (
            Path(output).expanduser().resolve() if output else self.output / "preview"
        )
        references = [
            value
            for value in (self.point_cloud, self.pgsr_output_mesh)
            if value is not None
        ]
        return export_preview(
            self.scene, report, destination, references, include_reference
        )

    def autosave(self) -> Dict[str, str]:
        directory = self.output / "autosave"
        directory.mkdir(parents=True, exist_ok=True)
        scenario_path = directory / "latest_scenario.yaml"
        state_path = directory / "latest_editor_state.json"
        atomic_write_text(
            scenario_path,
            dump_scenario(self._scenario_document_without_transmitters()),
        )
        state_document = self.state.ui_document()
        state_document.update(
            {
                "autosaved_at": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "source_scenario_path": str(self.state.source_path)
                if self.state.source_path
                else None,
            }
        )
        write_json(state_path, state_document)
        marker_path = None
        if self.state.marker_document is not None:
            marker_path = directory / "latest_tx_rx.json"
            write_json(marker_path, self._resolved_marker_document())
        self.commands_since_autosave = 0
        result = {"scenario": str(scenario_path), "editor_state": str(state_path)}
        if marker_path is not None:
            result["markers"] = str(marker_path)
        return result

    def undo(self) -> bool:
        changed = self.commands.undo()
        if changed:
            self.last_validation = None
        return changed

    def redo(self) -> bool:
        changed = self.commands.redo()
        if changed:
            self.last_validation = None
        return changed
