from pathlib import Path

import numpy as np
import pytest

from tools.rf_experiment.contracts import load_json
from tools.rf_experiment.sionna_rssi import (
    SionnaRssiError,
    aggregate_path_gain,
    path_gain_to_rssi_dbm,
    validate_solver_document,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOLVER_CONFIG = (
    PROJECT_ROOT
    / "scenes"
    / "pnu_classroom"
    / "experiments"
    / "classroom_20260723"
    / "configs"
    / "sionna_solver.json"
)


def test_path_gain_to_rssi_uses_transmitter_power_once():
    result = path_gain_to_rssi_dbm([1.0e-6, 1.0e-8], 20.0)

    assert result == pytest.approx([-40.0, -60.0])


def test_path_gain_rejects_zero_and_non_finite_values():
    with pytest.raises(SionnaRssiError, match="양수"):
        path_gain_to_rssi_dbm([0.0], 20.0)
    with pytest.raises(SionnaRssiError, match="양수"):
        path_gain_to_rssi_dbm([np.nan], 20.0)


def test_aggregate_path_gain_sums_only_valid_squared_amplitudes():
    valid = np.asarray([[[True, True, False]], [[True, False, False]]])
    real = np.asarray([[[3.0, 0.0, 100.0]], [[1.0, 9.0, 9.0]]])
    imag = np.asarray([[[4.0, 2.0, 100.0]], [[0.0, 9.0, 9.0]]])

    gain, count = aggregate_path_gain(valid, real, imag)

    assert np.allclose(gain, [[29.0], [1.0]])
    assert count.tolist() == [[2], [1]]


def test_checked_in_solver_contract_is_valid():
    report = validate_solver_document(load_json(SOLVER_CONFIG))

    assert report == {
        "success": True,
        "config_id": "classroom_path_and_radio_map_v1",
        "status": "provisional",
        "required_runtime": {
            "required_sionna_rt_version": "1.2.2",
            "required_mitsuba_version": "3.8.0",
            "required_drjit_version": "1.3.1",
        },
    }


def test_solver_contract_rejects_invalid_grid_ratio():
    document = load_json(SOLVER_CONFIG)
    document["sionna_rssi"]["validation"]["minimum_valid_grid_ratio"] = 1.1

    with pytest.raises(SionnaRssiError, match="1 이하"):
        validate_solver_document(document)
