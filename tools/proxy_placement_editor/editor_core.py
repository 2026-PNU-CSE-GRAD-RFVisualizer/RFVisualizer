"""Headless authoring core shared by CLI, tests, and Open3D UI."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Dict, Optional, Type

from tools.sionna_smoke_test.io_utils import atomic_write_text, write_json
from tools.sionna_scenario.obstacle_schema import parse_obstacle
from tools.sionna_scenario.primitive_builder import build_obstacle_mesh

from .candidate_library import (
    CandidateTemplate,
    instantiate_candidate,
    load_candidate_library,
    materialize_draft_placeholders,
)
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
    ):
        self.scene = scene
        self.state = state
        self.candidates = candidates
        self.output = Path(output).expanduser().resolve()
        self.reference = reference
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
        existing = {str(value.get("id")) for value in self.state.obstacles}
        index = 0
        while True:
            value = "{}_{:03d}".format(candidate_id, index)
            if value not in existing:
                return value
            index += 1

    def add_candidate(self, candidate_id: str) -> Dict[str, Any]:
        before = self.state.snapshot_document()
        object_id = self.next_object_id(candidate_id)
        obstacle = instantiate_candidate(
            self.candidate(candidate_id), object_id, self.scene.containment
        )
        self.state.add_object(obstacle)
        self._commit(before, AddObjectCommand, object_id)
        return obstacle

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
            item.get("id") == value for item in self.state.obstacles
        ):
            raise EditorCoreError("Object ID '{}'가 이미 존재합니다.".format(value))
        before = self.state.snapshot_document()
        obstacle = self.state.get_object(object_id)
        obstacle["id"] = value
        export = obstacle.setdefault("export", {})
        if export.get("object_name", object_id) == object_id:
            export["object_name"] = value
        visible = self.state.object_visibility.pop(object_id, True)
        self.state.object_visibility[value] = visible
        self.state.selected_object_id = value
        self.state.dirty = True
        self._commit(before, ChangePropertyCommand, value)

    def reorder(self, object_id: str, offset: int) -> None:
        current = next(
            index
            for index, value in enumerate(self.state.obstacles)
            if value.get("id") == object_id
        )
        target = max(0, min(len(self.state.obstacles) - 1, current + int(offset)))
        if target == current:
            return
        before = self.state.snapshot_document()
        value = self.state.obstacles.pop(current)
        self.state.obstacles.insert(target, value)
        self.state.selected_object_id = object_id
        self.state.dirty = True
        self._commit(before, ChangePropertyCommand, object_id)

    def duplicate(self, object_id: str) -> Dict[str, Any]:
        before = self.state.snapshot_document()
        value = self.state.duplicate_object(object_id)
        self._commit(before, DuplicateObjectCommand, value["id"])
        return value

    def set_enabled(self, object_id: str, enabled: bool) -> None:
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
        for index, obstacle in enumerate(self.state.obstacles):
            if obstacle.get("id") == object_id:
                self.state.obstacles[index] = deepcopy(value)
                self.state.dirty = True
                self._commit(before, command_type, object_id)
                return
        raise EditorCoreError("Obstacle '{}'를 찾지 못했습니다.".format(object_id))

    def translate(
        self,
        object_id: str,
        delta_m,
        axis: Optional[str] = None,
        snap: Optional[bool] = None,
    ) -> None:
        value = translate_obstacle(
            self.state.get_object(object_id),
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
        return self.last_validation

    def preview_mesh(self, object_id: str):
        """Build one complete object for interactive drag without full validation."""

        value = deepcopy(self.state.get_object(object_id))
        value["enabled"] = True
        spec = parse_obstacle(value, source_path=self.state.source_path)
        return build_obstacle_mesh(spec, room=self.scene.containment)

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
        saved = save_editor_scenario(self.state.document, destination)
        self.state.document = with_authoring_metadata(self.state.document)
        self.state.source_path = saved
        self.state.dirty = False
        files = export_resolved_outputs(
            self.state, report, self.output, self.commands.log
        )
        return {"scenario": str(saved), "validation": report, "files": files}

    def export_preview(
        self, output: Optional[Path] = None, include_reference: bool = True
    ) -> Dict[str, str]:
        report = self.validate()
        destination = (
            Path(output).expanduser().resolve() if output else self.output / "preview"
        )
        return export_preview(
            self.scene, report, destination, self.reference, include_reference
        )

    def autosave(self) -> Dict[str, str]:
        directory = self.output / "autosave"
        directory.mkdir(parents=True, exist_ok=True)
        scenario_path = directory / "latest_scenario.yaml"
        state_path = directory / "latest_editor_state.json"
        atomic_write_text(scenario_path, dump_scenario(self.state.document))
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
        self.commands_since_autosave = 0
        return {"scenario": str(scenario_path), "editor_state": str(state_path)}

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
