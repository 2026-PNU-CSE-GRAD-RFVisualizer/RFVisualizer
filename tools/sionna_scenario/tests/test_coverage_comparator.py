import json

import numpy as np
import pytest

from tools.sionna_scenario.coverage_comparator import (
    CoverageComparisonError,
    compare_coverage,
    to_db,
)


def _centers():
    return np.asarray(
        [
            [[0.0, 0.0, 1.5], [1.0, 0.0, 1.5]],
            [[0.0, 1.0, 1.5], [1.0, 1.0, 1.5]],
        ]
    )


def test_compare_db_coverage_computes_required_delta_statistics():
    baseline = {
        "values": np.asarray([[-10.0, -20.0], [-30.0, -40.0]]),
        "unit": "dB",
        "valid_mask": np.ones((2, 2), dtype=bool),
        "inside_mask": np.ones((2, 2), dtype=bool),
        "centers": _centers(),
    }
    variant = {
        **baseline,
        "values": np.asarray([[-9.0, -22.0], [-30.0, -36.0]]),
        "centers": _centers().copy(),
    }
    result = compare_coverage(baseline, variant)
    assert result["common_valid_cell_count"] == 4
    assert result["mean_delta_db"] == pytest.approx(0.75)
    assert result["mean_absolute_delta_db"] == pytest.approx(1.75)
    assert result["median_delta_db"] == pytest.approx(0.5)
    assert result["minimum_delta_db"] == pytest.approx(-2.0)
    assert result["maximum_delta_db"] == pytest.approx(4.0)
    assert result["abs_delta_gt_1_db_cell_count"] == 2
    assert result["abs_delta_gt_3_db_cell_count"] == 1
    assert result["positive_delta_cell_count"] == 2
    assert result["negative_delta_cell_count"] == 1
    assert result["delta_db"] == [[1.0, -2.0], [0.0, 4.0]]
    json.dumps(result)


def test_linear_path_gain_is_converted_once_and_noise_floor_is_applied():
    baseline = np.asarray([[1e-3, 1e-4]])
    variant = np.asarray([[1e-3, 10 ** (-3.9)]])
    result = compare_coverage(
        baseline,
        variant,
        baseline_unit="unitless_linear",
        variant_unit="linear_path_gain",
        noise_floor_db=1.1,
    )
    assert to_db(baseline, "linear")[0, 0] == pytest.approx(-30.0)
    assert result["delta_db"][0][0] == pytest.approx(0.0)
    assert result["delta_db"][0][1] == pytest.approx(1.0)
    assert not result["ab_change_exceeds_noise_floor"]


def test_mask_mismatch_is_rejected_in_strict_mode_and_intersected_otherwise():
    baseline_mask = np.asarray([[True, True], [True, False]])
    variant_mask = np.asarray([[True, False], [True, False]])
    baseline = {"values": np.zeros((2, 2)), "valid_mask": baseline_mask}
    variant = {"values": np.ones((2, 2)), "valid_mask": variant_mask}
    with pytest.raises(CoverageComparisonError, match="valid masks"):
        compare_coverage(baseline, variant)
    result = compare_coverage(
        baseline, variant, require_common_valid_mask=False
    )
    assert result["common_valid_cell_count"] == 2
    assert result["valid_mask_validation"]["mask_mismatch_cell_count"] == 1
    assert result["delta_db"] == [[1.0, None], [1.0, None]]


def test_grid_coordinate_mismatch_is_rejected_but_shape_only_arrays_are_supported():
    baseline = {"values": np.zeros((2, 2)), "centers": _centers()}
    moved = _centers()
    moved[0, 0, 0] += 0.01
    variant = {"values": np.zeros((2, 2)), "centers": moved}
    with pytest.raises(CoverageComparisonError, match="grids"):
        compare_coverage(baseline, variant)
    shape_only = compare_coverage(np.zeros((2, 2)), np.ones((2, 2)))
    assert shape_only["grid_validation"]["mode"] == "shape_only"


def test_nonpositive_linear_values_are_excluded_from_common_valid_cells():
    baseline = {
        "values": np.asarray([[1.0, 0.0]]),
        "unit": "linear",
        "valid_mask": np.asarray([[True, False]]),
    }
    variant = {
        "values": np.asarray([[2.0, -1.0]]),
        "unit": "linear",
        "valid_mask": np.asarray([[True, False]]),
    }
    result = compare_coverage(baseline, variant)
    assert result["common_valid_cell_count"] == 1
    assert result["delta_db"][0][1] is None

