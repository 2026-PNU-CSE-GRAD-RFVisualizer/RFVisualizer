import math
from types import SimpleNamespace

import numpy as np

from tools.proxy_placement_editor.app import ProxyPlacementApp
from tools.proxy_placement_editor.transform_controller import (
    rotate_point_about_pivot,
    scale_point_about_pivot,
)
from tools.sionna_scenario.primitive_builder import rotation_matrix_xyz


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


class CameraGestureEvent(DragEvent):
    def __init__(self, event_type, x, y, buttons=(), modifiers=()):
        super().__init__(event_type, x, y)
        self.buttons = set(buttons)
        self.modifiers = set(modifiers)

    def is_button_down(self, button):
        return button in self.buttons

    def is_modifier_down(self, modifier):
        return modifier in self.modifiers


class Viewport:
    obstacle_meshes = []
    gizmo_frame = None

    def ray(self, x, y):
        return np.asarray([0.0, -2.0, 0.0]), np.asarray([0.0, 1.0, 0.0])

    def __init__(self):
        self.hit = None
        self.near_gizmo = False
        self.interactions = []

    def pick_gizmo(self, origin, direction, screen_xy=None):
        return None

    def is_near_gizmo(self, screen_xy):
        return self.near_gizmo

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


def test_near_gizmo_miss_is_consumed_without_clearing_selection():
    value = _app()
    value.viewport.near_gizmo = True
    assert value._on_mouse(Event()) == Results.CONSUMED
    assert value.core.state.selected_object_id == "box"
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


def test_active_gizmo_drag_owns_mouse_until_left_button_is_released():
    value = _app()
    value._drag = {"active": True}
    value._start_fps_navigation = lambda: (_ for _ in ()).throw(
        AssertionError("FPS camera started during gizmo drag")
    )
    value.viewport.ray = lambda x, y: (_ for _ in ()).throw(
        AssertionError("gizmo drag advanced during a camera gesture")
    )

    assert value._on_mouse(
        CameraGestureEvent(
            Gui.MouseEvent.Type.BUTTON_DOWN,
            100,
            100,
            buttons=(Gui.MouseButton.LEFT, Gui.MouseButton.RIGHT),
        )
    ) == Results.CONSUMED
    assert value._on_mouse(
        CameraGestureEvent(
            Gui.MouseEvent.Type.DRAG,
            110,
            100,
            buttons=(Gui.MouseButton.LEFT, Gui.MouseButton.MIDDLE),
        )
    ) == Results.CONSUMED
    assert value._on_mouse(
        CameraGestureEvent(
            Gui.MouseEvent.Type.DRAG,
            110,
            100,
            buttons=(Gui.MouseButton.LEFT,),
            modifiers=(Gui.KeyModifier.ALT,),
        )
    ) == Results.CONSUMED
    assert value._drag == {"active": True}


def test_other_button_release_does_not_finish_active_gizmo_drag():
    value = _app()
    value._drag = {"active": True}

    assert value._on_mouse(
        CameraGestureEvent(
            Gui.MouseEvent.Type.BUTTON_UP,
            100,
            100,
            buttons=(Gui.MouseButton.LEFT,),
        )
    ) == Results.CONSUMED
    assert value._drag == {"active": True}


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
    object_id = str(draft_core.state.obstacles[0]["id"])
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
    object_id = str(draft_core.state.obstacles[0]["id"])
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


def _center_anchor_ids(core):
    """draft_core의 4개 예시는 모두 null geometry라 미리보기가 불가능하므로,
    center anchor 후보 두 개를 직접 추가해 그룹 변환 대상으로 쓴다.
    add_candidate는 size_m을 리스트로 남기므로 무변화 resize로 dict 형태로 정규화하고,
    이 준비 과정에서 쌓인 undo 기록은 그룹 변환 테스트에 영향이 없도록 비운다."""
    first = core.add_candidate("blackboard_panel")
    second = core.add_candidate("custom_thin_panel")
    core.resize(first["id"], 1.0)
    core.resize(second["id"], 1.0)
    core.commands._undo.clear()
    core.commands._redo.clear()
    return [str(first["id"]), str(second["id"])]


def _mesh_center(core, object_id):
    vertices = np.asarray(core.preview_mesh(object_id).vertices, dtype=float)
    return (np.min(vertices, axis=0) + np.max(vertices, axis=0)) / 2.0


def _group_drag_app(draft_core, mode):
    object_ids = _center_anchor_ids(draft_core)
    draft_core.state.select(object_ids[0])
    draft_core.state.select(object_ids[1], additive=True)
    draft_core.state.viewport_mode = mode
    draft_core.state.transform_space = "local"
    draft_core.state.snap.enabled = False
    centers = {
        object_id: _mesh_center(draft_core, object_id)
        for object_id in object_ids
    }
    vertices = np.concatenate(
        [
            np.asarray(draft_core.preview_mesh(object_id).vertices, dtype=float)
            for object_id in object_ids
        ],
        axis=0,
    )
    pivot = (np.min(vertices, axis=0) + np.max(vertices, axis=0)) / 2.0
    value = _app()
    value.core = draft_core
    value.refresh = lambda: None
    value._refresh_drag_preview = lambda *args: None
    value.viewport.gizmo_object_ids = object_ids
    frame = SimpleNamespace(
        center=pivot,
        length=1.0,
        axis=lambda name: np.eye(3)[:, {"x": 0, "y": 1, "z": 2}[name]],
    )
    value.viewport.gizmo_frame = frame
    value.viewport.pick_gizmo = lambda origin, direction, screen_xy=None: {
        "axis": "z" if mode == "rotate" else "x",
        "point": (
            pivot + np.asarray([1.0, 0.0, 0.0])
        ).tolist(),
    }
    return value, object_ids, centers, pivot


def test_group_translation_moves_every_selected_object_as_one_undo(draft_core):
    value, object_ids, centers, _ = _group_drag_app(draft_core, "translate")

    value._on_mouse(DragEvent(Gui.MouseEvent.Type.BUTTON_DOWN, 100, 100))
    value._on_mouse(DragEvent(Gui.MouseEvent.Type.DRAG, 125, 100))
    value._on_mouse(DragEvent(Gui.MouseEvent.Type.BUTTON_UP, 125, 100))

    for object_id in object_ids:
        np.testing.assert_allclose(
            _mesh_center(draft_core, object_id),
            centers[object_id] + [0.5, 0.0, 0.0],
            atol=1.0e-8,
        )
    assert draft_core.commands.undo_count == 1


def test_group_rotation_uses_combined_center_and_world_axes(draft_core):
    value, object_ids, centers, pivot = _group_drag_app(draft_core, "rotate")
    before_rotations = {
        object_id: list(
            draft_core.state.get_object(object_id)["geometry"][
                "rotation_deg"
            ].values()
        )
        for object_id in object_ids
    }

    value._on_mouse(DragEvent(Gui.MouseEvent.Type.BUTTON_DOWN, 150, 100))
    value._on_mouse(DragEvent(Gui.MouseEvent.Type.DRAG, 150, 21.46))
    value._on_mouse(DragEvent(Gui.MouseEvent.Type.BUTTON_UP, 150, 21.46))

    expected_delta = rotation_matrix_xyz([0.0, 0.0, 90.0])
    for object_id in object_ids:
        np.testing.assert_allclose(
            _mesh_center(draft_core, object_id),
            rotate_point_about_pivot(
                centers[object_id], pivot, "z", 90.0
            ),
            atol=2.0e-3,
        )
        after = list(
            draft_core.state.get_object(object_id)["geometry"][
                "rotation_deg"
            ].values()
        )
        np.testing.assert_allclose(
            rotation_matrix_xyz(after),
            expected_delta @ rotation_matrix_xyz(before_rotations[object_id]),
            atol=2.0e-3,
        )


def test_group_scale_resizes_objects_and_their_offsets_from_center(draft_core):
    value, object_ids, centers, pivot = _group_drag_app(draft_core, "scale")
    before_sizes = {
        object_id: float(
            draft_core.state.get_object(object_id)["geometry"]["size_m"]["x"]
        )
        for object_id in object_ids
    }

    value._on_mouse(DragEvent(Gui.MouseEvent.Type.BUTTON_DOWN, 100, 100))
    value._on_mouse(DragEvent(Gui.MouseEvent.Type.DRAG, 125, 100))
    value._on_mouse(DragEvent(Gui.MouseEvent.Type.BUTTON_UP, 125, 100))

    factor = math.exp(0.5)
    for object_id in object_ids:
        np.testing.assert_allclose(
            _mesh_center(draft_core, object_id),
            scale_point_about_pivot(
                centers[object_id], pivot, "x", factor
            ),
            atol=1.0e-8,
        )
        assert np.isclose(
            draft_core.state.get_object(object_id)["geometry"]["size_m"]["x"],
            before_sizes[object_id] * factor,
        )


def test_extreme_scale_drag_is_ignored_instead_of_raising(draft_core):
    value, object_ids, _, _ = _group_drag_app(draft_core, "scale")
    before_sizes = {
        object_id: float(
            draft_core.state.get_object(object_id)["geometry"]["size_m"]["x"]
        )
        for object_id in object_ids
    }
    value._on_mouse(DragEvent(Gui.MouseEvent.Type.BUTTON_DOWN, 100, 100))

    assert (
        value._on_mouse(DragEvent(Gui.MouseEvent.Type.DRAG, 1.0e9, 100))
        == Results.CONSUMED
    )
    for object_id in object_ids:
        assert np.isclose(
            draft_core.state.get_object(object_id)["geometry"]["size_m"]["x"],
            before_sizes[object_id],
        )
