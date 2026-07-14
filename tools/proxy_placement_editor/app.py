"""Open3D 0.19 desktop application for interactive proxy placement."""

from __future__ import annotations

import math
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

from .command_stack import ResizeObjectCommand, TransformObjectCommand
from .external_commands import ExternalCommandRunner, ExternalEnvironment
from .fps_camera_controller import FpsCameraController, FpsNavigationSettings
from .picking import nearest_obstacle_hit, ray_plane_intersection
from .transform_controller import resize_obstacle, rotate_obstacle, translate_obstacle
from .gui.candidate_panel import CandidatePanel
from .gui.object_list_panel import ObjectListPanel
from .gui.properties_panel import PropertiesPanel
from .gui.shortcuts import shortcut_text
from .gui.toolbar import PlacementToolbar
from .gui.validation_panel import ValidationPanel
from .gui.viewport import PlacementViewport


PROVISIONAL_WARNING = (
    "PROVISIONAL GEOMETRY\n현재 Metric scale 및 proxy placement는 현장 실측으로 검증되지 않았습니다.\n"
    "이 장면의 Sionna 결과를 실제 RSSI 정확도로 해석하지 마세요."
)


class ProxyPlacementApp:
    def __init__(
        self,
        core,
        editor_config: Dict[str, Any],
        experiment: Optional[Path] = None,
        width: int = 1500,
        height: int = 920,
    ):
        import open3d as o3d
        from open3d.visualization import gui

        self.o3d, self.gui, self.core = o3d, gui, core
        self.experiment = Path(experiment).resolve() if experiment else None
        app = gui.Application.instance
        app.initialize()
        self.window = app.create_window(
            "RFVisualizer Phase 2-C Proxy Placement", width, height
        )
        self.viewport = PlacementViewport(self.window.renderer, core)
        self.toolbar = PlacementToolbar(core.state, self.refresh)
        self.candidate_panel = CandidatePanel(core, self._add_candidate)
        self.object_panel = ObjectListPanel(
            self._select,
            self._duplicate,
            self._delete,
            self._enable,
            lambda: self._reorder(-1),
            lambda: self._reorder(1),
            self._toggle_visibility,
        )
        self.properties_panel = PropertiesPanel(core, self.refresh)
        self.validation_panel = ValidationPanel()
        self.warning = gui.Label(PROVISIONAL_WARNING)
        self.warning.text_color = gui.Color(1.0, 0.38, 0.18)
        self.side = gui.ScrollableVert(4, gui.Margins(8, 8, 8, 8))
        self.side.add_child(self.warning)
        self.side.add_child(self.candidate_panel.widget)
        self.side.add_child(self.object_panel.widget)
        self.side.add_child(self.properties_panel.widget)
        self.side.add_child(self.validation_panel.widget)
        self._add_actions()
        shortcuts = gui.CollapsableVert("Shortcuts", 0.25, gui.Margins(6, 6, 6, 6))
        shortcuts.add_child(gui.Label(shortcut_text()))
        self.side.add_child(shortcuts)
        self.window.add_child(self.toolbar.widget)
        self.window.add_child(self.viewport.widget)
        self.window.add_child(self.side)
        self.window.set_on_layout(self._layout)
        self.viewport.widget.set_on_mouse(self._on_mouse)
        self.window.set_on_key(self._on_key)
        self.window.set_on_tick_event(self._on_tick)
        self.window.set_on_close(self._on_close)
        environment = editor_config["external_commands"]["sionna_environment"]
        self.runner = ExternalCommandRunner(
            ExternalEnvironment(environment["type"], environment.get("name", "")),
            Path(__file__).resolve().parents[2],
        )
        self._drag = None
        self._keys = {"ctrl": False, "shift": False}
        self.fps_camera = FpsCameraController(
            FpsNavigationSettings.from_dict(
                editor_config.get("navigation", {}).get("fps", {})
            )
        )
        self._fps_exit_pending = False
        self._last_autosave = time.monotonic()
        self._autosave_seconds = int(
            editor_config.get("autosave", {}).get("interval_seconds", 60)
        )
        self.refresh()

    def _add_actions(self):
        gui = self.gui
        actions = gui.CollapsableVert(
            "Scenario & Sionna", 0.25, gui.Margins(6, 6, 6, 6)
        )
        row1, row2 = gui.Horiz(4), gui.Horiz(4)
        for label, callback, row in (
            ("Validate", self._validate, row1),
            ("Save", self._save, row1),
            ("Save As", self._save_as, row1),
            ("Export Preview", self._preview, row2),
            ("Build Sionna Scene", self._build, row2),
            ("Run A/B", self._run_ab, row2),
            ("Open Output", self._open_output, row2),
        ):
            button = gui.Button(label)
            button.set_on_clicked(callback)
            row.add_child(button)
        actions.add_child(row1)
        actions.add_child(row2)
        self.side.add_child(actions)

    def _layout(self, context):
        rect = self.window.content_rect
        toolbar_height = 42
        side_width = int(self.core.state.panel_sizes.get("side_panel_width", 410.0))
        self.toolbar.widget.frame = self.gui.Rect(
            rect.x, rect.y, rect.width, toolbar_height
        )
        self.viewport.widget.frame = self.gui.Rect(
            rect.x,
            rect.y + toolbar_height,
            rect.width - side_width,
            rect.height - toolbar_height,
        )
        self.side.frame = self.gui.Rect(
            rect.get_right() - side_width,
            rect.y + toolbar_height,
            side_width,
            rect.height - toolbar_height,
        )

    def refresh(self):
        report = self.core.validate()
        self.viewport.refresh(report)
        self.object_panel.refresh(self.core.state, report)
        self.properties_panel.refresh(self.core.state.selected_object_id, report)
        self.validation_panel.refresh(report, self.core.state.selected_object_id)
        self.window.post_redraw()

    def _select(self, object_id):
        self.core.state.select(object_id)
        self.refresh()

    def _add_candidate(self, candidate_id):
        self.core.add_candidate(candidate_id)
        self.refresh()

    def _duplicate(self):
        if self.core.state.selected_object_id:
            self.core.duplicate(self.core.state.selected_object_id)
            self.refresh()

    def _delete(self):
        if self.core.state.selected_object_id:
            self.core.delete(self.core.state.selected_object_id)
            self.refresh()

    def _enable(self, checked):
        if self.core.state.selected_object_id:
            try:
                self.core.set_enabled(self.core.state.selected_object_id, checked)
                self.refresh()
            except Exception as exc:
                self._message("Cannot enable object", str(exc))
                self.refresh()

    def _reorder(self, offset):
        if self.core.state.selected_object_id:
            self.core.reorder(self.core.state.selected_object_id, offset)
            self.refresh()

    def _toggle_visibility(self):
        object_id = self.core.state.selected_object_id
        if object_id:
            self.core.state.object_visibility[
                object_id
            ] = not self.core.state.object_visibility.get(object_id, True)
            self.refresh()

    def _message(self, title, text):
        self.window.show_message_box(title, text)

    def _validate(self):
        report = self.core.validate()
        self.refresh()
        self._message(
            "Scenario validation",
            "PASS"
            if report["success"]
            else "Enabled object errors:\n{}".format(report["enabled_errors"]),
        )

    def _save(self):
        try:
            result = self.core.save()
            self.validation_panel.append_log("Saved: {}".format(result["scenario"]))
            self.refresh()
        except Exception as exc:
            self._message("Save blocked", str(exc))

    def _save_as(self):
        dialog = self.gui.FileDialog(
            self.gui.FileDialog.SAVE, "Save provisional scenario", self.window.theme
        )
        dialog.add_filter(".yaml", "YAML scenario")
        dialog.set_path(
            str(self.core.state.source_path or Path.cwd() / "scenario.yaml")
        )
        dialog.set_on_cancel(self.window.close_dialog)

        def done(path):
            self.window.close_dialog()
            try:
                self.core.save(Path(path))
                self.refresh()
            except Exception as exc:
                self._message("Save As blocked", str(exc))

        dialog.set_on_done(done)
        self.window.show_dialog(dialog)

    def _preview(self):
        try:
            files = self.core.export_preview()
            self.validation_panel.append_log(
                "Preview: {}".format(files["perspective_view_png"])
            )
        except Exception as exc:
            self._message("Preview failed", str(exc))

    def _external(self, command):
        self.validation_panel.append_log("$ " + " ".join(command))

        def output(line):
            self.gui.Application.instance.post_to_main_thread(
                self.window, lambda: self.validation_panel.append_log(line)
            )

        def complete(code):
            self.gui.Application.instance.post_to_main_thread(
                self.window,
                lambda: self.validation_panel.append_log("Exit code {}".format(code)),
            )

        try:
            self.runner.run_async(command, output, complete)
        except Exception as exc:
            self._message("External command", str(exc))

    def _build(self):
        try:
            self.core.save()
            command = self.runner.scenario_command(
                "build", self.core.state.source_path, self.core.output / "sionna_build"
            )
            self._external(command)
        except Exception as exc:
            self._message("Build blocked", str(exc))

    def _run_ab(self):
        if self.experiment is None:
            self._message("Run A/B", "--experiment 경로를 지정해야 합니다.")
            return
        self._external(
            self.runner.experiment_command(
                self.experiment, self.core.output / "sionna_ab"
            )
        )

    def _open_output(self):
        try:
            subprocess.Popen(
                ["xdg-open", str(self.core.output)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            self._message("Open output", str(exc))

    def _replace_preview(self, object_id, value):
        for index, obstacle in enumerate(self.core.state.obstacles):
            if obstacle.get("id") == object_id:
                self.core.state.obstacles[index] = value
                self.core.state.dirty = True
                self.core.last_validation = None
                return

    def _start_fps_navigation(self):
        if not self.fps_camera.settings.enabled:
            return False
        self.window.set_focus_widget(self.viewport.widget)
        self.viewport.set_fps_navigation(True)
        self.fps_camera.activate(time.monotonic())
        self._fps_exit_pending = False
        self.toolbar.set_fps_active(True)
        return True

    def _end_fps_navigation(self):
        if not self.fps_camera.active and not self._fps_exit_pending:
            return
        self.fps_camera.deactivate()
        # Fly interactor가 현재 BUTTON_UP을 먼저 받은 뒤 다음 tick에 복귀한다.
        self._fps_exit_pending = True
        self.toolbar.set_fps_active(False)

    def _on_mouse(self, event):
        gui = self.gui
        handled, ignored = (
            gui.Widget.EventCallbackResult.HANDLED,
            gui.Widget.EventCallbackResult.IGNORED,
        )
        right_down = event.is_button_down(gui.MouseButton.RIGHT)
        if event.type == gui.MouseEvent.Type.BUTTON_DOWN and right_down:
            self._start_fps_navigation()
            return ignored
        if self.fps_camera.active:
            if not right_down:
                self._end_fps_navigation()
            return ignored
        if self._fps_exit_pending:
            return handled
        if event.is_modifier_down(gui.KeyModifier.ALT) or event.is_button_down(
            gui.MouseButton.MIDDLE
        ):
            return ignored
        if event.type == gui.MouseEvent.Type.BUTTON_DOWN and event.is_button_down(
            gui.MouseButton.LEFT
        ):
            origin, direction = self.viewport.ray(event.x, event.y)
            mode = self.core.state.viewport_mode
            if mode == "select" or self.core.state.selected_object_id is None:
                hit = nearest_obstacle_hit(
                    origin, direction, self.viewport.obstacle_meshes
                )
                self.core.state.select(hit["object_id"] if hit else None)
                self.refresh()
                return handled
            object_id = self.core.state.selected_object_id
            self._drag = {
                "before": self.core.state.snapshot_document(),
                "object_id": object_id,
                "source": self.core.state.get_object(object_id),
                "x": event.x,
                "y": event.y,
                "floor_hit": ray_plane_intersection(
                    origin, direction, self.core.scene.containment.floor
                ),
                "mode": mode,
            }
            return handled
        if event.type == gui.MouseEvent.Type.DRAG and self._drag is not None:
            drag = self._drag
            dx, dy = event.x - drag["x"], event.y - drag["y"]
            fine = 0.1 if event.is_modifier_down(gui.KeyModifier.SHIFT) else 1.0
            snap = self.core.state.snap.enabled or event.is_modifier_down(
                gui.KeyModifier.CTRL
            )
            axis = self.core.state.axis_constraint
            try:
                if drag["mode"] == "translate":
                    if axis == "z":
                        delta = [0.0, 0.0, -dy * 0.01 * fine]
                    else:
                        origin, direction = self.viewport.ray(event.x, event.y)
                        current = ray_plane_intersection(
                            origin, direction, self.core.scene.containment.floor
                        )
                        delta = (
                            (current - drag["floor_hit"]) * fine
                            if current is not None and drag["floor_hit"] is not None
                            else np.asarray([dx, -dy, 0.0]) * 0.01 * fine
                        )
                    value = translate_obstacle(
                        drag["source"],
                        delta,
                        axis=axis,
                        snap_increment_m=self.core.state.snap.translation_m,
                        snap_enabled=snap,
                    )
                elif drag["mode"] == "rotate":
                    value = rotate_obstacle(
                        drag["source"],
                        dx * 0.5 * fine,
                        axis=axis or "z",
                        snap_increment_deg=self.core.state.snap.rotation_deg,
                        snap_enabled=snap,
                    )
                else:
                    value = resize_obstacle(
                        drag["source"],
                        math.exp(dx * 0.005 * fine),
                        axis=axis,
                        snap_increment_m=self.core.state.snap.size_m,
                        snap_enabled=snap,
                    )
                self._replace_preview(drag["object_id"], value)
                self.refresh()
            except ValueError:
                pass
            return handled
        if event.type == gui.MouseEvent.Type.BUTTON_UP and self._drag is not None:
            drag, self._drag = self._drag, None
            command = (
                ResizeObjectCommand
                if drag["mode"] == "scale"
                else TransformObjectCommand
            )
            self.core.commit_preview(drag["before"], command, drag["object_id"])
            self.refresh()
            return handled
        return ignored

    def _on_key(self, event):
        gui = self.gui
        # Window.set_on_key()은 SceneWidget mouse callback과 달리 bool을 요구한다.
        handled, ignored = True, False
        is_down = event.type == gui.KeyEvent.Type.DOWN
        if event.key in (gui.KeyName.LEFT_CONTROL, gui.KeyName.RIGHT_CONTROL):
            self._keys["ctrl"] = is_down
            return handled
        if event.key in (gui.KeyName.LEFT_SHIFT, gui.KeyName.RIGHT_SHIFT):
            self._keys["shift"] = is_down
            return handled
        movement_keys = {
            gui.KeyName.W: "w",
            gui.KeyName.A: "a",
            gui.KeyName.S: "s",
            gui.KeyName.D: "d",
        }
        if self.fps_camera.active or self._fps_exit_pending:
            if event.key in movement_keys:
                self.fps_camera.set_key(movement_keys[event.key], is_down)
                return handled
            if is_down and event.key == gui.KeyName.ESCAPE:
                self._end_fps_navigation()
                return handled
            # Open3D FLY의 Q/Z/E/R 등 추가 이동은 편집기에서 노출하지 않는다.
            return handled
        if not is_down:
            return ignored
        ctrl, shift = self._keys["ctrl"], self._keys["shift"]
        if ctrl and event.key == gui.KeyName.S:
            self._save()
            return handled
        if ctrl and event.key == gui.KeyName.D:
            self._duplicate()
            return handled
        if ctrl and event.key == gui.KeyName.Z:
            self.core.redo() if shift else self.core.undo()
            self.refresh()
            return handled
        if ctrl and event.key == gui.KeyName.Y:
            self.core.redo()
            self.refresh()
            return handled
        modes = {
            gui.KeyName.G: "translate",
            gui.KeyName.R: "rotate",
            gui.KeyName.S: "scale",
        }
        if event.key in modes:
            self.core.state.viewport_mode = modes[event.key]
            self.refresh()
            return handled
        axes = {gui.KeyName.X: "x", gui.KeyName.Y: "y", gui.KeyName.Z: "z"}
        if event.key in axes:
            self.core.state.axis_constraint = axes[event.key]
            self.refresh()
            return handled
        if event.key == gui.KeyName.DELETE:
            self._delete()
            return handled
        if event.key == gui.KeyName.F:
            self.viewport.frame_selected()
            return handled
        if event.key == gui.KeyName.HOME:
            self.viewport.frame_room()
            return handled
        if event.key == gui.KeyName.V:
            self.core.state.reference_visible = not self.core.state.reference_visible
            self.refresh()
            return handled
        if event.key == gui.KeyName.H and self.core.state.selected_object_id:
            key = self.core.state.selected_object_id
            self.core.state.object_visibility[
                key
            ] = not self.core.state.object_visibility.get(key, True)
            self.refresh()
            return handled
        views = {
            gui.KeyName.ONE: "front",
            gui.KeyName.THREE: "side",
            gui.KeyName.SEVEN: "top",
        }
        if event.key in views:
            self.viewport.set_view(views[event.key])
            return handled
        if event.key == gui.KeyName.ESCAPE:
            self.core.state.viewport_mode = "select"
            self.core.state.axis_constraint = None
            self.refresh()
            return handled
        return ignored

    def _on_tick(self):
        now = time.monotonic()
        if self.fps_camera.active:
            try:
                movement = self.fps_camera.step(
                    self.viewport.camera_view_matrix(),
                    now,
                    sprint=self._keys["shift"],
                )
                if float(np.linalg.norm(movement)) > 0.0:
                    self.core.state.camera = self.viewport.translate_camera(movement)
            except ValueError:
                self._end_fps_navigation()
        if self._fps_exit_pending:
            self.viewport.set_fps_navigation(False)
            self._fps_exit_pending = False
        if (
            now - self._last_autosave >= self._autosave_seconds
            and self.core.state.dirty
        ):
            self.core.autosave()
            self._last_autosave = now
        return True

    def _on_close(self):
        self.fps_camera.deactivate()
        if self.core.state.dirty:
            self.core.autosave()
        return True

    def run(self):
        self.gui.Application.instance.run()


def ensure_gui_display():
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        raise RuntimeError(
            "Open3D GUI를 열 display server가 없습니다. headless validate/export-preview를 사용하세요."
        )


def run_editor(core, editor_config, experiment=None):
    ensure_gui_display()
    ProxyPlacementApp(core, editor_config, experiment=experiment).run()
