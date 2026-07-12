import json

import pytest

from tools.sionna_scenario.path_comparator import (
    PathComparisonError,
    canonicalize_path_records,
    compare_paths,
)


def _path(
    path_type,
    distance,
    objects=(),
    path_index=0,
    transmitter="tx",
    receiver="rx_los",
):
    return {
        "path_index": path_index,
        "transmitter": transmitter,
        "receiver": receiver,
        "path_type": path_type,
        "interaction_count": len(objects),
        "interaction_object_ids": list(objects),
        "distance_m": distance,
        "delay_s": distance / 299792458.0,
        "amplitude_magnitude": 1.0 / distance,
    }


def test_path_order_and_path_index_do_not_create_false_changes():
    baseline = [
        _path("los", 4.0, path_index=0),
        _path("specular_reflection", 6.0, ("wall_000",), path_index=1),
    ]
    variant = [
        _path("specular_reflection", 6.0, ("wall_000",), path_index=91),
        _path("los", 4.0, path_index=72),
    ]
    result = compare_paths(baseline, variant)
    assert result["canonical_matching"]["matched_path_count"] == 2
    assert not result["canonical_matching"]["structure_changed"]
    assert not result["path_configuration_changed"]
    assert [item["path_type"] for item in canonicalize_path_records(baseline)] == [
        "los",
        "specular_reflection",
    ]


def test_small_canonical_numeric_change_can_be_below_repeat_noise_floor():
    baseline = [_path("specular_reflection", 6.0, ("wall_000",))]
    variant = [_path("specular_reflection", 6.0 + 5e-6, ("wall_000",))]
    result = compare_paths(
        baseline,
        variant,
        numerical_noise_floors={"path_distance_m": 1e-5, "default": 1.0},
    )
    distance = result["changes"]["distribution_changes"]["path_distance_m"]
    assert distance["absolute_sorted_delta"]["maximum_absolute_delta"] == pytest.approx(5e-6)
    assert not distance["change_exceeds_noise_floor"]
    assert not result["path_configuration_changed"]


def test_blocker_los_and_interaction_evidence_are_reported_separately():
    baseline = [
        _path("los", 4.0),
        _path("specular_reflection", 6.0, ("wall_000",)),
    ]
    variant = [
        _path("specular_reflection", 6.2, ("wall_000",)),
        _path("specular_reflection", 5.0, ("blocker_panel_000",)),
    ]
    result = compare_paths(
        baseline, variant, obstacle_object_ids=["blocker_panel_000"]
    )
    assert result["baseline"]["los_path_exists"]
    assert not result["variant"]["los_path_exists"]
    assert result["changes"]["los_path_count_delta"] == -1
    assert result["changes"]["specular_reflection_path_count_delta"] == 1
    evidence = result["obstacle_evidence"]
    assert evidence["los_change_evidence"]
    assert evidence["has_obstacle_interaction_evidence"]
    assert evidence["blocker_related_change"]
    assert evidence["variant_interacting_obstacle_ids"] == ["blocker_panel_000"]
    json.dumps(result)


def test_ordered_interaction_object_ids_are_part_of_canonical_identity():
    baseline = [_path("specular_reflection", 8.0, ("wall", "blocker"))]
    variant = [_path("specular_reflection", 8.0, ("blocker", "wall"))]
    result = compare_paths(baseline, variant)
    assert result["canonical_matching"]["structure_changed"]
    assert result["canonical_matching"]["matched_path_count"] == 0


def test_different_endpoints_are_rejected_by_default():
    baseline = [_path("los", 4.0, receiver="rx_a")]
    variant = [_path("los", 4.0, receiver="rx_b")]
    with pytest.raises(PathComparisonError, match="endpoint"):
        compare_paths(baseline, variant)

