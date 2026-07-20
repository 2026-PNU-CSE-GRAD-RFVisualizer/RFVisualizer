"""Obstacle list and destructive action controls."""

from .strings_ko import (
    confidence_label,
    material_label,
    semantic_label,
    status_label,
    tr,
)
from .section import make_section


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
    ):
        from open3d.visualization import gui

        self.on_select, self.on_enable = on_select, on_enable
        self.updating = False
        self.ids = []
        self.widget = make_section(gui, tr("objects"), heading_font_id)
        self.list = gui.ListView()
        self.list.set_max_visible_items(8)
        self.list.set_on_selection_changed(self._selected)
        actions = gui.Horiz(4)
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
            self.on_select(self.ids[self.list.selected_index])

    def _enabled_changed(self, checked):
        if not self.updating:
            self.on_enable(checked)

    def refresh(self, state, report):
        self.updating = True
        status = {value["id"]: value["status"] for value in report["objects"]}
        self.ids = [str(value.get("id")) for value in state.obstacles]
        self.list.set_items(
            [
                "{}·{} {} | {} | {} | {} | {}".format(
                    "활성" if value.get("enabled") else "비활성",
                    "표시"
                    if state.object_visibility.get(str(value.get("id")), True)
                    else "숨김",
                    value.get("id"),
                    semantic_label(value.get("semantic_class", "?")),
                    material_label(value.get("material", {}).get("category", "?")),
                    status_label(status.get(value.get("id"), "INCOMPLETE")),
                    confidence_label(value.get("confidence", "unset")),
                )
                for value in state.obstacles
            ]
        )
        if state.selected_object_id in self.ids:
            self.list.selected_index = self.ids.index(state.selected_object_id)
            self.enabled.enabled = True
            self.enabled.checked = bool(
                state.get_object(state.selected_object_id).get("enabled")
            )
        else:
            self.list.selected_index = -1
            self.enabled.enabled = False
        self.updating = False
