import numpy as np
import pytest

from tools.proxy_mesh_editor.envelope.intersections import (
    PlaneIntersectionError,
    acute_plane_angle_degrees,
    solve_three_plane_intersection,
)


def test_three_plane_intersection_returns_residual_diagnostics():
    point, diagnostics = solve_three_plane_intersection(
        [
            np.asarray([1.0, 0.0, 0.0, -2.0]),
            np.asarray([0.0, 1.0, 0.0, -3.0]),
            np.asarray([0.0, 0.0, 1.0, -4.0]),
        ],
        residual_tolerance=1e-9,
        max_condition_number=1e12,
    )
    np.testing.assert_allclose(point, [2.0, 3.0, 4.0])
    assert diagnostics["condition_number"] == pytest.approx(1.0)
    assert diagnostics["maximum_residual"] <= 1e-12


def test_singular_three_plane_intersection_is_rejected():
    with pytest.raises(PlaneIntersectionError, match="singular"):
        solve_three_plane_intersection(
            [
                np.asarray([1.0, 0.0, 0.0, 0.0]),
                np.asarray([1.0, 0.0, 0.0, -1.0]),
                np.asarray([0.0, 0.0, 1.0, 0.0]),
            ],
            residual_tolerance=1e-9,
            max_condition_number=1e12,
        )


def test_plane_angle_ignores_normal_sign():
    assert acute_plane_angle_degrees(
        np.asarray([1.0, 0.0, 0.0, 0.0]),
        np.asarray([-1.0, 0.0, 0.0, 1.0]),
    ) == pytest.approx(0.0)
