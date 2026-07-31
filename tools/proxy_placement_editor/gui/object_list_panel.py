"""Obstacle list and destructive action controls."""

from .strings_ko import (
    confidence_label,
    material_label,
    semantic_label,
    status_label,
    tr,
)
from .section import make_section
from .metrics import scaled


class ObjectListPanel:
    def __init__(
        self,
        on_select,
        on_duplicate,
        on_delete,
        on_enable,
        on_up,
        on_down,
        on_visibility,
        heading_font_id=None,
        ui_scale=1.0,
        is_ctrl_down=None,
    ):
        from open3d.visualization import gui

        self.on_select, self.on_enable = on_select, on_enable
        self.is_ctrl_down = is_ctrl_down or (lambda: False)
        self.updating = False
        self.ids = []
        self.widget = make_section(gui, tr("objects"), heading_font_id, ui_scale)
        self.list = gui.ListView()
        self.list.set_max_visible_items(8)
        self.list.set_on_selection_changed(self._selected)
        actions = gui.Horiz(scaled(4, ui_scale))
        duplicate = gui.Button(tr("duplicate"))
        delete = gui.Button(tr("delete"))
        up = gui.Button(tr("move_up"))
        down = gui.Button(tr("move_down"))
        visibility = gui.Button(tr("show_hide"))
        duplicate.set_on_clicked(on_duplicate)
        delete.set_on_clicked(on_delete)
        up.set_on_clicked(on_up)
        down.set_on_clicked(on_down)
        visibility.set_on_clicked(on_visibility)
        actions.add_child(duplicate)
        actions.add_child(delete)
        actions.add_child(up)
        actions.add_child(down)
        actions.add_child(visibility)
        self.enabled = gui.Checkbox(tr("enabled_in_sionna"))
        self.enabled.set_on_checked(self._enabled_changed)
        self.widget.add_child(self.list)
        self.widget.add_child(self.enabled)
        self.widget.add_child(actions)

    def _selected(self, value, is_double_click):
        if not self.updating and 0 <= self.list.selected_index < len(self.ids):
            self.on_select(
                self.ids[self.list.selected_index],
                bool(self.is_ctrl_down()),
            )

    def _enabled_changed(self, checked):
        if not self.updating:
            self.on_enable(checked)

    def refresh(self, state, report):
        self.updating = True
        status = {value["id"]: value["status"] for value in report["objects"]}
        self.ids = [str(value.get("id")) for value in state.all_objects]
        self.list.set_items(
            [
                "{} {}·{} {} | {} | {} | {} | {}".format(
                    (
                        "●"
                        if value.get("id") == state.selected_object_id
                        else "✓"
                        if value.get("id") in state.selected_object_ids
                        else " "
                    ),
                    (
                        "RX"
                        if state.object_kind(str(value.get("id"))) == "rx"
                        else "활성" if value.get("enabled") else "비활성"
                    ),
                    "표시"
                    if state.object_visibility.get(str(value.get("id")), True)
                    else "숨김",
                    value.get("id"),
                    (
                        "보정 수신점"
                        if value.get("role") == "calibration"
                        else "Test 수신점"
                        if value.get("role") == "test"
                        else semantic_label(value.get("semantic_class", "?"))
                    ),
                    (
                        "점"
                        if state.object_kind(str(value.get("id"))) == "rx"
                        else material_label(value.get("material", {}).get("category", "?"))
                    ),
                    status_label(status.get(value.get("id"), "INCOMPLETE")),
                    (
                        value.get("point_id", "-")
                        if state.object_kind(str(value.get("id"))) == "rx"
                        else confidence_label(value.get("confidence", "unset"))
                    ),
                )
                for value in state.all_objects
            ]
        )
        if state.selected_object_id in self.ids:
            # Selection is rendered with ●/✓ prefixes instead of ListView's
            # single-row highlight. Resetting the native index also guarantees
            # that Ctrl-clicking the same row again emits a callback to toggle it.
            self.list.selected_index = -1
            is_obstacle = state.object_kind(state.selected_object_id) != "rx"
            self.enabled.enabled = is_obstacle
            self.enabled.checked = bool(
                state.get_object(state.selected_object_id).get("enabled")
            ) if is_obstacle else False
        else:
            self.list.selected_index = -1
            self.enabled.enabled = False
        self.updating = False
