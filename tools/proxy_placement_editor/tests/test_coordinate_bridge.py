import numpy as np

from tools.proxy_placement_editor.coordinate_bridge import PlacementCoordinateBridge


def test_vertex_and_transform_round_trip(placement_scene):
    bridge = PlacementCoordinateBridge.from_calibration(placement_scene.calibration)
    vertices = np.array([[0.0, 0.0, 0.0], [-5.0, -5.0, 1.5], [-15.0, -10.0, 2.0]])
    transform = np.eye(4)
    transform[:3, 3] = [-5.0, -5.0, 1.0]
    report = bridge.report(vertices, transform)
    assert report["success"]
    assert report["maximum_error"] < 1e-14
