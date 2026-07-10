import numpy as np

from tools.proxy_mesh_editor.config import format_threshold_token
from tools.proxy_mesh_editor.geometry.normal_analyzer import compute_normal_up_scores


def test_normal_up_scores_use_absolute_dot_and_reject_invalid_normals():
    normals = np.asarray(
        [
            [0.0, 0.0, 2.0],
            [0.0, 0.0, -3.0],
            [1.0, 0.0, 0.0],
            [1.0, 0.0, 1.0],
            [0.0, 0.0, 0.0],
            [np.nan, 0.0, 1.0],
            [np.inf, 0.0, 1.0],
        ]
    )
    scores, valid = compute_normal_up_scores(normals, np.asarray([0.0, 0.0, 1.0]))

    assert valid.tolist() == [True, True, True, True, False, False, False]
    np.testing.assert_allclose(scores[:4], [1.0, 1.0, 0.0, np.sqrt(0.5)])
    assert np.all(np.isnan(scores[4:]))
    assert np.count_nonzero(valid & (scores <= np.sqrt(0.5))) == 2


def test_threshold_file_token_keeps_at_least_two_decimal_places():
    assert format_threshold_token(0.0) == "0_00"
    assert format_threshold_token(0.25) == "0_25"
    assert format_threshold_token(0.5) == "0_50"
    assert format_threshold_token(0.125) == "0_125"
