from types import SimpleNamespace

import numpy as np

from tools.sionna_scenario.preview import _extent, _room_hull


def test_image_extent_uses_cell_edges_not_cell_centers():
    centers = np.asarray(
        [
            [[0.0, 10.0, 1.5], [2.0, 10.0, 1.5]],
            [[0.0, 14.0, 1.5], [2.0, 14.0, 1.5]],
        ]
    )
    assert _extent(centers) == [-1.0, 3.0, 8.0, 16.0]


def test_room_preview_preserves_concave_bottom_corner_order():
    bottom_corners = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [4.0, 0.0, 0.0],
            [4.0, 4.0, 0.0],
            [0.0, 4.0, 0.0],
            [0.0, 3.0, 0.0],
            [2.0, 3.0, 0.0],
            [2.0, 1.0, 0.0],
            [0.0, 1.0, 0.0],
        ]
    )
    scene = SimpleNamespace(
        metric_metadata={"bottom_corners": bottom_corners.tolist()},
        vertices=np.vstack([bottom_corners, bottom_corners + [0.0, 0.0, 2.5]]),
    )

    np.testing.assert_allclose(_room_hull(scene), bottom_corners[:, :2])
