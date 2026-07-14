"""Exact numeric obstacle properties; callbacks update the shared YAML state."""

from __future__ import annotations

import numpy as np

from tools.proxy_placement_editor.command_stack import (
    ChangeMaterialCommand,
    ChangePropertyCommand,
)
from tools.proxy_placement_editor.transform_controller import set_numeric_geometry


def _values(value, names, default):
    if value is None:
        return list(default)
    if isinstance(value, dict):
        return [
            float(value.get(name, default[index])) for index, name in enumerate(names)
        ]
    return [float(item) for item in value]


class PropertiesPanel:
    def __init__(self, core, on_change):
        from open3d.visualization import gui

        self.gui, self.core, self.on_change = gui, core, on_change
        self.updating = False
        self.widget = gui.CollapsableVert("Properties", 0.25, gui.Margins(6, 6, 6, 6))
        self.identity = {}
        for key, label in (
            ("id", "Object ID"),
            ("display_name", "Display name"),
            ("semantic_class", "Semantic class"),
            ("purpose", "Purpose"),
            ("measurement_source", "Measurement source"),
            ("notes", "Notes"),
        ):
            self.widget.add_child(gui.Label(label))
            edit = gui.TextEdit()
            edit.set_on_value_changed(lambda value, k=key: self._identity(k, value))
            self.identity[key] = edit
            self.widget.add_child(edit)
        self.confidence = gui.Combobox()
        for value in ("unset", "estimated_from_reference", "measured", "synthetic"):
            self.confidence.add_item(value)
        self.confidence.set_on_selection_changed(
            lambda value, index: self._identity("confidence", value)
        )
        self.widget.add_child(gui.Label("Confidence"))
        self.widget.add_child(self.confidence)
        self.physical = gui.Checkbox("Physical object")
        self.physical.set_on_checked(
            lambda value: self._identity("physical_object", bool(value))
        )
        self.widget.add_child(self.physical)

        self.geometry_type = gui.Combobox()
        for value in ("box", "thin_panel", "mesh"):
            self.geometry_type.add_item(value)
        self.geometry_type.set_on_selection_changed(self._geometry_type)
        self.anchor_mode = gui.Combobox()
        for value in ("center", "bottom_center", "floor_at_xy", "explicit_transform"):
            self.anchor_mode.add_item(value)
        self.anchor_mode.set_on_selection_changed(self._anchor_mode)
        self.floor_policy = gui.Combobox()
        for value in ("anchor_point", "minimum_bottom_vertex_clearance"):
            self.floor_policy.add_item(value)
        self.floor_policy.set_on_selection_changed(self._floor_policy)
        self.floor_clearance = gui.NumberEdit(gui.NumberEdit.DOUBLE)
        self.floor_clearance.decimal_precision = 6
        self.floor_clearance.set_limits(0.0, 100.0)
        self.floor_clearance.set_on_value_changed(self._floor_clearance)
        for label, widget in (
            ("Geometry type", self.geometry_type),
            ("Anchor mode", self.anchor_mode),
            ("Floor contact policy", self.floor_policy),
            ("Floor clearance m", self.floor_clearance),
        ):
            self.widget.add_child(gui.Label(label))
            self.widget.add_child(widget)

        grid = gui.VGrid(4, 3)
        grid.add_child(gui.Label(""))
        [grid.add_child(gui.Label(value)) for value in ("X", "Y", "Z")]
        self.position, self.size, self.rotation = [], [], []
        for label, target, callback in (
            ("Position m", self.position, self._numeric),
            ("Size m", self.size, self._numeric),
            ("Roll/Pitch/Yaw", self.rotation, self._numeric),
        ):
            grid.add_child(gui.Label(label))
            for _ in range(3):
                edit = gui.NumberEdit(gui.NumberEdit.DOUBLE)
                edit.decimal_precision = 6
                edit.set_limits(-10000.0 if label != "Size m" else 0.001, 10000.0)
                edit.set_on_value_changed(callback)
                target.append(edit)
                grid.add_child(edit)
        self.widget.add_child(grid)
        self.material = gui.Combobox()
        for value in ("concrete", "wood", "metal", "glass"):
            self.material.add_item(value)
        self.material.set_on_selection_changed(self._material)
        self.widget.add_child(gui.Label("Material category"))
        self.widget.add_child(self.material)
        self.material_thickness = gui.NumberEdit(gui.NumberEdit.DOUBLE)
        self.material_thickness.decimal_precision = 6
        self.material_thickness.set_limits(0.000001, 100.0)
        self.material_thickness.set_on_value_changed(self._material_numbers)
        self.scattering = gui.NumberEdit(gui.NumberEdit.DOUBLE)
        self.scattering.decimal_precision = 6
        self.scattering.set_limits(0.0, 1.0)
        self.scattering.set_on_value_changed(self._material_numbers)
        self.widget.add_child(gui.Label("Material thickness m"))
        self.widget.add_child(self.material_thickness)
        self.widget.add_child(gui.Label("Scattering coefficient"))
        self.widget.add_child(self.scattering)
        self.widget.add_child(
            gui.Label("Fallback policy: none (strict Phase 2-B resolution)")
        )
        self.transforms = gui.Label("Local/world transform: select a renderable object")
        self.widget.add_child(self.transforms)
        self.set_enabled(False)

    def set_enabled(self, enabled):
        for value in (
            list(self.identity.values())
            + self.position
            + self.size
            + self.rotation
            + [self.confidence, self.material]
            + [
                self.physical,
                self.geometry_type,
                self.anchor_mode,
                self.floor_policy,
                self.floor_clearance,
                self.material_thickness,
                self.scattering,
            ]
        ):
            value.enabled = bool(enabled)

    def refresh(self, selected, report):
        self.updating = True
        try:
            if not selected:
                self.set_enabled(False)
                return
            obstacle = self.core.state.get_object(selected)
            self.set_enabled(True)
            for key, edit in self.identity.items():
                edit.text_value = str(obstacle.get(key, ""))
            confidence = str(obstacle.get("confidence", "unset"))
            self.physical.checked = bool(obstacle.get("physical_object", True))
            values = [
                self.confidence.get_item(index)
                for index in range(self.confidence.number_of_items)
            ]
            self.confidence.selected_index = (
                values.index(confidence) if confidence in values else 0
            )
            geometry = obstacle.get("geometry", {})
            anchor = geometry.get("anchor", {})
            mode = anchor if isinstance(anchor, str) else anchor.get("mode", "center")
            geometry_types = [
                self.geometry_type.get_item(index)
                for index in range(self.geometry_type.number_of_items)
            ]
            geometry_type = geometry.get("type", "box")
            self.geometry_type.selected_index = (
                geometry_types.index(geometry_type)
                if geometry_type in geometry_types
                else 0
            )
            modes = [
                self.anchor_mode.get_item(index)
                for index in range(self.anchor_mode.number_of_items)
            ]
            self.anchor_mode.selected_index = modes.index(mode) if mode in modes else 0
            contact = (
                anchor.get("floor_contact_policy", {})
                if isinstance(anchor, dict)
                else {}
            )
            if isinstance(contact, str):
                policy, clearance = contact, 0.0
            else:
                policy = contact.get("type", "anchor_point")
                clearance = contact.get(
                    "clearance_m", geometry.get("floor_clearance_m", 0.0)
                )
            self.floor_policy.selected_index = 0 if policy == "anchor_point" else 1
            self.floor_clearance.double_value = float(clearance)
            self.floor_policy.enabled = mode == "floor_at_xy"
            self.floor_clearance.enabled = mode == "floor_at_xy"
            position_names = ("x", "y") if mode == "floor_at_xy" else ("x", "y", "z")
            position_defaults = (0.0, 0.0) if mode == "floor_at_xy" else (0.0, 0.0, 0.0)
            position = _values(
                geometry.get("position_m"), position_names, position_defaults
            )
            if len(position) == 2:
                position.append(0.0)
            size = _values(geometry.get("size_m"), ("x", "y", "z"), (1.0, 1.0, 1.0))
            rotation = _values(
                geometry.get("rotation_deg"), ("roll", "pitch", "yaw"), (0.0, 0.0, 0.0)
            )
            for edit, value in zip(self.position, position):
                edit.double_value = value
            self.position[2].enabled = mode != "floor_at_xy"
            for edit, value in zip(self.size, size):
                edit.double_value = value
            for edit, value in zip(self.rotation, rotation):
                edit.double_value = value
            category = str(obstacle.get("material", {}).get("category", "concrete"))
            material = obstacle.get("material", {})
            self.material_thickness.double_value = float(
                material.get("thickness_m", 0.1)
            )
            self.scattering.double_value = float(
                material.get("scattering_coefficient", 0.0)
            )
            categories = [
                self.material.get_item(index)
                for index in range(self.material.number_of_items)
            ]
            self.material.selected_index = (
                categories.index(category) if category in categories else 0
            )
            record = next(
                (value for value in report["objects"] if value["id"] == selected), None
            )
            if record and record.get("renderable"):
                metric = np.asarray(record["metric_transform"])
                scene = np.asarray(record["scene_transform"])
                self.transforms.text = (
                    "Metric T:\n{}\nScene T:\n{}\nRound trip: {:.3e}".format(
                        np.array2string(metric, precision=5, suppress_small=True),
                        np.array2string(scene, precision=5, suppress_small=True),
                        record["coordinate_round_trip"]["maximum_error"],
                    )
                )
            else:
                self.transforms.text = "Object has incomplete geometry"
        finally:
            self.updating = False

    def _identity(self, key, value):
        if self.updating or not self.core.state.selected_object_id:
            return
        object_id = self.core.state.selected_object_id
        if key == "id":
            try:
                self.core.rename(object_id, value)
                self.on_change()
            except ValueError:
                self.refresh(object_id, self.core.validate())
            return
        obstacle = dict(self.core.state.get_object(object_id))
        obstacle[key] = value
        self.core.replace_object(object_id, obstacle, ChangePropertyCommand)
        self.on_change()

    def _numeric(self, unused):
        if self.updating or not self.core.state.selected_object_id:
            return
        object_id = self.core.state.selected_object_id
        obstacle = self.core.state.get_object(object_id)
        geometry = obstacle.get("geometry", {})
        anchor = geometry.get("anchor", {})
        mode = anchor if isinstance(anchor, str) else anchor.get("mode", "center")
        position = [
            value.double_value
            for value in self.position[: 2 if mode == "floor_at_xy" else 3]
        ]
        size = [value.double_value for value in self.size]
        rotation = [value.double_value for value in self.rotation]
        try:
            updated = set_numeric_geometry(
                obstacle, position=position, size=size, rotation=rotation
            )
            self.core.replace_object(object_id, updated, ChangePropertyCommand)
            self.on_change()
        except ValueError:
            self.refresh(object_id, self.core.validate())

    def _material(self, value, index):
        if self.updating or not self.core.state.selected_object_id:
            return
        object_id = self.core.state.selected_object_id
        obstacle = dict(self.core.state.get_object(object_id))
        material = dict(obstacle.get("material", {}))
        material.update({"source": "sionna_preset", "category": value, "preset": value})
        obstacle["material"] = material
        self.core.replace_object(object_id, obstacle, ChangeMaterialCommand)
        self.on_change()

    def _geometry_type(self, value, index):
        if self.updating or not self.core.state.selected_object_id:
            return
        object_id = self.core.state.selected_object_id
        obstacle = dict(self.core.state.get_object(object_id))
        geometry = dict(obstacle.get("geometry", {}))
        geometry["type"] = value
        obstacle["geometry"] = geometry
        self.core.replace_object(object_id, obstacle, ChangePropertyCommand)
        self.on_change()

    def _anchor_mode(self, value, index):
        if self.updating or not self.core.state.selected_object_id:
            return
        object_id = self.core.state.selected_object_id
        obstacle = dict(self.core.state.get_object(object_id))
        geometry = dict(obstacle.get("geometry", {}))
        current_anchor = geometry.get("anchor", {})
        current_mode = (
            current_anchor
            if isinstance(current_anchor, str)
            else current_anchor.get("mode", "center")
        )
        names = ("x", "y") if current_mode == "floor_at_xy" else ("x", "y", "z")
        defaults = (0.0, 0.0) if current_mode == "floor_at_xy" else (0.0, 0.0, 0.0)
        position = _values(geometry.get("position_m"), names, defaults)
        if value == "floor_at_xy":
            geometry["position_m"] = {"x": position[0], "y": position[1]}
            geometry["anchor"] = {
                "mode": value,
                "floor_contact_policy": {
                    "type": "minimum_bottom_vertex_clearance",
                    "clearance_m": 0.01,
                },
            }
        else:
            if len(position) == 2:
                record = next(
                    (
                        item
                        for item in self.core.validate()["objects"]
                        if item["id"] == object_id and item.get("renderable")
                    ),
                    None,
                )
                z = (
                    float(np.mean(np.asarray(record["metric_vertices"])[:, 2]))
                    if record
                    else 0.0
                )
                position.append(z)
            geometry["position_m"] = {
                "x": position[0],
                "y": position[1],
                "z": position[2],
            }
            geometry["anchor"] = {"mode": value}
        obstacle["geometry"] = geometry
        self.core.replace_object(object_id, obstacle, ChangePropertyCommand)
        self.on_change()

    def _floor_policy(self, value, index):
        if self.updating or not self.core.state.selected_object_id:
            return
        self._set_floor_contact(value, self.floor_clearance.double_value)

    def _floor_clearance(self, value):
        if self.updating or not self.core.state.selected_object_id:
            return
        self._set_floor_contact(self.floor_policy.selected_text, value)

    def _set_floor_contact(self, policy, clearance):
        object_id = self.core.state.selected_object_id
        obstacle = dict(self.core.state.get_object(object_id))
        geometry = dict(obstacle.get("geometry", {}))
        anchor = geometry.get("anchor", {})
        anchor = {"mode": anchor} if isinstance(anchor, str) else dict(anchor)
        anchor["floor_contact_policy"] = {
            "type": policy,
            "clearance_m": float(clearance),
        }
        geometry["anchor"] = anchor
        if policy != "anchor_point":
            geometry.pop("floor_clearance_m", None)
        obstacle["geometry"] = geometry
        self.core.replace_object(object_id, obstacle, ChangePropertyCommand)
        self.on_change()

    def _material_numbers(self, unused):
        if self.updating or not self.core.state.selected_object_id:
            return
        object_id = self.core.state.selected_object_id
        obstacle = dict(self.core.state.get_object(object_id))
        material = dict(obstacle.get("material", {}))
        material["thickness_m"] = self.material_thickness.double_value
        material["scattering_coefficient"] = self.scattering.double_value
        obstacle["material"] = material
        self.core.replace_object(object_id, obstacle, ChangeMaterialCommand)
        self.on_change()
