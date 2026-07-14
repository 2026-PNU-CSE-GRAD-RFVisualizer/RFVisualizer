"""Transform modes, axis constraints, and snap settings."""


class PlacementToolbar:
    def __init__(self, state, on_change):
        from open3d.visualization import gui

        self.gui, self.state, self.on_change = gui, state, on_change
        self.widget = gui.Horiz(4, gui.Margins(4, 4, 4, 4))
        for label, mode in (
            ("Select", "select"),
            ("G Move", "translate"),
            ("R Rotate", "rotate"),
            ("S Scale", "scale"),
        ):
            button = gui.Button(label)
            button.set_on_clicked(lambda m=mode: self.set_mode(m))
            self.widget.add_child(button)
        self.axis = gui.Combobox()
        for value in ("Free/XY", "X", "Y", "Z"):
            self.axis.add_item(value)
        self.axis.set_on_selection_changed(self._axis)
        self.snap = gui.Checkbox("Snap")
        self.snap.checked = state.snap.enabled
        self.snap.set_on_checked(self._snap)
        self.widget.add_child(self.axis)
        self.widget.add_child(self.snap)
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
            ("Move m", self.translation),
            ("Rotate °", self.rotation),
            ("Size m", self.size),
        ):
            self.widget.add_child(gui.Label(label))
            self.widget.add_child(combo)
        self.fps_status = gui.Label("FPS: hold RMB + WASD")
        self.fps_status.text_color = gui.Color(0.6, 0.65, 0.72)
        self.widget.add_child(self.fps_status)

    def set_fps_active(self, active):
        if active:
            self.fps_status.text = "FPS: ACTIVE · WASD / Shift"
            self.fps_status.text_color = self.gui.Color(0.25, 0.9, 0.45)
        else:
            self.fps_status.text = "FPS: hold RMB + WASD"
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

    def _axis(self, text, index):
        self.state.axis_constraint = None if index == 0 else text.lower()
        self.on_change()

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
