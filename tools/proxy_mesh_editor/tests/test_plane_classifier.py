import numpy as np

from tools.proxy_mesh_editor.geometry.plane_classifier import classify_plane


SETTINGS = {
    "horizontal_max_angle_deg": 15.0,
    "vertical_max_deviation_deg": 15.0,
    "boundary_height_ratio": 0.15,
}


def test_floor_ceiling_and_wall_are_only_suggestions():
    height_range = {"min": -2.0, "max": 2.0}
    up = np.asarray([0.0, 1.0, 0.0])

    floor = classify_plane(
        normal=up,
        centroid=np.asarray([0.0, -1.9, 0.0]),
        up_vector=up,
        height_range=height_range,
        settings=SETTINGS,
    )
    ceiling = classify_plane(
        normal=-up,
        centroid=np.asarray([0.0, 1.9, 0.0]),
        up_vector=up,
        height_range=height_range,
        settings=SETTINGS,
    )
    wall = classify_plane(
        normal=np.asarray([1.0, 0.0, 0.0]),
        centroid=np.zeros(3),
        up_vector=up,
        height_range=height_range,
        settings=SETTINGS,
    )

    assert floor.orientation == "horizontal"
    assert floor.suggested_semantic == "floor"
    assert ceiling.suggested_semantic == "ceiling"
    assert wall.orientation == "vertical"
    assert wall.suggested_semantic == "wall"
    assert 0.0 <= wall.confidence <= 1.0

