import numpy as np

from tools.proxy_mesh_editor.calibration.frame_analysis import analyze_frame_candidates


def test_lowest_corner_and_longest_horizontal_edge_are_deterministic():
    bottom = np.asarray(
        [[0.0, 0.0, -1.0], [5.0, 0.0, -0.5], [5.0, 2.0, 0.0], [0.0, 2.0, -0.8]]
    )
    origin, x_axis, warnings = analyze_frame_candidates(
        bottom, np.asarray([0.0, 0.0, 1.0])
    )
    assert origin["recommended_corner_index"] == 0
    assert x_axis["recommended_edge_index"] == 0
    assert x_axis["recommended_start_corner"] == 0
    assert x_axis["recommended_end_corner"] == 1
    assert np.dot(x_axis["recommended_horizontal_direction"], [0.0, 0.0, 1.0]) == 0.0
    assert len(warnings) == 1
    assert "여러 개" in warnings[0]
