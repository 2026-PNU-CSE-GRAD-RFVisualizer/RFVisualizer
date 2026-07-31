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
    marker_document: Optional[Dict[str, Any]] = None
    marker_source_path: Optional[Path] = None
    selected_object_id: Optional[str] = None
    selected_object_ids: List[str] = field(default_factory=list)
    object_visibility: Dict[str, bool] = field(default_factory=dict)
    viewport_mode: str = "select"
    axis_constraint: Optional[str] = None
    transform_space: str = "world"
    reference_point_size: float = 2.0
    point_cloud_visible: bool = True
    proxy_mesh_visible: bool = True
    pgsr_output_mesh_visible: bool = True
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
        self.marker_document = (
            deepcopy(self.marker_document) if self.marker_document is not None else None
        )
        for value in self.all_objects:
            self.object_visibility.setdefault(str(value.get("id")), True)
        identifiers = {str(value.get("id")) for value in self.all_objects}
        normalized = []
        for object_id in self.selected_object_ids:
            value = str(object_id)
            if value in identifiers and value not in normalized:
                normalized.append(value)
        if self.selected_object_id in identifiers:
            if self.selected_object_id in normalized:
                normalized.remove(self.selected_object_id)
            normalized.append(self.selected_object_id)
        self.selected_object_ids = normalized
        self.selected_object_id = normalized[-1] if normalized else None

    @property
    def obstacles(self) -> List[Dict[str, Any]]:
        scenario = self.document.get("scenario")
        if not isinstance(scenario, dict):
            raise EditorStateError("scenario mapping이 없습니다.")
        obstacles = scenario.setdefault("obstacles", [])
        if not isinstance(obstacles, list):
            raise EditorStateError("scenario.obstacles는 목록이어야 합니다.")
        return obstacles

    @property
    def receivers(self) -> List[Dict[str, Any]]:
        if self.marker_document is None:
            return []
        values = self.marker_document.setdefault("rx", [])
        if not isinstance(values, list):
            raise EditorStateError("TX/RX 문서의 rx는 목록이어야 합니다.")
        return values

    @property
    def all_objects(self) -> List[Dict[str, Any]]:
        return [*self.obstacles, *self.receivers]

    def object_kind(self, object_id: str) -> str:
        for obstacle in self.obstacles:
            if obstacle.get("id") == object_id:
                return "ap_tx" if isinstance(obstacle.get("rf_transmitter"), dict) else "obstacle"
        for receiver in self.receivers:
            if receiver.get("id") == object_id:
                return "rx"
        raise EditorStateError("객체 '{}'를 찾지 못했습니다.".format(object_id))

    def get_object(self, object_id: str) -> Dict[str, Any]:
        for value in self.all_objects:
            if value.get("id") == object_id:
                return value
        raise EditorStateError("객체 '{}'를 찾지 못했습니다.".format(object_id))

    def select(self, object_id: Optional[str], additive: bool = False) -> None:
        if object_id is not None:
            self.get_object(object_id)
        if not additive:
            self.selected_object_ids = [] if object_id is None else [object_id]
            self.selected_object_id = object_id
            return
        if object_id is None:
            return
        if object_id in self.selected_object_ids:
            self.selected_object_ids.remove(object_id)
            self.selected_object_id = (
                self.selected_object_ids[-1] if self.selected_object_ids else None
            )
            return
        self.selected_object_ids.append(object_id)
        self.selected_object_id = object_id

    def rename_selection(self, old_id: str, new_id: str) -> None:
        self.selected_object_ids = [
            new_id if value == old_id else value
            for value in self.selected_object_ids
        ]
        if self.selected_object_id == old_id:
            self.selected_object_id = new_id

    def add_object(self, obstacle: Dict[str, Any], index: Optional[int] = None) -> None:
        object_id = str(obstacle.get("id", ""))
        if not object_id or any(
            value.get("id") == object_id for value in self.all_objects
        ):
            raise EditorStateError(
                "Obstacle ID가 비어 있거나 중복됩니다: {}".format(object_id)
            )
        if index is None:
            self.obstacles.append(deepcopy(obstacle))
        else:
            self.obstacles.insert(index, deepcopy(obstacle))
        self.object_visibility[object_id] = True
        self.select(object_id)
        self.dirty = True

    def add_receiver(self, receiver: Dict[str, Any], index: Optional[int] = None) -> None:
        if self.marker_document is None:
            raise EditorStateError(
                "RX를 추가하려면 편집기를 --markers TX_RX_JSON과 함께 실행해야 합니다."
            )
        object_id = str(receiver.get("id", ""))
        if not object_id or any(
            value.get("id") == object_id for value in self.all_objects
        ):
            raise EditorStateError(
                "Marker ID가 비어 있거나 중복됩니다: {}".format(object_id)
            )
        if index is None:
            self.receivers.append(deepcopy(receiver))
        else:
            self.receivers.insert(index, deepcopy(receiver))
        self.object_visibility[object_id] = True
        self.select(object_id)
        self.dirty = True

    def delete_object(self, object_id: str) -> Dict[str, Any]:
        for index, obstacle in enumerate(self.obstacles):
            if obstacle.get("id") == object_id:
                removed = self.obstacles.pop(index)
                self.object_visibility.pop(object_id, None)
                if object_id in self.selected_object_ids:
                    self.selected_object_ids.remove(object_id)
                if self.selected_object_id == object_id:
                    self.selected_object_id = (
                        self.selected_object_ids[-1]
                        if self.selected_object_ids
                        else None
                    )
                self.dirty = True
                return removed
        for index, receiver in enumerate(self.receivers):
            if receiver.get("id") == object_id:
                removed = self.receivers.pop(index)
                self.object_visibility.pop(object_id, None)
                if object_id in self.selected_object_ids:
                    self.selected_object_ids.remove(object_id)
                if self.selected_object_id == object_id:
                    self.selected_object_id = (
                        self.selected_object_ids[-1]
                        if self.selected_object_ids
                        else None
                    )
                self.dirty = True
                return removed
        raise EditorStateError("객체 '{}'를 찾지 못했습니다.".format(object_id))

    def duplicate_object(self, object_id: str) -> Dict[str, Any]:
        source = deepcopy(self.get_object(object_id))
        base = "{}_copy".format(object_id)
        existing = {str(value.get("id")) for value in self.all_objects}
        candidate = base
        suffix = 1
        while candidate in existing:
            candidate = "{}_{:02d}".format(base, suffix)
            suffix += 1
        source["id"] = candidate
        if self.object_kind(object_id) == "rx":
            point_base = "{}_copy".format(source.get("point_id", object_id))
            existing_points = {str(value.get("point_id")) for value in self.receivers}
            point_candidate = point_base
            point_suffix = 1
            while point_candidate in existing_points:
                point_candidate = "{}_{:02d}".format(point_base, point_suffix)
                point_suffix += 1
            source["point_id"] = point_candidate
            source["name"] = "{} 복사본".format(source.get("name", object_id))
            self.add_receiver(source)
            return source
        source["enabled"] = False
        source["confidence"] = "unset"
        source["placement_status"] = "provisional_unconfirmed"
        export = source.setdefault("export", {})
        export["object_name"] = candidate
        self.add_object(source)
        return source

    def reorder(self, object_id: str, new_index: int) -> None:
        selected = list(self.selected_object_ids)
        primary = self.selected_object_id
        obstacle = self.delete_object(object_id)
        bounded = max(0, min(int(new_index), len(self.obstacles)))
        self.obstacles.insert(bounded, obstacle)
        identifiers = {str(value.get("id")) for value in self.all_objects}
        self.selected_object_ids = [
            value for value in selected if value in identifiers
        ]
        self.selected_object_id = (
            primary
            if primary in self.selected_object_ids
            else self.selected_object_ids[-1]
            if self.selected_object_ids
            else None
        )
        self.dirty = True

    def snapshot_document(self) -> Dict[str, Any]:
        if self.marker_document is not None:
            return {
                "__proxy_editor_bundle__": True,
                "scenario_document": deepcopy(self.document),
                "marker_document": deepcopy(self.marker_document),
            }
        return deepcopy(self.document)

    def restore_document(self, document: Dict[str, Any]) -> None:
        selected = list(self.selected_object_ids)
        primary = self.selected_object_id
        if document.get("__proxy_editor_bundle__") is True:
            self.document = deepcopy(document["scenario_document"])
            self.marker_document = deepcopy(document["marker_document"])
        else:
            self.document = deepcopy(document)
        identifiers = {str(value.get("id")) for value in self.all_objects}
        self.selected_object_ids = [
            value for value in selected if value in identifiers
        ]
        self.selected_object_id = (
            primary
            if primary in self.selected_object_ids
            else self.selected_object_ids[-1]
            if self.selected_object_ids
            else None
        )
        self.object_visibility = {
            key: self.object_visibility.get(key, True) for key in identifiers
        }
        self.dirty = True

    def ui_document(self) -> Dict[str, Any]:
        return {
            "schema_version": "1.0",
            "camera": deepcopy(self.camera),
            "selected_object": self.selected_object_id,
            "selected_objects": list(self.selected_object_ids),
            "viewport_mode": self.viewport_mode,
            "axis_constraint": self.axis_constraint,
            "transform_space": self.transform_space,
            "reference_point_size": self.reference_point_size,
            "layer_visibility": {
                "point_cloud": self.point_cloud_visible,
                "proxy_mesh": self.proxy_mesh_visible,
                "pgsr_output_mesh": self.pgsr_output_mesh_visible,
            },
            "grid_visibility": self.grid_visible,
            "show_disabled": self.show_disabled,
            "object_visibility": dict(sorted(self.object_visibility.items())),
            "snap_settings": self.snap.to_dict(),
            "panel_sizes": deepcopy(self.panel_sizes),
            "last_opened_scenario": str(self.source_path) if self.source_path else None,
        }
