import numpy as np
import pytest

from tools.proxy_mesh_editor.calibration.metric_transform import (
    MetricTransformError,
    build_metric_transform,
    inverse_transform_points,
    transform_diagnostics,
    transform_points,
)


VALIDATION = {
    "maximum_rotation_determinant_error": 1e-8,
    "maximum_orthogonality_error": 1e-8,
    "maximum_axis_alignment_error": 1e-8,
    "maximum_round_trip_error": 1e-8,
}


def _frame(origin=0, start=0, end=1):
    return {
        "origin": {"corner_index": origin},
        "x_axis": {"start_corner": start, "end_corner": end},
    }


def test_identity_metric_transform_keeps_points_unchanged():
    envelope = {
        "up_vector": [0.0, 0.0, 1.0],
        "bottom_corners": [[0, 0, 0], [4, 0, 0], [4, 3, 0], [0, 3, 0]],
    }
    transform = build_metric_transform(envelope, _frame(), 1.0, VALIDATION)
    points = np.asarray([[0.0, 0.0, 0.0], [4.0, 3.0, 2.0]])
    np.testing.assert_allclose(transform_points(points, transform), points)
    np.testing.assert_allclose(transform.rotation, np.eye(3))
    assert np.linalg.det(transform.rotation) == pytest.approx(1.0)


def test_rotation_scale_and_translation_make_canonical_room():
    origin = np.asarray([4.0, 5.0, 6.0])
    x = np.asarray([1.0, 0.0, 0.0])
    y = np.asarray([0.0, 0.0, 1.0])
    z = np.asarray([0.0, -1.0, 0.0])
    bottom = np.asarray([origin, origin + 4 * x, origin + 4 * x + 3 * y, origin + 3 * y])
    envelope = {"up_vector": z.tolist(), "bottom_corners": bottom.tolist()}
    transform = build_metric_transform(envelope, _frame(), 2.0, VALIDATION)
    top = bottom + 3 * z
    expected_bottom = np.asarray([[0, 0, 0], [8, 0, 0], [8, 6, 0], [0, 6, 0]])
    np.testing.assert_allclose(transform_points(bottom, transform), expected_bottom)
    np.testing.assert_allclose(transform_points(top, transform)[:, 2], 6.0)
    assert transform_diagnostics(transform)["origin_metric_coordinate"] == [0.0, 0.0, 0.0]


def test_random_points_round_trip_with_small_error():
    envelope = {
        "up_vector": [0.2, -0.9, 0.3],
        "bottom_corners": [[2, 3, 4], [5, 4, 5], [4, 7, 6], [1, 6, 5]],
    }
    transform = build_metric_transform(envelope, _frame(), 1.7, VALIDATION)
    points = np.random.RandomState(7).normal(size=(100, 3))
    restored = inverse_transform_points(transform_points(points, transform), transform)
    np.testing.assert_allclose(restored, points, atol=1e-12)


@pytest.mark.parametrize("scale", [0.0, -1.0, float("nan"), float("inf")])
def test_nonpositive_or_nonfinite_scale_is_rejected(scale):
    envelope = {
        "up_vector": [0, 0, 1],
        "bottom_corners": [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
    }
    with pytest.raises(MetricTransformError, match="양수"):
        build_metric_transform(envelope, _frame(), scale, VALIDATION)


def test_out_of_range_and_parallel_x_axis_are_rejected():
    envelope = {
        "up_vector": [0, 0, 1],
        "bottom_corners": [[0, 0, 0], [0, 0, 2], [1, 1, 0]],
    }
    with pytest.raises(MetricTransformError, match="범위"):
        build_metric_transform(envelope, _frame(origin=9), 1.0, VALIDATION)
    with pytest.raises(MetricTransformError, match="평행"):
        build_metric_transform(envelope, _frame(start=0, end=1), 1.0, VALIDATION)


@pytest.mark.parametrize("up", [[0, 0, 0], [float("nan"), 0, 1], [float("inf"), 0, 1]])
def test_invalid_scene_up_is_rejected(up):
    envelope = {
        "up_vector": up,
        "bottom_corners": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
    }
    with pytest.raises(ValueError):
        build_metric_transform(envelope, _frame(), 1.0, VALIDATION)
