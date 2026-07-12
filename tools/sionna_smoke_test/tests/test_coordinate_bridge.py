import numpy as np

from tools.sionna_smoke_test.coordinate_bridge import CoordinateBridge


def test_known_transform_round_trip():
    forward = np.eye(4)
    forward[:3, :3] = 2.0 * np.eye(3)
    forward[:3, 3] = [1, -2, 3]
    inverse = np.linalg.inv(forward)
    bridge = CoordinateBridge.from_calibration(
        {
            "transform": {
                "T_metric_from_scene": forward.tolist(),
                "T_scene_from_metric": inverse.tolist(),
            }
        }
    )
    scene = np.asarray([[0, 0, 0], [1, 2, 3]], dtype=float)
    metric = bridge.scene_to_metric(scene)
    np.testing.assert_allclose(metric, [[1, -2, 3], [3, 2, 9]])
    np.testing.assert_allclose(bridge.metric_to_scene(metric), scene)
    assert bridge.validation_report(metric, scene)["success"]
