import json

import numpy as np
import pytest

from tools.sionna_scenario.coverage_comparator import compare_coverage
from tools.sionna_scenario.reproducibility import (
    ReproducibilityError,
    analyze_reproducibility,
    compare_coverage_repeats,
    compare_path_repeats,
    compute_noise_statistics,
)


def _path(distance, path_index):
    return {
        "path_index": path_index,
        "transmitter": "tx",
        "receiver": "rx",
        "path_type": "specular_reflection",
        "interaction_count": 1,
        "interaction_object_ids": ["wall_000"],
        "distance_m": distance,
        "delay_s": distance / 299792458.0,
        "amplitude_magnitude": 0.5,
        "interaction_points_m": [[1.0, 2.0, 1.5]],
    }


def test_noise_statistics_use_maximum_absolute_delta_as_conservative_floor():
    result = compute_noise_statistics(np.asarray([-0.1, 0.2, 0.0]))
    assert result["mean_absolute_repeat_delta"] == pytest.approx(0.1)
    assert result["maximum_absolute_repeat_delta"] == pytest.approx(0.2)
    assert result["noise_floor"] == pytest.approx(0.2)


def test_coverage_repeat_noise_floor_and_ab_significance_are_consistent():
    first = np.asarray([[0.0, 0.0]])
    second = np.asarray([[0.1, -0.2]])
    repeat = compare_coverage_repeats([first, second])
    assert repeat["mean_absolute_repeat_delta_db"] == pytest.approx(0.15)
    assert repeat["maximum_absolute_repeat_delta_db"] == pytest.approx(0.2)
    assert repeat["noise_floor_db"] == pytest.approx(0.2)
    ab = compare_coverage(first, np.asarray([[0.05, -0.1]]), noise_floor_db=repeat)
    assert not ab["ab_change_exceeds_noise_floor"]


def test_path_repeats_match_by_structure_not_solver_order_or_path_index():
    first = [_path(6.0, 0), _path(7.0, 1)]
    second = [_path(7.0 + 5e-6, 81), _path(6.0 + 4e-6, 93)]
    second[0]["interaction_points_m"] = [[1.0 + 3e-6, 2.0, 1.5]]
    second[1]["interaction_points_m"] = [[1.0, 2.0 + 4e-6, 1.5]]
    result = compare_path_repeats(
        [first, second],
        deterministic_tolerances={"path_distance_m": 1e-5, "default": 1e-5},
    )
    assert result["path_counts_match"]
    assert result["path_structures_match"]
    assert result["distributions"]["path_distance_m"][
        "maximum_absolute_repeat_delta"
    ] == pytest.approx(5e-6)
    assert result["distributions"]["interaction_point_displacement_m"][
        "maximum_absolute_repeat_delta"
    ] == pytest.approx(4e-6)
    assert not result["exactly_deterministic"]
    assert result["reproducible_within_tolerance"]


def test_complete_reproducibility_document_is_json_safe_and_preserves_seed_roles():
    mask = np.ones((1, 2), dtype=bool)
    grid = np.asarray([[[0.0, 0.0, 1.5], [1.0, 0.0, 1.5]]])
    runs = [
        {
            "path_seed": 42,
            "coverage_seed": 43,
            "paths": [_path(6.0, 0)],
            "coverage": {
                "values": np.asarray([[-30.0, -31.0]]),
                "unit": "dB",
                "valid_mask": mask,
                "centers": grid,
            },
        },
        {
            "path_seed": 42,
            "coverage_seed": 43,
            "paths": [_path(6.0 + 5e-6, 99)],
            "coverage": {
                "values": np.asarray([[-30.0, -31.0001]]),
                "unit": "dB",
                "valid_mask": mask.copy(),
                "centers": grid.copy(),
            },
        },
    ]
    result = analyze_reproducibility(
        runs,
        coverage_tolerance_db=0.001,
        path_tolerances={"path_distance_m": 1e-5, "default": 1e-5},
    )
    assert result["same_seed"]
    assert result["reproducible_within_tolerance"]
    assert result["noise_floor"]["coverage_db"] == pytest.approx(0.0001)
    assert result["noise_floor"]["paths"]["path_distance_m"] == pytest.approx(5e-6)
    json.dumps(result)


def test_reproducibility_rejects_a_changed_valid_mask_in_strict_mode():
    repeats = [
        {"values": np.zeros((1, 2)), "valid_mask": [[True, True]]},
        {"values": np.zeros((1, 2)), "valid_mask": [[True, False]]},
    ]
    with pytest.raises(ReproducibilityError, match="valid masks"):
        compare_coverage_repeats(repeats)
