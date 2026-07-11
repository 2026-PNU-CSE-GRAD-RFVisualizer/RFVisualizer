import numpy as np

from tools.proxy_mesh_editor.calibration.metric_transform import (
    build_metric_transform,
    transform_plane,
    transform_points,
)


VALIDATION = {
    "maximum_rotation_determinant_error": 1e-8,
    "maximum_orthogonality_error": 1e-8,
    "maximum_axis_alignment_error": 1e-8,
    "maximum_round_trip_error": 1e-8,
}


def test_plane_equation_follows_rotation_scale_and_translation():
    origin = np.asarray([3.0, 4.0, 5.0])
    envelope = {
        "up_vector": [0.0, -1.0, 0.0],
        "bottom_corners": [origin, origin + [2, 0, 0], origin + [2, 0, 3], origin + [0, 0, 3]],
    }
    transform = build_metric_transform(
        envelope,
        {"origin": {"corner_index": 0}, "x_axis": {"start_corner": 0, "end_corner": 1}},
        2.0,
        VALIDATION,
    )
    source_plane = np.asarray([0.0, 1.0, 0.0, -4.0])
    metric_plane = transform_plane(source_plane, transform)
    source_points = np.asarray([origin, origin + [2, 0, 0], origin + [0, 0, 3]])
    metric_points = transform_points(source_points, transform)
    residuals = np.abs(metric_points @ metric_plane[:3] + metric_plane[3])
    assert np.max(residuals) < 1e-12
    np.testing.assert_allclose(abs(metric_plane[2]), 1.0)
