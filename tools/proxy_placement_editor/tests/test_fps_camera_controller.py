import numpy as np
import pytest

from tools.proxy_placement_editor.fps_camera_controller import (
    FpsCameraController,
    FpsNavigationSettings,
    camera_pose_from_view,
    movement_basis,
)


def view_looking_positive_y(eye=(0.0, 0.0, 1.7)):
    world_from_camera = np.eye(4, dtype=float)
    world_from_camera[:3, 0] = [1.0, 0.0, 0.0]
    world_from_camera[:3, 1] = [0.0, 0.0, 1.0]
    world_from_camera[:3, 2] = [0.0, -1.0, 0.0]
    world_from_camera[:3, 3] = eye
    return np.linalg.inv(world_from_camera)


def test_camera_pose_is_recovered_from_view_matrix():
    eye, forward, right, up = camera_pose_from_view(
        view_looking_positive_y((1.0, 2.0, 3.0))
    )
    np.testing.assert_allclose(eye, [1.0, 2.0, 3.0])
    np.testing.assert_allclose(forward, [0.0, 1.0, 0.0])
    np.testing.assert_allclose(right, [1.0, 0.0, 0.0])
    np.testing.assert_allclose(up, [0.0, 0.0, 1.0])


def test_wasd_direction_diagonal_speed_and_sprint():
    settings = FpsNavigationSettings(
        movement_speed_mps=2.0,
        sprint_multiplier=3.0,
        max_frame_delta_seconds=1.0,
    )
    controller = FpsCameraController(settings)
    controller.activate(10.0)
    controller.set_key("w", True)
    np.testing.assert_allclose(
        controller.step(view_looking_positive_y(), 10.25), [0.0, 0.5, 0.0]
    )
    controller.set_key("d", True)
    diagonal = controller.step(view_looking_positive_y(), 10.5)
    assert np.linalg.norm(diagonal) == pytest.approx(0.5)
    sprint = controller.step(view_looking_positive_y(), 10.75, sprint=True)
    assert np.linalg.norm(sprint) == pytest.approx(1.5)


def test_frame_delta_is_clamped_and_deactivation_clears_keys():
    controller = FpsCameraController(
        FpsNavigationSettings(
            movement_speed_mps=2.0,
            max_frame_delta_seconds=0.05,
        )
    )
    controller.activate(0.0)
    controller.set_key("a", True)
    np.testing.assert_allclose(
        controller.step(view_looking_positive_y(), 5.0), [-0.1, 0.0, 0.0]
    )
    controller.deactivate()
    assert controller.pressed_keys == set()
    np.testing.assert_allclose(
        controller.step(view_looking_positive_y(), 6.0), [0.0, 0.0, 0.0]
    )


def test_horizontal_basis_removes_pitch_and_rejects_invalid_view():
    forward, right = movement_basis(
        np.array([0.0, 1.0, 2.0]), np.array([1.0, 0.0, 0.0])
    )
    np.testing.assert_allclose(forward, [0.0, 1.0, 0.0])
    np.testing.assert_allclose(right, [1.0, 0.0, 0.0])
    with pytest.raises(ValueError, match="singular"):
        camera_pose_from_view(np.zeros((4, 4)))
    with pytest.raises(ValueError, match="finite 4x4"):
        camera_pose_from_view(np.eye(3))
