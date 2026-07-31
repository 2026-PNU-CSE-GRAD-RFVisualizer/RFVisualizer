"""AP/TX와 RX를 같은 편집기에서 수정하는 전파 객체 속성 패널."""

from __future__ import annotations

from copy import deepcopy

from tools.proxy_placement_editor.command_stack import ChangePropertyCommand

from .section import make_section
from .metrics import scaled
from .strings_ko import tr


class RadioPropertiesPanel:
    def __init__(self, core, on_change, heading_font_id=None, ui_scale=1.0):
        from open3d.visualization import gui

        self.gui, self.core, self.on_change = gui, core, on_change
        self.updating = False
        self.widget = make_section(
            gui, tr("radio_properties"), heading_font_id, ui_scale
        )
        self.kind = gui.Label("전파 객체를 선택하세요.")
        self.widget.add_child(self.kind)
        self.rows = {}

        def text_row(key, label, callback):
            label_widget = gui.Label(label)
            edit = gui.TextEdit()
            edit.set_on_value_changed(callback)
            self.widget.add_child(label_widget)
            self.widget.add_child(edit)
            self.rows[key] = (label_widget, edit)
            return edit

        self.marker_id = text_row("id", tr("object_id"), self._identity)
        self.name = text_row("name", tr("marker_name"), self._name)
        self.point_id = text_row("point_id", tr("point_id"), self._point_id)

        role_label = gui.Label(tr("receiver_role"))
        self.role = gui.Combobox()
        self.role.add_item("보정(calibration)")
        self.role.add_item("평가(test)")
        self.role.set_on_selection_changed(self._role)
        self.widget.add_child(role_label)
        self.widget.add_child(self.role)
        self.rows["role"] = (role_label, self.role)

        position_label = gui.Label(tr("position"))
        position_row = gui.Horiz(scaled(4, ui_scale))
        self.position = []
        for axis in ("X", "Y", "Z"):
            position_row.add_child(gui.Label(axis))
            edit = gui.NumberEdit(gui.NumberEdit.DOUBLE)
            edit.decimal_precision = 6
            edit.set_limits(-10000.0, 10000.0)
            edit.set_on_value_changed(self._position)
            position_row.add_child(edit)
            self.position.append(edit)
        self.widget.add_child(position_label)
        self.widget.add_child(position_row)
        self.rows["position"] = (position_label, position_row)

        frequency_label = gui.Label(tr("frequency_hz"))
        self.frequency = gui.NumberEdit(gui.NumberEdit.DOUBLE)
        self.frequency.decimal_precision = 3
        self.frequency.set_limits(1.0, 1.0e15)
        self.frequency.set_on_value_changed(self._transmitter)
        power_label = gui.Label(tr("power_dbm"))
        self.power = gui.NumberEdit(gui.NumberEdit.DOUBLE)
        self.power.decimal_precision = 3
        self.power.set_limits(-300.0, 300.0)
        self.power.set_on_value_changed(self._transmitter)
        for key, label_widget, edit in (
            ("frequency", frequency_label, self.frequency),
            ("power", power_label, self.power),
        ):
            self.widget.add_child(label_widget)
            self.widget.add_child(edit)
            self.rows[key] = (label_widget, edit)
        self.refresh(None)

    def _show(self, key, visible):
        for widget in self.rows[key]:
            widget.visible = bool(visible)
            widget.enabled = bool(visible)

    def set_enabled(self, enabled):
        for widgets in self.rows.values():
            for widget in widgets:
                widget.enabled = bool(enabled and widget.visible)

    def refresh(self, selected):
        self.updating = True
        try:
            if not selected:
                self.kind.text = "전파 객체를 선택하세요."
                for key in self.rows:
                    self._show(key, False)
                return
            kind = self.core.state.object_kind(selected)
            if kind not in {"ap_tx", "rx"}:
                self.kind.text = "선택한 객체에는 전파 속성이 없습니다."
                for key in self.rows:
                    self._show(key, False)
                return
            value = self.core.state.get_object(selected)
            is_rx = kind == "rx"
            self.kind.text = "RX 측정점" if is_rx else "물리 객체와 결합된 AP / TX"
            for key in ("id", "name", "point_id", "role", "position"):
                self._show(key, is_rx)
            for key in ("frequency", "power"):
                self._show(key, not is_rx)
            if is_rx:
                self.marker_id.text_value = str(value.get("id", ""))
                self.name.text_value = str(value.get("name", ""))
                self.point_id.text_value = str(value.get("point_id", ""))
                self.role.selected_index = 0 if value.get("role") == "calibration" else 1
                for edit, coordinate in zip(self.position, value.get("position_m", [0, 0, 0])):
                    edit.double_value = float(coordinate)
            else:
                transmitter = value.get("rf_transmitter", {})
                self.frequency.double_value = float(
                    transmitter.get("frequency_hz", 2.4e9)
                )
                self.power.double_value = float(transmitter.get("power_dbm", 20.0))
        finally:
            self.updating = False

    def _replace_rx(self, **changes):
        if self.updating or not self.core.state.selected_object_id:
            return
        object_id = self.core.state.selected_object_id
        if self.core.state.object_kind(object_id) != "rx":
            return
        value = deepcopy(self.core.state.get_object(object_id))
        value.update(changes)
        self.core.replace_object(object_id, value, ChangePropertyCommand)
        self.on_change()

    def _identity(self, value):
        if self.updating or not self.core.state.selected_object_id:
            return
        object_id = self.core.state.selected_object_id
        try:
            self.core.rename(object_id, value)
            self.on_change()
        except ValueError:
            self.refresh(object_id)

    def _name(self, value):
        self._replace_rx(name=str(value))

    def _point_id(self, value):
        self._replace_rx(point_id=str(value))

    def _role(self, unused_value, index):
        self._replace_rx(role="calibration" if index == 0 else "test")

    def _position(self, unused):
        self._replace_rx(position_m=[edit.double_value for edit in self.position])

    def _transmitter(self, unused):
        if self.updating or not self.core.state.selected_object_id:
            return
        object_id = self.core.state.selected_object_id
        if self.core.state.object_kind(object_id) != "ap_tx":
            return
        value = deepcopy(self.core.state.get_object(object_id))
        value["rf_transmitter"] = {
            "frequency_hz": self.frequency.double_value,
            "power_dbm": self.power.double_value,
        }
        self.core.replace_object(object_id, value, ChangePropertyCommand)
        self.on_change()
