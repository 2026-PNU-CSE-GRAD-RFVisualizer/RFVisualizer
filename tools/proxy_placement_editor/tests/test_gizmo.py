import numpy as np

from tools.proxy_placement_editor.gizmo import (
    axis_drag_parameter,
    make_gizmo_frame,
    make_front_gizmo_frame,
    pick_gizmo_axis,
    pick_projected_gizmo_axis,
    rotation_drag_angle_deg,
    screen_rotation_drag_angle_deg,
)


def _box_vertices():
    return np.asarray(
        [
            [-1.0, -0.5, -0.25],
            [1.0, -0.5, -0.25],
            [-1.0, 0.5, -0.25],
            [1.0, 0.5, -0.25],
            [-1.0, -0.5, 0.25],
            [1.0, -0.5, 0.25],
            [-1.0, 0.5, 0.25],
            [1.0, 0.5, 0.25],
        ]
    )


def _rotated_transform():
    value = np.eye(4)
    value[:3, :3] = np.asarray(
        [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]
    )
    return value


def test_world_local_axes_and_scale_is_always_local():
    world = make_gizmo_frame(_box_vertices(), _rotated_transform(), "translate", "world", 10.0)
    local = make_gizmo_frame(_box_vertices(), _rotated_transform(), "translate", "local", 10.0)
    scale = make_gizmo_frame(_box_vertices(), _rotated_transform(), "scale", "world", 10.0)
    np.testing.assert_allclose(world.axes, np.eye(3), atol=1.0e-12)
    np.testing.assert_allclose(local.axis("x"), [0.0, 1.0, 0.0], atol=1.0e-12)
    np.testing.assert_allclose(scale.axes, local.axes, atol=1.0e-12)


def test_front_frame_keeps_perspective_projection_and_moves_actual_handles_near():
    frame = make_gizmo_frame(
        _box_vertices(), np.eye(4), "translate", "world", 10.0
    )
    eye = np.asarray([1.0, -2.0, 20.0])
    forward = np.asarray([0.0, 0.0, -1.0])
    display = make_front_gizmo_frame(frame, eye, forward, 0.1)
    logical_end = frame.center + frame.axis("x") * frame.length
    display_end = display.center + display.axis("x") * display.length

    assert np.isclose(np.dot(display.center - eye, forward), 0.15)
    np.testing.assert_allclose(
        (display_end - eye)[:2] / abs(display_end[2] - eye[2]),
        (logical_end - eye)[:2] / abs(logical_end[2] - eye[2]),
        atol=1.0e-12,
    )


def test_axis_handle_pick_and_drag_parameter():
    frame = make_gizmo_frame(_box_vertices(), np.eye(4), "translate", "world", 10.0)
    origin = np.asarray([frame.length * 0.75, -2.0, 0.0])
    direction = np.asarray([0.0, 1.0, 0.0])
    hit = pick_gizmo_axis(origin, direction, frame)
    assert hit["axis"] == "x"
    parameter = axis_drag_parameter(origin, direction, frame.center, frame.axis("x"))
    assert np.isclose(parameter, frame.length * 0.75)


def test_rotation_ring_pick_and_signed_angle():
    frame = make_gizmo_frame(_box_vertices(), np.eye(4), "rotate", "world", 10.0)
    origin = np.asarray([frame.length, 0.0, 3.0])
    direction = np.asarray([0.0, 0.0, -1.0])
    hit = pick_gizmo_axis(origin, direction, frame)
    assert hit["axis"] == "z"
    angle = rotation_drag_angle_deg(
        frame.center,
        frame.axis("z"),
        frame.center + [frame.length, 0.0, 0.0],
        frame.center + [0.0, frame.length, 0.0],
    )
    assert np.isclose(angle, 90.0)


def test_screen_rotation_uses_projected_ring_tangent():
    angle = screen_rotation_drag_angle_deg(
        np.asarray([100.0, 100.0]),
        np.asarray([100.0, 55.0]),
        np.asarray([0.0, -1.0]),
        2.0,
    )
    assert np.isclose(angle, 90.0)


def test_screen_space_pick_uses_fixed_pixel_tolerance():
    frame = make_gizmo_frame(_box_vertices(), np.eye(4), "translate", "world", 10.0)

    def project(point):
        value = np.asarray(point, dtype=float)
        return np.asarray([100.0 + value[0] * 100.0, 100.0 - value[1] * 100.0, 0.5])

    endpoint = project(frame.center + frame.axis("x") * frame.length)
    hit = pick_projected_gizmo_axis(endpoint[:2] + [0.0, 20.0], frame, project)
    assert hit["axis"] == "x"
    assert hit["distance_px"] <= 20.0 + 1.0e-9
    assert pick_projected_gizmo_axis(endpoint[:2] + [0.0, 30.0], frame, project) is None
    guard_hit = pick_projected_gizmo_axis(
        endpoint[:2] + [0.0, 30.0], frame, project, tolerance_px=34.0
    )
    assert guard_hit["axis"] == "x"
