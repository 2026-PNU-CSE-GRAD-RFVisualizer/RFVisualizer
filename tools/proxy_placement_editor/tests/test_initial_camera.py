import numpy as np

from tools.proxy_placement_editor.gui.viewport import origin_camera_pose


def test_origin_camera_pose_starts_near_room_origin_and_looks_back_at_it():
    pose = origin_camera_pose(
        [0.0, 0.0, 0.0],
        [3.0, 3.0, 2.2],
        [0.5, 0.5, 0.5],
    )

    assert pose["eye"] == [3.0, 3.0, 2.2]
    assert pose["target"] == [0.5, 0.5, 0.5]
    np.testing.assert_allclose(np.linalg.norm(pose["forward"]), 1.0)
    assert pose["up"] == [0.0, 0.0, 1.0]
