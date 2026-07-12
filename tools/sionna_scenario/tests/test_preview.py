import numpy as np

from tools.sionna_scenario.preview import _extent


def test_image_extent_uses_cell_edges_not_cell_centers():
    centers = np.asarray(
        [
            [[0.0, 10.0, 1.5], [2.0, 10.0, 1.5]],
            [[0.0, 14.0, 1.5], [2.0, 14.0, 1.5]],
        ]
    )
    assert _extent(centers) == [-1.0, 3.0, 8.0, 16.0]
