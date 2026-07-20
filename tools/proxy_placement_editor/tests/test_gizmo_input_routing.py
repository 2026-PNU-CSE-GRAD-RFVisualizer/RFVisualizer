from types import SimpleNamespace

import numpy as np

from tools.proxy_placement_editor.app import ProxyPlacementApp


class Results:
    CONSUMED = "consumed"
    HANDLED = "handled"
    IGNORED = "ignored"


class Gui:
    Widget = SimpleNamespace(EventCallbackResult=Results)
    MouseButton = SimpleNamespace(LEFT="left", MIDDLE="middle", RIGHT="right")
    MouseEvent = SimpleNamespace(
        Type=SimpleNamespace(BUTTON_DOWN="down", BUTTON_UP="up", DRAG="drag")
    )
    KeyModifier = SimpleNamespace(ALT="alt", SHIFT="shift", CTRL="ctrl")


class Event:
    type = "down"
    x = 100
    y = 100

    def is_button_down(self, button):
        return button == Gui.MouseButton.LEFT

    def is_modifier_down(self, modifier):
        return False


class CtrlEvent(Event):
    def is_modifier_down(self, modifier):
        return modifier == Gui.KeyModifier.CTRL


class DragEvent(Event):
    def __init__(self, event_type, x, y):
        self.type = event_type
        self.x = x
        self.y = y

    def is_button_down(self, button):
        return self.type != Gui.MouseEvent.Type.BUTTON_UP and button == Gui.MouseButton.LEFT


class Viewport:
    obstacle_meshes = []
    gizmo_frame = None

    def ray(self, x, y):
        return np.asarray([0.0, -2.0, 0.0]), np.asarray([0.0, 1.0, 0.0])

    def __init__(self):
        self.hit = None
        self.interactions = []

    def pick_gizmo(self, origin, direction, screen_xy=None):
        return None

    def set_gizmo_interaction(self, enabled):
        self.interactions.append(bool(enabled))

    def project_gizmo_point(self, point):
        value = np.asarray(point, dtype=float)
        return np.asarray([100.0 + 50.0 * value[0], 100.0 - 50.0 * value[1], 0.5])


def _app():
    value = ProxyPlacementApp.__new__(ProxyPlacementApp)
    value.gui = Gui
    value.viewport = Viewport()
    value.fps_camera = SimpleNamespace(active=False)
    value._fps_exit_pending = False
    value._drag = None
    state = SimpleNamespace(viewport_mode="scale", selected_object_id="box")
    value.core = SimpleNamespace(state=state)
    return value


def test_transform_mode_background_drag_is_left_for_camera():
    value = _app()
    assert value._on_mouse(Event()) == Results.IGNORED
    assert value._drag is None


def test_ctrl_left_drag_is_left_for_native_camera_pan():
    value = _app()
    assert value._on_mouse(CtrlEvent()) == Results.IGNORED
    assert value._drag is None


def test_gizmo_mouse_down_keeps_scene_capture_without_camera_rotation():
    value = _app()
    frame = SimpleNamespace(
        center=np.zeros(3),
        length=1.0,
        axis=lambda name: np.eye(3)[:, {"x": 0, "y": 1, "z": 2}[name]],
    )
    value.viewport.gizmo_frame = frame
    value.viewport.pick_gizmo = lambda origin, direction, screen_xy=None: {
        "axis": "x",
        "point": [1.0, 0.0, 0.0],
    }
    value.core.state.snapshot_document = lambda: {"scenario": {}}
    value.core.state.get_object = lambda object_id: {"id": object_id}
    assert value._on_mouse(Event()) == Results.HANDLED
    assert value._drag["axis"] == "x"
    assert value.viewport.interactions == [True]


def test_screen_axis_drag_converts_pixels_to_world_distance():
    value = _app()
    drag = {
        "start_mouse": np.asarray([100.0, 100.0]),
        "screen_axis": np.asarray([1.0, 0.0]),
        "world_per_pixel": 0.02,
    }
    event = SimpleNamespace(x=125.0, y=110.0)
    distance = value._axis_drag_distance(
        drag,
        event,
        np.zeros(3),
        np.asarray([0.0, 1.0, 0.0]),
    )
    assert np.isclose(distance, 0.5)


def test_gizmo_drag_updates_object_and_restores_camera_control(draft_core):
    draft_core.materialize_draft_placeholders()
    object_id = "desk_block_example"
    draft_core.state.select(object_id)
    draft_core.state.viewport_mode = "translate"
    draft_core.state.snap.enabled = False
    before_x = float(
        draft_core.state.get_object(object_id)["geometry"]["position_m"]["x"]
    )
    value = _app()
    value.core = draft_core
    value._refresh_drag_preview = lambda object_id: None
    value.refresh = lambda: None
    frame = SimpleNamespace(
        center=np.zeros(3),
        length=1.0,
        axis=lambda name: np.eye(3)[:, {"x": 0, "y": 1, "z": 2}[name]],
    )
    value.viewport.gizmo_frame = frame
    value.viewport.pick_gizmo = lambda origin, direction, screen_xy=None: {
        "axis": "x",
        "point": [1.0, 0.0, 0.0],
    }
    assert (
        value._on_mouse(DragEvent(Gui.MouseEvent.Type.BUTTON_DOWN, 100, 100))
        == Results.HANDLED
    )
    assert (
        value._on_mouse(DragEvent(Gui.MouseEvent.Type.DRAG, 125, 100))
        == Results.CONSUMED
    )
    assert (
        value._on_mouse(DragEvent(Gui.MouseEvent.Type.BUTTON_UP, 125, 100))
        == Results.CONSUMED
    )
    after_x = float(
        draft_core.state.get_object(object_id)["geometry"]["position_m"]["x"]
    )
    assert np.isclose(after_x - before_x, 0.5)
    assert value.viewport.interactions == [True, False]


def test_rotation_gizmo_drag_changes_object_yaw(draft_core):
    draft_core.materialize_draft_placeholders()
    object_id = "desk_block_example"
    draft_core.state.select(object_id)
    draft_core.state.viewport_mode = "rotate"
    draft_core.state.transform_space = "world"
    draft_core.state.snap.enabled = False
    before_yaw = float(
        draft_core.state.get_object(object_id)["geometry"]["rotation_deg"]["yaw"]
    )
    value = _app()
    value.core = draft_core
    value._refresh_drag_preview = lambda object_id: None
    value.refresh = lambda: None
    frame = SimpleNamespace(
        center=np.zeros(3),
        length=1.0,
        axis=lambda name: np.eye(3)[:, {"x": 0, "y": 1, "z": 2}[name]],
    )
    value.viewport.gizmo_frame = frame
    value.viewport.pick_gizmo = lambda origin, direction, screen_xy=None: {
        "axis": "z",
        "point": [1.0, 0.0, 0.0],
    }
    assert (
        value._on_mouse(DragEvent(Gui.MouseEvent.Type.BUTTON_DOWN, 150, 100))
        == Results.HANDLED
    )
    assert (
        value._on_mouse(DragEvent(Gui.MouseEvent.Type.DRAG, 150, 21.46))
        == Results.CONSUMED
    )
    assert (
        value._on_mouse(DragEvent(Gui.MouseEvent.Type.BUTTON_UP, 150, 21.46))
        == Results.CONSUMED
    )
    after_yaw = float(
        draft_core.state.get_object(object_id)["geometry"]["rotation_deg"]["yaw"]
    )
    assert np.isclose(after_yaw - before_yaw, 90.0, atol=0.1)
