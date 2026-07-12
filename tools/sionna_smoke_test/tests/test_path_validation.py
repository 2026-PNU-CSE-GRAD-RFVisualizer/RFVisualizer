import numpy as np
import pytest

from tools.sionna_smoke_test.path_test import (
    SPEED_OF_LIGHT_M_PER_S,
    extract_path_records,
    validate_los_records,
    validate_reflection_records,
)


def _arrays():
    return {
        "valid": np.asarray([[[True, True]]]),
        "tau": np.asarray([[[4.0 / SPEED_OF_LIGHT_M_PER_S, 6.0 / SPEED_OF_LIGHT_M_PER_S]]]),
        "theta_t": np.zeros((1, 1, 2)),
        "phi_t": np.zeros((1, 1, 2)),
        "theta_r": np.zeros((1, 1, 2)),
        "phi_r": np.zeros((1, 1, 2)),
        "a_real": np.asarray([[[1.0, 0.5]]]),
        "a_imag": np.zeros((1, 1, 2)),
        "interactions": np.asarray([[[[0, 1]]]], dtype=np.uint32),
        "vertices": np.asarray([[[[[0, 0, 0], [1, 1, 0]]]]], dtype=float),
        "objects": np.asarray([[[[0, 3]]]], dtype=np.uint32),
    }


def test_mock_paths_distinguish_los_and_reflection_and_validate_distance():
    records = extract_path_records(_arrays(), ["tx"], ["rx"])
    assert [value["path_type"] for value in records] == ["los", "specular_reflection"]
    los = validate_los_records(records, np.asarray([0, 0, 0]), np.asarray([4, 0, 0]), 1, 1e-8)
    assert los["success"]
    assert los["distance_error_m"] == pytest.approx(0.0)
    reflection = validate_reflection_records(records, 2)
    assert reflection["reflection_path_count"] == 1
    assert reflection["status"] == "pass"
