from types import SimpleNamespace

import numpy as np

from tools.proxy_placement_editor.app import ProxyPlacementApp
from tools.proxy_placement_editor.fps_camera_controller import (
    FpsCameraController,
    FpsNavigationSettings,
)


class EventResults:
    HANDLED = "handled"
    IGNORED = "ignored"
    CONSUMED = "consumed"


class FakeGui:
    Widget = SimpleNamespace(EventCallbackResult=EventResults)
    MouseButton = SimpleNamespace(LEFT="left", MIDDLE="middle", RIGHT="right")
    MouseEvent = SimpleNamespace(
        Type=SimpleNamespace(BUTTON_DOWN="down", BUTTON_UP="up", DRAG="drag")
    )
    KeyModifier = SimpleNamespace(ALT="alt", CTRL="ctrl", SHIFT="shift")
    KeyEvent = SimpleNamespace(Type=SimpleNamespace(DOWN="down", UP="up"))
    KeyName = SimpleNamespace(
        LEFT_CONTROL="left_ctrl",
        RIGHT_CONTROL="right_ctrl",
        LEFT_SHIFT="left_shift",
        RIGHT_SHIFT="right_shift",
        W="w",
        A="a",
        S="s",
        D="d",
        G="g",
        R="r",
        X="x",
        Y="y",
        Z="z",
        DELETE="delete",
        F="f",
        HOME="home",
        V="v",
        H="h",
        ONE="one",
        THREE="three",
        SEVEN="seven",
        ESCAPE="escape",
    )


class MouseEvent:
    def __init__(self, event_type, right=False, x=0.0, y=0.0):
        self.type = event_type
        self.right = right
        self.x = x
        self.y = y

    def is_button_down(self, button):
        return self.right if button == FakeGui.MouseButton.RIGHT else False

    def is_modifier_down(self, modifier):
        return False


class KeyEvent:
    def __init__(self, key, is_down=True):
        self.key = key
        self.type = FakeGui.KeyEvent.Type.DOWN if is_down else FakeGui.KeyEvent.Type.UP


class FakeViewport:
    def __init__(self):
        self.widget = object()
        self.navigation_modes = []
        self.movements = []
        self.rotations = []
        self.gizmo_front_updates = 0

    def set_fps_navigation(self, enabled):
        self.navigation_modes.append(bool(enabled))

    def camera_view_matrix(self):
        world_from_camera = np.eye(4)
        world_from_camera[:3, 0] = [1.0, 0.0, 0.0]
        world_from_camera[:3, 1] = [0.0, 0.0, 1.0]
        world_from_camera[:3, 2] = [0.0, -1.0, 0.0]
        return np.linalg.inv(world_from_camera)

    def translate_camera(self, movement):
        self.movements.append(np.asarray(movement))
        return {"eye": [0, 0, 0], "forward": [0, 1, 0], "up": [0, 0, 1]}

    def rotate_fps_camera(self, delta_x, delta_y, settings):
        self.rotations.append((delta_x, delta_y, settings))
        return {"eye": [0, 0, 0], "forward": [1, 0, 0], "up": [0, 0, 1]}

    def update_gizmo_front_geometry(self):
        self.gizmo_front_updates += 1
        return True


def make_app():
    value = ProxyPlacementApp.__new__(ProxyPlacementApp)
    value.gui = FakeGui
    value.viewport = FakeViewport()
    value.toolbar = SimpleNamespace(
        states=[], set_fps_active=lambda active: value.toolbar.states.append(active)
    )
    value.window = SimpleNamespace(set_focus_widget=lambda widget: None)
    value.fps_camera = FpsCameraController(
        FpsNavigationSettings(
            movement_speed_mps=1.0,
            max_frame_delta_seconds=1.0,
        )
    )
    value._fps_exit_pending = False
    value._keys = {"ctrl": False, "shift": False}
    value._drag = None
    value._fps_mouse_position = None
    value._last_autosave = 0.0
    value._autosave_seconds = 60
    state = SimpleNamespace(viewport_mode="select", dirty=False, camera={})
    value.core = SimpleNamespace(state=state, autosave=lambda: None)
    value.refresh = lambda: None
    return value


def test_right_mouse_routes_wasd_to_fps_and_restores_scale(monkeypatch):
    value = make_app()
    times = iter((10.0, 10.1, 10.2))
    monkeypatch.setattr(
        "tools.proxy_placement_editor.app.time.monotonic", lambda: next(times)
    )
    assert (
        value._on_mouse(MouseEvent(FakeGui.MouseEvent.Type.BUTTON_DOWN, right=True))
        == EventResults.HANDLED
    )
    assert value.fps_camera.active is True
    assert value.viewport.navigation_modes == [True]
    assert value._on_key(KeyEvent(FakeGui.KeyName.S)) is True
    assert value.fps_camera.pressed_keys == {"s"}
    assert value.core.state.viewport_mode == "select"

    # Releasing another mouse button while right is still held must not end
    # the FPS gesture or restore the orbit controller early.
    assert (
        value._on_mouse(MouseEvent(FakeGui.MouseEvent.Type.BUTTON_UP, right=True))
        == EventResults.CONSUMED
    )
    assert value.fps_camera.active is True

    # Open3D 0.18/0.19 may omit the held-button bit on DRAG events. FPS must
    # end on BUTTON_UP, not on that transient bit.
    assert (
        value._on_mouse(
            MouseEvent(FakeGui.MouseEvent.Type.DRAG, right=False, x=20, y=10)
        )
        == EventResults.CONSUMED
    )
    assert value.fps_camera.active is True
    assert value.viewport.rotations[0][:2] == (20.0, 10.0)
    assert value.core.state.camera["forward"] == [1, 0, 0]

    assert (
        value._on_mouse(MouseEvent(FakeGui.MouseEvent.Type.BUTTON_UP, right=False))
        == EventResults.CONSUMED
    )
    assert value.fps_camera.active is False
    assert value._fps_exit_pending is True
    value._on_tick()
    assert value.viewport.navigation_modes == [True, False]
    assert value._fps_exit_pending is False

    assert value._on_key(KeyEvent(FakeGui.KeyName.S)) is True
    assert value.core.state.viewport_mode == "scale"


def test_active_fps_movement_is_captured_without_native_focus_dependency():
    value = make_app()
    assert value._on_window_key(KeyEvent(FakeGui.KeyName.W)) is False
    assert value.fps_camera.pressed_keys == set()
    value.fps_camera.activate(1.0)
    assert value._on_window_key(KeyEvent(FakeGui.KeyName.W)) is True
    assert value.fps_camera.pressed_keys == {"w"}
    assert value._on_window_key(KeyEvent(FakeGui.KeyName.W, is_down=False)) is True
    assert value.fps_camera.pressed_keys == set()
    assert value._on_viewport_key(KeyEvent(FakeGui.KeyName.W)) == EventResults.CONSUMED
    assert value.fps_camera.pressed_keys == {"w"}


def test_window_tracks_ctrl_for_list_selection_without_consuming_it():
    value = make_app()

    assert (
        value._on_window_key(KeyEvent(FakeGui.KeyName.LEFT_CONTROL))
        is False
    )
    assert value._ctrl_selection_active() is True
    assert (
        value._on_window_key(
            KeyEvent(FakeGui.KeyName.LEFT_CONTROL, is_down=False)
        )
        is False
    )
    assert value._ctrl_selection_active() is False


def test_tick_moves_camera_from_captured_fps_keys(monkeypatch):
    value = make_app()
    value.fps_camera.activate(5.0)
    value.fps_camera.set_key("w", True)
    monkeypatch.setattr(
        "tools.proxy_placement_editor.app.time.monotonic", lambda: 5.25
    )
    assert value._on_tick() is True
    assert value.viewport.gizmo_front_updates == 1
    assert len(value.viewport.movements) == 1
    np.testing.assert_allclose(value.viewport.movements[0], [0.0, 0.25, 0.0])
    assert value.core.state.camera["forward"] == [0, 1, 0]


def test_tick_polls_native_keys_when_imgui_suppresses_callbacks(monkeypatch):
    value = make_app()
    value.native_keyboard = SimpleNamespace(
        available=True,
        pressed=lambda: {"w", "shift_left"},
    )
    value.fps_camera.activate(5.0)
    monkeypatch.setattr(
        "tools.proxy_placement_editor.app.time.monotonic", lambda: 5.25
    )
    assert value._on_tick() is True
    assert value.fps_camera.pressed_keys == {"w"}
    assert value._keys["shift"] is True
    np.testing.assert_allclose(value.viewport.movements[0], [0.0, 0.75, 0.0])


def test_fps_navigation_locks_and_restores_active_property_editor(monkeypatch):
    value = make_app()
    native_resets = []
    value.native_keyboard = SimpleNamespace(
        reset_transient=lambda: native_resets.append(True)
    )
    panel = SimpleNamespace(
        updating=False,
        enabled_states=[],
        refresh_calls=[],
    )
    panel.set_enabled = lambda enabled: panel.enabled_states.append(bool(enabled))
    panel.refresh = lambda selected, report: panel.refresh_calls.append(
        (selected, report)
    )
    value.properties_panel = panel
    value.core.state.selected_object_id = "desk_000"
    value.core.last_validation = {"objects": []}
    value.core.validate = lambda: {"objects": ["unexpected"]}
    monkeypatch.setattr(
        "tools.proxy_placement_editor.app.time.monotonic", lambda: 5.0
    )

    assert value._start_fps_navigation() is True
    assert native_resets == [True]
    assert panel.updating is True
    assert panel.enabled_states == [False]

    value._end_fps_navigation()
    assert panel.updating is False
    assert panel.refresh_calls == [("desk_000", {"objects": []})]


def test_ctrl_modifier_is_observed_but_passed_to_native_pan():
    value = make_app()
    result = value._on_viewport_key(KeyEvent(FakeGui.KeyName.LEFT_CONTROL))
    assert result == EventResults.HANDLED
    assert value._keys["ctrl"] is True


def test_active_gizmo_drag_consumes_camera_and_mode_shortcuts():
    value = make_app()
    value._drag = {"active": True}
    value.viewport.frame_room = lambda: (_ for _ in ()).throw(
        AssertionError("camera changed during gizmo drag")
    )

    assert (
        value._on_viewport_key(KeyEvent(FakeGui.KeyName.HOME))
        == EventResults.CONSUMED
    )
    assert value._on_window_key(KeyEvent(FakeGui.KeyName.HOME)) is True
    assert value.core.state.viewport_mode == "select"

    assert (
        value._on_viewport_key(KeyEvent(FakeGui.KeyName.LEFT_SHIFT))
        == EventResults.CONSUMED
    )
    assert value._keys["shift"] is True
