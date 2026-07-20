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
from .gizmo import (
    axis_drag_parameter,
    rotation_drag_angle_deg,
    screen_rotation_drag_angle_deg,
)
from .native_keyboard import NativeKeyboardState, fps_keys_from_native
from .picking import nearest_obstacle_hit, ray_plane_intersection
from .transform_controller import (
    resize_obstacle,
    rotate_obstacle_in_space,
    snap_value,
    translate_obstacle,
)
from .gui.candidate_panel import CandidatePanel
from .gui.korean_font import configure_heading_font, configure_korean_font
from .gui.object_list_panel import ObjectListPanel
from .gui.properties_panel import PropertiesPanel
from .gui.section import make_section
from .gui.shortcuts import shortcut_text
from .gui.strings_ko import format_enabled_errors, localize_message, tr
from .gui.toolbar import PlacementToolbar
from .gui.validation_panel import ValidationPanel
from .gui.viewport import PlacementViewport


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
        self.korean_font_path = configure_korean_font(gui, app)
        self.heading_font_id = configure_heading_font(
            gui, app, self.korean_font_path
        )
        self.window = app.create_window(tr("window_title"), width, height)
        reference_config = editor_config.get("reference", {})
        core.state.reference_point_size = float(
            reference_config.get("point_size", core.state.reference_point_size)
        )
        core.state.reference_visible = bool(reference_config.get("visible", True))
        core.state.scene_display_mode = str(
            reference_config.get("display_mode", core.state.scene_display_mode)
        )
        core.materialize_draft_placeholders()
        self.viewport = PlacementViewport(self.window.renderer, core)
        self.toolbar = PlacementToolbar(
            core.state, self.refresh, self._set_reference_point_size
        )
        self.candidate_panel = CandidatePanel(
            core, self._add_candidate, self.heading_font_id
        )
        self.object_panel = ObjectListPanel(
            self._select,
            self._duplicate,
            self._delete,
            self._enable,
            lambda: self._reorder(-1),
            lambda: self._reorder(1),
            self._toggle_visibility,
            self.heading_font_id,
        )
        self.properties_panel = PropertiesPanel(
            core, self.refresh, self.heading_font_id
        )
        self.validation_panel = ValidationPanel(self.heading_font_id)
        self.warning = gui.Label(tr("provisional_warning"))
        self.warning.text_color = gui.Color(1.0, 0.38, 0.18)
        self.side = gui.ScrollableVert(4, gui.Margins(8, 8, 8, 8))
        self.side.add_child(self.warning)
        self.side.add_child(self.candidate_panel.widget)
        self.side.add_child(self.object_panel.widget)
        self.side.add_child(self.properties_panel.widget)
        self.side.add_child(self.validation_panel.widget)
        self._add_actions()
        shortcuts = make_section(gui, tr("shortcuts"), self.heading_font_id)
        shortcuts.add_child(gui.Label(shortcut_text()))
        self.side.add_child(shortcuts)
        self.window.add_child(self.toolbar.widget)
        self.window.add_child(self.viewport.widget)
        self.window.add_child(self.side)
        self.window.set_on_layout(self._layout)
        self.viewport.widget.set_on_mouse(self._on_mouse)
        # Viewport-only shortcuts leave cursor movement, Backspace, Delete, and
        # arrow keys to a focused TextEdit/NumberEdit.
        self.viewport.widget.set_on_key(self._on_viewport_key)
        # FPS movement records keys at the Window level so it does not depend
        # on SceneWidget's native FLY key focus. Outside FPS this returns False
        # so focused text/number inputs still receive every editing key.
        self.window.set_on_key(self._on_window_key)
        self.window.set_focus_widget(self.viewport.widget)
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
        self.native_keyboard = NativeKeyboardState()
        self._fps_exit_pending = False
        self._last_autosave = time.monotonic()
        self._autosave_seconds = int(
            editor_config.get("autosave", {}).get("interval_seconds", 60)
        )
        self.refresh()

    def _add_actions(self):
        gui = self.gui
        actions = make_section(gui, tr("scenario_actions"), self.heading_font_id)
        row1, row2, row3 = gui.Horiz(4), gui.Horiz(4), gui.Horiz(4)
        for label, callback, row in (
            (tr("validate"), self._validate, row1),
            (tr("save"), self._save, row1),
            (tr("save_as"), self._save_as, row1),
            (tr("export_preview"), self._preview, row2),
            (tr("build_sionna"), self._build, row2),
            (tr("run_ab"), self._run_ab, row3),
            (tr("open_output"), self._open_output, row3),
        ):
            button = gui.Button(label)
            button.set_on_clicked(callback)
            row.add_child(button)
        actions.add_child(row1)
        actions.add_child(row2)
        actions.add_child(row3)
        self.side.add_child(actions)

    def _layout(self, context):
        rect = self.window.content_rect
        toolbar_height = 78
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
        self.toolbar.refresh()
        self.object_panel.refresh(self.core.state, report)
        self.properties_panel.refresh(self.core.state.selected_object_id, report)
        self.validation_panel.refresh(report, self.core.state.selected_object_id)
        self.window.post_redraw()

    def _refresh_drag_preview(self, object_id):
        mesh = self.core.preview_mesh(object_id)
        self.viewport.update_object_preview(object_id, mesh)
        self.window.post_redraw()

    def _set_reference_point_size(self, value):
        self.viewport.set_reference_point_size(value)

    def _axis_drag_distance(self, drag, event, origin, direction):
        screen_axis = drag.get("screen_axis")
        if screen_axis is not None:
            mouse_delta = np.asarray(
                [event.x, event.y], dtype=float
            ) - drag["start_mouse"]
            return float(np.dot(mouse_delta, screen_axis)) * drag[
                "world_per_pixel"
            ]
        parameter = axis_drag_parameter(
            origin, direction, drag["center"], drag["axis_vector"]
        )
        return float(parameter - drag["start_parameter"])

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
                self._message(tr("cannot_enable"), str(exc))
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
        self.window.show_message_box(title, localize_message(text))

    def _validate(self):
        report = self.core.validate()
        self.refresh()
        self._message(
            tr("scenario_validation"),
            tr("validation_pass")
            if report["success"]
            else format_enabled_errors(report["enabled_errors"]),
        )

    def _save(self):
        try:
            result = self.core.save()
            self.validation_panel.append_log(
                "{}: {}".format(tr("saved"), result["scenario"])
            )
            self.refresh()
        except Exception as exc:
            self._message(tr("save_blocked"), str(exc))

    def _save_as(self):
        dialog = self.gui.FileDialog(
            self.gui.FileDialog.SAVE, tr("save_dialog"), self.window.theme
        )
        dialog.add_filter(".yaml", tr("yaml_scenario"))
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
                self._message(tr("save_as_blocked"), str(exc))

        dialog.set_on_done(done)
        self.window.show_dialog(dialog)

    def _preview(self):
        try:
            files = self.core.export_preview()
            self.validation_panel.append_log(
                "{}: {}".format(
                    tr("preview_created"), files["perspective_view_png"]
                )
            )
        except Exception as exc:
            self._message(tr("preview_failed"), str(exc))

    def _external(self, command):
        self.validation_panel.append_log("$ " + " ".join(command))

        def output(line):
            self.gui.Application.instance.post_to_main_thread(
                self.window, lambda: self.validation_panel.append_log(line)
            )

        def complete(code):
            self.gui.Application.instance.post_to_main_thread(
                self.window,
                lambda: self.validation_panel.append_log(
                    "{} {}".format(tr("exit_code"), code)
                ),
            )

        try:
            self.runner.run_async(command, output, complete)
        except Exception as exc:
            self._message(tr("external_command"), str(exc))

    def _build(self):
        try:
            self.core.save()
            command = self.runner.scenario_command(
                "build", self.core.state.source_path, self.core.output / "sionna_build"
            )
            self._external(command)
        except Exception as exc:
            self._message(tr("build_blocked"), str(exc))

    def _run_ab(self):
        if self.experiment is None:
            self._message(tr("run_ab"), tr("experiment_required"))
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
            self._message(tr("open_output_failed"), str(exc))

    def _replace_preview(self, object_id, value):
        for index, obstacle in enumerate(self.core.state.obstacles):
            if obstacle.get("id") == object_id:
                self.core.state.obstacles[index] = value
                self.core.state.dirty = True
                self.core.last_validation = None
                return

    def _set_fps_property_lock(self, active):
        panel = getattr(self, "properties_panel", None)
        if panel is None:
            return
        if active:
            # Open3D 0.18 keeps ImGui's text-edit ActiveId after a right-click
            # in the SceneWidget. Prevent polled WASD keys from changing the
            # active property while FPS navigation owns the keyboard.
            panel.updating = True
            panel.set_enabled(False)
            return
        panel.updating = False
        report = self.core.last_validation or self.core.validate()
        panel.refresh(self.core.state.selected_object_id, report)

    def _start_fps_navigation(self):
        if not self.fps_camera.settings.enabled:
            return False
        self.window.set_focus_widget(self.viewport.widget)
        self._set_fps_property_lock(True)
        native_keyboard = getattr(self, "native_keyboard", None)
        reset_transient = getattr(native_keyboard, "reset_transient", None)
        if reset_transient is not None:
            reset_transient()
        self.viewport.set_fps_navigation(True)
        self.fps_camera.activate(time.monotonic())
        self._fps_exit_pending = False
        self.toolbar.set_fps_active(True)
        return True

    def _end_fps_navigation(self):
        if not self.fps_camera.active and not self._fps_exit_pending:
            return
        self.fps_camera.deactivate()
        self._keys["ctrl"] = False
        self._keys["shift"] = False
        # Fly interactor가 현재 BUTTON_UP을 먼저 받은 뒤 다음 tick에 복귀한다.
        self._fps_exit_pending = True
        self._set_fps_property_lock(False)
        self.toolbar.set_fps_active(False)

    def _on_mouse(self, event):
        gui = self.gui
        consumed, handled, ignored = (
            gui.Widget.EventCallbackResult.CONSUMED,
            gui.Widget.EventCallbackResult.HANDLED,
            gui.Widget.EventCallbackResult.IGNORED,
        )
        right_down = event.is_button_down(gui.MouseButton.RIGHT)
        if event.type == gui.MouseEvent.Type.BUTTON_DOWN and right_down:
            self._start_fps_navigation()
            return ignored
        if self.fps_camera.active:
            if event.type == gui.MouseEvent.Type.BUTTON_UP:
                self._end_fps_navigation()
            return ignored
        if self._fps_exit_pending:
            return consumed
        if event.is_modifier_down(gui.KeyModifier.ALT) or event.is_button_down(
            gui.MouseButton.MIDDLE
        ):
            return ignored
        # Preserve Open3D's Ctrl+left-drag camera pan. Ctrl can still enable
        # snap after a gizmo drag has already started.
        if self._drag is None and event.is_modifier_down(gui.KeyModifier.CTRL):
            return ignored
        if event.type == gui.MouseEvent.Type.BUTTON_DOWN and event.is_button_down(
            gui.MouseButton.LEFT
        ):
            origin, direction = self.viewport.ray(event.x, event.y)
            mode = self.core.state.viewport_mode
            selected = self.core.state.selected_object_id
            if mode in {"translate", "rotate", "scale"} and selected is not None:
                gizmo_hit = self.viewport.pick_gizmo(
                    origin, direction, screen_xy=(event.x, event.y)
                )
                frame = self.viewport.gizmo_frame
                if gizmo_hit is not None and frame is not None:
                    axis_name = str(gizmo_hit["axis"])
                    axis = frame.axis(axis_name)
                    drag = {
                        "before": self.core.state.snapshot_document(),
                        "object_id": selected,
                        "source": self.core.state.get_object(selected),
                        "axis": axis_name,
                        "axis_vector": axis,
                        "center": frame.center,
                        "gizmo_length": frame.length,
                        "mode": mode,
                        "start_mouse": np.asarray(
                            [event.x, event.y], dtype=float
                        ),
                    }
                    if mode == "rotate":
                        drag["start_point"] = np.asarray(
                            gizmo_hit["point"], dtype=float
                        )
                        screen_start = self.viewport.project_gizmo_point(
                            drag["start_point"]
                        )
                        radial_world = drag["start_point"] - frame.center
                        radial_length = float(np.linalg.norm(radial_world))
                        if screen_start is not None and radial_length > 1.0e-9:
                            radial_world /= radial_length
                            tangent_world = np.cross(axis, radial_world)
                            tangent_length = float(np.linalg.norm(tangent_world))
                            if tangent_length > 1.0e-9:
                                tangent_world /= tangent_length
                                sample_angle = 0.15
                                screen_tangent_point = (
                                    self.viewport.project_gizmo_point(
                                        drag["start_point"]
                                        + tangent_world
                                        * frame.length
                                        * sample_angle
                                    )
                                )
                                if screen_tangent_point is not None:
                                    screen_tangent = (
                                        screen_tangent_point[:2]
                                        - screen_start[:2]
                                    )
                                    screen_tangent_length = float(
                                        np.linalg.norm(screen_tangent)
                                    )
                                    if screen_tangent_length > 1.0:
                                        drag["screen_tangent"] = (
                                            screen_tangent / screen_tangent_length
                                        )
                                        drag["rotation_deg_per_pixel"] = (
                                            math.degrees(sample_angle)
                                            / screen_tangent_length
                                        )
                    else:
                        drag["start_parameter"] = axis_drag_parameter(
                            origin, direction, frame.center, axis
                        )
                        screen_center = self.viewport.project_gizmo_point(
                            frame.center
                        )
                        screen_end = self.viewport.project_gizmo_point(
                            frame.center + axis * frame.length
                        )
                        if screen_center is not None and screen_end is not None:
                            screen_axis = screen_end[:2] - screen_center[:2]
                            screen_length = float(np.linalg.norm(screen_axis))
                            if screen_length > 6.0:
                                drag["screen_axis"] = screen_axis / screen_length
                                drag["world_per_pixel"] = (
                                    frame.length / screen_length
                                )
                    self._drag = drag
                    # HANDLED lets SceneWidget retain mouse capture for DRAG
                    # events; PICK_POINTS prevents its camera interactor from
                    # rotating at the same time.
                    self.viewport.set_gizmo_interaction(True)
                    return handled
            hit = nearest_obstacle_hit(origin, direction, self.viewport.obstacle_meshes)
            if mode == "select":
                self.core.state.select(hit["object_id"] if hit else None)
                self.refresh()
                return consumed if hit else ignored
            if hit and hit["object_id"] != selected:
                self.core.state.select(hit["object_id"])
                self.refresh()
                return consumed
            # Only a gizmo handle starts a transform. Other drags are left to
            # Open3D's camera orbit controller.
            return ignored
        if event.type == gui.MouseEvent.Type.DRAG and self._drag is not None:
            drag = self._drag
            fine = 0.1 if event.is_modifier_down(gui.KeyModifier.SHIFT) else 1.0
            snap = self.core.state.snap.enabled or event.is_modifier_down(
                gui.KeyModifier.CTRL
            )
            try:
                origin, direction = self.viewport.ray(event.x, event.y)
                if drag["mode"] == "translate":
                    distance = self._axis_drag_distance(
                        drag, event, origin, direction
                    ) * fine
                    distance = snap_value(
                        distance, self.core.state.snap.translation_m, snap
                    )
                    delta = drag["axis_vector"] * distance
                    value = translate_obstacle(
                        drag["source"],
                        delta,
                        axis=None,
                        snap_increment_m=self.core.state.snap.translation_m,
                        snap_enabled=False,
                    )
                elif drag["mode"] == "rotate":
                    tangent = drag.get("screen_tangent")
                    if tangent is not None:
                        angle = screen_rotation_drag_angle_deg(
                            drag["start_mouse"],
                            np.asarray([event.x, event.y], dtype=float),
                            tangent,
                            drag["rotation_deg_per_pixel"],
                        )
                    else:
                        plane = np.append(
                            drag["axis_vector"],
                            -float(
                                np.dot(drag["axis_vector"], drag["center"])
                            ),
                        )
                        current = ray_plane_intersection(origin, direction, plane)
                        if current is None:
                            return consumed
                        angle = rotation_drag_angle_deg(
                            drag["center"],
                            drag["axis_vector"],
                            drag["start_point"],
                            current,
                        )
                    value = rotate_obstacle_in_space(
                        drag["source"],
                        angle * fine,
                        axis=drag["axis"],
                        space=self.core.state.transform_space,
                        snap_increment_deg=self.core.state.snap.rotation_deg,
                        snap_enabled=snap,
                    )
                else:
                    distance = self._axis_drag_distance(
                        drag, event, origin, direction
                    ) * fine
                    value = resize_obstacle(
                        drag["source"],
                        math.exp(distance / drag["gizmo_length"]),
                        axis=drag["axis"],
                        snap_increment_m=self.core.state.snap.size_m,
                        snap_enabled=snap,
                    )
                self._replace_preview(drag["object_id"], value)
                self._refresh_drag_preview(drag["object_id"])
            except ValueError:
                pass
            return consumed
        if event.type == gui.MouseEvent.Type.BUTTON_UP and self._drag is not None:
            drag, self._drag = self._drag, None
            self.viewport.set_gizmo_interaction(False)
            command = (
                ResizeObjectCommand
                if drag["mode"] == "scale"
                else TransformObjectCommand
            )
            self.core.commit_preview(drag["before"], command, drag["object_id"])
            self.refresh()
            return consumed
        return ignored

    def _on_viewport_key(self, event):
        gui = self.gui
        if self.fps_camera.active or self._fps_exit_pending:
            self._on_key(event)
            return gui.Widget.EventCallbackResult.CONSUMED
        elif event.key in (
            gui.KeyName.LEFT_CONTROL,
            gui.KeyName.RIGHT_CONTROL,
            gui.KeyName.LEFT_SHIFT,
            gui.KeyName.RIGHT_SHIFT,
        ):
            self._on_key(event)
            return gui.Widget.EventCallbackResult.HANDLED
        return (
            gui.Widget.EventCallbackResult.CONSUMED
            if self._on_key(event)
            else gui.Widget.EventCallbackResult.IGNORED
        )

    def _on_window_key(self, event):
        if self.fps_camera.active or self._fps_exit_pending:
            return bool(self._on_key(event))
        return False

    def _on_key(self, event):
        gui = self.gui
        # Keep bool return values for headless tests; _on_viewport_key converts
        # them to SceneWidget.EventCallbackResult.
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
            values = ("both", "point_cloud", "proxy_mesh")
            index = values.index(self.core.state.scene_display_mode)
            self.core.state.scene_display_mode = values[(index + 1) % len(values)]
            self.core.state.reference_visible = True
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
                native_keyboard = getattr(self, "native_keyboard", None)
                if native_keyboard is not None and native_keyboard.available:
                    native_keys = fps_keys_from_native(native_keyboard.pressed())
                    for key in ("w", "a", "s", "d"):
                        self.fps_camera.set_key(key, key in native_keys)
                    self._keys["shift"] = "shift" in native_keys
                movement = self.fps_camera.step(
                    self.viewport.camera_view_matrix(),
                    now,
                    sprint=self._keys["shift"],
                )
                if float(np.linalg.norm(movement)) > 0.0:
                    self.core.state.camera = self.viewport.translate_camera(
                        movement
                    )
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
        native_keyboard = getattr(self, "native_keyboard", None)
        if native_keyboard is not None:
            native_keyboard.close()
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
