"""Transform modes, axis constraints, and snap settings."""

from .strings_ko import tr
from .metrics import scaled, scaled_margins


class PlacementToolbar:
    def __init__(self, state, on_change, on_point_size, ui_scale=1.0):
        from open3d.visualization import gui

        self.gui, self.state, self.on_change = gui, state, on_change
        self.on_point_size = on_point_size
        self.updating = False
        self.widget = gui.Vert(
            scaled(3, ui_scale),
            scaled_margins(gui, 4, 4, 4, 4, ui_scale),
        )
        modes = gui.Horiz(scaled(4, ui_scale))
        for label, mode in (
            (tr("select"), "select"),
            ("G " + tr("move"), "translate"),
            ("R " + tr("rotate"), "rotate"),
            ("S " + tr("scale"), "scale"),
        ):
            button = gui.Button(label)
            button.set_on_clicked(lambda m=mode: self.set_mode(m))
            modes.add_child(button)
        self.space = gui.Button("")
        self.space.set_on_clicked(self._toggle_space)
        self._refresh_space_label()
        modes.add_child(self.space)
        modes.add_child(gui.Label(tr("display_layers")))
        self.point_cloud = gui.Checkbox(tr("display_point_cloud"))
        self.point_cloud.checked = state.point_cloud_visible
        self.point_cloud.set_on_checked(self._point_cloud_visibility)
        modes.add_child(self.point_cloud)
        self.proxy_mesh = gui.Checkbox(tr("display_proxy_mesh"))
        self.proxy_mesh.checked = state.proxy_mesh_visible
        self.proxy_mesh.set_on_checked(self._proxy_mesh_visibility)
        modes.add_child(self.proxy_mesh)
        self.pgsr_output_mesh = gui.Checkbox(tr("display_pgsr_output_mesh"))
        self.pgsr_output_mesh.checked = state.pgsr_output_mesh_visible
        self.pgsr_output_mesh.set_on_checked(self._pgsr_output_mesh_visibility)
        modes.add_child(self.pgsr_output_mesh)
        modes.add_child(gui.Label(tr("point_size")))
        self.point_size = gui.Slider(gui.Slider.DOUBLE)
        self.point_size.set_limits(1.0, 12.0)
        self.point_size.double_value = float(state.reference_point_size)
        self.point_size.set_on_value_changed(self._point_size)
        self.point_size_label = gui.Label("{:.1f}px".format(state.reference_point_size))
        modes.add_child(self.point_size)
        modes.add_child(self.point_size_label)

        settings = gui.Horiz(scaled(4, ui_scale))
        self.snap = gui.Checkbox(tr("snap"))
        self.snap.checked = state.snap.enabled
        self.snap.set_on_checked(self._snap)
        settings.add_child(self.snap)
        self.translation = self._increment_combo(
            (0.01, 0.05, 0.1, 0.5), state.snap.translation_m, self._translation
        )
        self.rotation = self._increment_combo(
            (1.0, 5.0, 15.0, 45.0), state.snap.rotation_deg, self._rotation
        )
        self.size = self._increment_combo(
            (0.01, 0.05, 0.1, 0.5), state.snap.size_m, self._size
        )
        for label, combo in (
            (tr("move_unit"), self.translation),
            (tr("rotation_unit"), self.rotation),
            (tr("size_unit"), self.size),
        ):
            settings.add_child(gui.Label(label))
            settings.add_child(combo)
        self.fps_status = gui.Label(tr("fps_idle"))
        self.fps_status.text_color = gui.Color(0.6, 0.65, 0.72)
        settings.add_child(self.fps_status)
        self.widget.add_child(modes)
        self.widget.add_child(settings)

    def set_fps_active(self, active):
        if active:
            self.fps_status.text = tr("fps_active")
            self.fps_status.text_color = self.gui.Color(0.25, 0.9, 0.45)
        else:
            self.fps_status.text = tr("fps_idle")
            self.fps_status.text_color = self.gui.Color(0.6, 0.65, 0.72)

    def _increment_combo(self, values, selected, callback):
        combo = self.gui.Combobox()
        for value in values:
            combo.add_item(str(value))
        combo.selected_index = list(values).index(float(selected))
        combo.set_on_selection_changed(callback)
        return combo

    def set_mode(self, mode):
        self.state.viewport_mode = mode
        self.on_change()

    def refresh(self):
        self.updating = True
        try:
            self._refresh_space_label()
            self.point_cloud.checked = self.state.point_cloud_visible
            self.proxy_mesh.checked = self.state.proxy_mesh_visible
            self.pgsr_output_mesh.checked = self.state.pgsr_output_mesh_visible
            self.point_size.double_value = float(self.state.reference_point_size)
            self.point_size_label.text = "{:.1f}px".format(
                self.state.reference_point_size
            )
        finally:
            self.updating = False

    def _refresh_space_label(self):
        self.space.text = "{}: {}".format(
            tr("coordinate_space"),
            tr("space_local")
            if self.state.transform_space == "local"
            else tr("space_world"),
        )

    def _toggle_space(self):
        self.state.transform_space = (
            "local" if self.state.transform_space == "world" else "world"
        )
        self._refresh_space_label()
        self.on_change()

    def _point_cloud_visibility(self, checked):
        if self.updating:
            return
        self.state.point_cloud_visible = bool(checked)
        self.on_change()

    def _proxy_mesh_visibility(self, checked):
        if self.updating:
            return
        self.state.proxy_mesh_visible = bool(checked)
        self.on_change()

    def _pgsr_output_mesh_visibility(self, checked):
        if self.updating:
            return
        self.state.pgsr_output_mesh_visible = bool(checked)
        self.on_change()

    def _point_size(self, value):
        if self.updating:
            return
        self.state.reference_point_size = float(value)
        self.point_size_label.text = "{:.1f}px".format(value)
        self.on_point_size(value)

    def _snap(self, checked):
        self.state.snap.enabled = bool(checked)
        self.on_change()

    def _translation(self, text, index):
        self.state.snap.translation_m = float(text)
        self.on_change()

    def _rotation(self, text, index):
        self.state.snap.rotation_deg = float(text)
        self.on_change()

    def _size(self, text, index):
        self.state.snap.size_m = float(text)
        self.on_change()
