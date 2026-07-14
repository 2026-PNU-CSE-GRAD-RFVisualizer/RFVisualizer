"""GUI-independent mutable editor state; scenario YAML remains authoritative."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


class EditorStateError(ValueError):
    pass


@dataclass
class SnapSettings:
    enabled: bool = True
    translation_m: float = 0.05
    rotation_deg: float = 5.0
    size_m: float = 0.05

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "translation_m": self.translation_m,
            "rotation_deg": self.rotation_deg,
            "size_m": self.size_m,
        }


@dataclass
class EditorState:
    document: Dict[str, Any]
    source_path: Optional[Path] = None
    selected_object_id: Optional[str] = None
    object_visibility: Dict[str, bool] = field(default_factory=dict)
    viewport_mode: str = "select"
    axis_constraint: Optional[str] = None
    reference_visible: bool = True
    grid_visible: bool = True
    show_disabled: bool = True
    snap: SnapSettings = field(default_factory=SnapSettings)
    camera: Dict[str, Any] = field(default_factory=dict)
    panel_sizes: Dict[str, float] = field(
        default_factory=lambda: {"side_panel_width": 410.0}
    )
    dirty: bool = False

    def __post_init__(self) -> None:
        self.document = deepcopy(self.document)
        for obstacle in self.obstacles:
            self.object_visibility.setdefault(str(obstacle.get("id")), True)

    @property
    def obstacles(self) -> List[Dict[str, Any]]:
        scenario = self.document.get("scenario")
        if not isinstance(scenario, dict):
            raise EditorStateError("scenario mapping이 없습니다.")
        obstacles = scenario.setdefault("obstacles", [])
        if not isinstance(obstacles, list):
            raise EditorStateError("scenario.obstacles는 목록이어야 합니다.")
        return obstacles

    def get_object(self, object_id: str) -> Dict[str, Any]:
        for obstacle in self.obstacles:
            if obstacle.get("id") == object_id:
                return obstacle
        raise EditorStateError("Obstacle '{}'를 찾지 못했습니다.".format(object_id))

    def select(self, object_id: Optional[str]) -> None:
        if object_id is not None:
            self.get_object(object_id)
        self.selected_object_id = object_id

    def add_object(self, obstacle: Dict[str, Any], index: Optional[int] = None) -> None:
        object_id = str(obstacle.get("id", ""))
        if not object_id or any(
            value.get("id") == object_id for value in self.obstacles
        ):
            raise EditorStateError(
                "Obstacle ID가 비어 있거나 중복됩니다: {}".format(object_id)
            )
        if index is None:
            self.obstacles.append(deepcopy(obstacle))
        else:
            self.obstacles.insert(index, deepcopy(obstacle))
        self.object_visibility[object_id] = True
        self.selected_object_id = object_id
        self.dirty = True

    def delete_object(self, object_id: str) -> Dict[str, Any]:
        for index, obstacle in enumerate(self.obstacles):
            if obstacle.get("id") == object_id:
                removed = self.obstacles.pop(index)
                self.object_visibility.pop(object_id, None)
                if self.selected_object_id == object_id:
                    self.selected_object_id = None
                self.dirty = True
                return removed
        raise EditorStateError("Obstacle '{}'를 찾지 못했습니다.".format(object_id))

    def duplicate_object(self, object_id: str) -> Dict[str, Any]:
        source = deepcopy(self.get_object(object_id))
        base = "{}_copy".format(object_id)
        existing = {str(value.get("id")) for value in self.obstacles}
        candidate = base
        suffix = 1
        while candidate in existing:
            candidate = "{}_{:02d}".format(base, suffix)
            suffix += 1
        source["id"] = candidate
        source["enabled"] = False
        source["confidence"] = "unset"
        source["placement_status"] = "provisional_unconfirmed"
        export = source.setdefault("export", {})
        export["object_name"] = candidate
        self.add_object(source)
        return source

    def reorder(self, object_id: str, new_index: int) -> None:
        obstacle = self.delete_object(object_id)
        bounded = max(0, min(int(new_index), len(self.obstacles)))
        self.obstacles.insert(bounded, obstacle)
        self.selected_object_id = object_id
        self.dirty = True

    def snapshot_document(self) -> Dict[str, Any]:
        return deepcopy(self.document)

    def restore_document(self, document: Dict[str, Any]) -> None:
        selected = self.selected_object_id
        self.document = deepcopy(document)
        identifiers = {str(value.get("id")) for value in self.obstacles}
        self.selected_object_id = selected if selected in identifiers else None
        self.object_visibility = {
            key: self.object_visibility.get(key, True) for key in identifiers
        }
        self.dirty = True

    def ui_document(self) -> Dict[str, Any]:
        return {
            "schema_version": "1.0",
            "camera": deepcopy(self.camera),
            "selected_object": self.selected_object_id,
            "viewport_mode": self.viewport_mode,
            "axis_constraint": self.axis_constraint,
            "reference_visibility": self.reference_visible,
            "grid_visibility": self.grid_visible,
            "show_disabled": self.show_disabled,
            "object_visibility": dict(sorted(self.object_visibility.items())),
            "snap_settings": self.snap.to_dict(),
            "panel_sizes": deepcopy(self.panel_sizes),
            "last_opened_scenario": str(self.source_path) if self.source_path else None,
        }
