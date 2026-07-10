import numpy as np

from tools.proxy_mesh_editor.geometry.plane_mesher import build_plane_rectangle


SETTINGS = {
    "lower_percentile": 1.0,
    "upper_percentile": 99.0,
    "margin_ratio": 0.0,
    "min_extent": 0.01,
    "min_extent_ratio": 0.0,
    "vertical_alignment_max_dot": 0.3,
}


def test_rectangle_stays_on_plane_and_has_consistent_winding():
    x, y = np.meshgrid(np.linspace(-2.0, 2.0, 80), np.linspace(-1.0, 1.0, 60))
    points = np.column_stack([x.ravel(), y.ravel(), np.zeros(x.size)])
    points = np.vstack([points, [100.0, 100.0, 0.0]])

    model, normal, _, rectangle = build_plane_rectangle(
        inlier_points=points,
        plane_equation=np.asarray([0.0, 0.0, 2.0, 0.0]),
        up_vector=np.asarray([0.0, 0.0, 1.0]),
        settings=SETTINGS,
        scene_extent=10.0,
    )

    assert np.max(np.abs(rectangle.corners @ normal + model[3])) < 1e-9
    winding = np.cross(
        rectangle.corners[1] - rectangle.corners[0],
        rectangle.corners[2] - rectangle.corners[0],
    )
    assert np.dot(winding, normal) > 0.0
    assert rectangle.area < 20.0
    assert rectangle.corners.shape == (4, 3)


def test_vertical_rectangle_height_axis_follows_up_vector():
    y, z = np.meshgrid(np.linspace(-2.0, 2.0, 20), np.linspace(-1.0, 1.0, 20))
    points = np.column_stack([np.zeros(y.size), y.ravel(), z.ravel()])
    _, normal, _, rectangle = build_plane_rectangle(
        inlier_points=points,
        plane_equation=np.asarray([1.0, 0.0, 0.0, 0.0]),
        up_vector=np.asarray([0.0, 1.0, 0.0]),
        settings=SETTINGS,
        scene_extent=10.0,
    )
    assert abs(np.dot(normal, rectangle.basis_v)) < 1e-9
    assert np.dot(rectangle.basis_v, [0.0, 1.0, 0.0]) > 0.99

