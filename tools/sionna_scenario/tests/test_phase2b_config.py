from copy import deepcopy
from pathlib import Path

import pytest

from tools.sionna_scenario.config import (
    ScenarioConfigError,
    load_experiment,
    load_scenario,
    public_document,
    validate_experiment,
    validate_scenario,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCENARIO_DIR = PROJECT_ROOT / "tools" / "sionna_scenario" / "tests" / "fixtures"
EXPERIMENT = (
    PROJECT_ROOT
    / "tools"
    / "sionna_scenario"
    / "tests"
    / "fixtures"
    / "phase2b_ab_experiment.yaml"
)


def test_checked_in_scenarios_keep_empty_synthetic_and_draft_contracts():
    empty = load_scenario(SCENARIO_DIR / "empty.yaml")
    blocker = load_scenario(
        SCENARIO_DIR / "synthetic_blocker.yaml"
    )
    draft = load_scenario(SCENARIO_DIR / "proxy_draft.yaml")

    assert empty["scenario"]["obstacles"] == []
    assert empty["scenario"]["synthetic_validation"] is False

    enabled = [
        value for value in blocker["scenario"]["obstacles"] if value["enabled"]
    ]
    assert len(enabled) == 1
    assert enabled[0]["purpose"] == "validation_only"
    assert enabled[0]["physical_object"] is False
    assert enabled[0]["confidence"] == "synthetic"
    assert blocker["scenario"]["synthetic_validation"] is True

    assert draft["scenario"]["obstacles"]
    assert not any(value["enabled"] for value in draft["scenario"]["obstacles"])
    assert all(
        value["geometry"]["position_m"] is None
        for value in draft["scenario"]["obstacles"]
    )


def test_checked_in_ab_experiment_resolves_common_seeded_solver_contract():
    document = load_experiment(EXPERIMENT)
    experiment = document["experiment"]

    assert Path(experiment["_baseline_scenario_path"]).name == (
        "empty.yaml"
    )
    assert [Path(value).name for value in experiment["_variant_scenario_paths"]] == [
        "synthetic_blocker.yaml"
    ]
    assert experiment["solver"]["path_seed"] == 42
    assert experiment["solver"]["coverage_seed"] == 43
    assert experiment["solver"]["max_depth"] == 2
    assert experiment["comparison"]["coverage_delta_unit"] == "dB"
    assert experiment["comparison"]["require_common_grid"] is True
    assert experiment["comparison"]["require_common_valid_mask"] is True
    assert experiment["reproducibility"] == {
        "rerun_baseline": True,
        "baseline_repeat_count": 2,
    }


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda value: value.update(schema_version="2.0"), "schema_version"),
        (lambda value: value["scenario"].update(status="final"), "provisional"),
        (
            lambda value: value["scenario"].update(physically_validated=True),
            "physically_validated",
        ),
        (
            lambda value: value["scenario"].update(
                synthetic_validation=True, obstacles=[]
            ),
            "validation_only",
        ),
    ],
)
def test_scenario_high_level_provisional_and_synthetic_markers_are_strict(
    mutation, match
):
    document = load_scenario(SCENARIO_DIR / "empty.yaml")
    mutation(document)
    with pytest.raises(ScenarioConfigError, match=match):
        validate_scenario(document)


def test_duplicate_obstacle_ids_are_rejected_at_scenario_boundary():
    document = load_scenario(
        SCENARIO_DIR / "synthetic_blocker.yaml"
    )
    duplicate = deepcopy(document["scenario"]["obstacles"][0])
    duplicate["enabled"] = False
    document["scenario"]["obstacles"].append(duplicate)
    with pytest.raises(ScenarioConfigError, match="ID"):
        validate_scenario(document)


def test_experiment_rejects_non_db_delta_and_single_baseline_repeat():
    document = load_experiment(EXPERIMENT)
    document["experiment"]["comparison"]["coverage_delta_unit"] = "linear"
    with pytest.raises(ScenarioConfigError, match="dB"):
        validate_experiment(document)

    document = load_experiment(EXPERIMENT)
    document["experiment"]["reproducibility"]["baseline_repeat_count"] = 1
    with pytest.raises(ScenarioConfigError, match="최소 두 번"):
        validate_experiment(document)

    document = load_experiment(EXPERIMENT)
    document["experiment"]["solver"]["reuse_phase2a_settings"] = False
    with pytest.raises(ScenarioConfigError, match="reuse_phase2a_settings"):
        validate_experiment(document)

    document = load_experiment(EXPERIMENT)
    document["experiment"]["reproducibility"]["rerun_baseline"] = False
    with pytest.raises(ScenarioConfigError, match="rerun_baseline=true"):
        validate_experiment(document)


@pytest.mark.parametrize(
    "field,value",
    [
        ("carrier_frequency_hz", True),
        ("max_depth", float("inf")),
    ],
)
def test_solver_numeric_fields_reject_bool_and_infinity(field, value):
    document = load_experiment(EXPERIMENT)
    document["experiment"]["solver"][field] = value
    with pytest.raises(ScenarioConfigError):
        validate_experiment(document)


def test_scenario_rejects_conflicting_material_category_and_preset():
    document = load_scenario(
        SCENARIO_DIR / "synthetic_blocker.yaml"
    )
    document["scenario"]["obstacles"][0]["material"]["preset"] = "metal"
    with pytest.raises(ScenarioConfigError, match="category와 preset"):
        validate_scenario(document)


def test_public_document_removes_only_loader_annotations_recursively():
    document = load_experiment(EXPERIMENT)
    document["experiment"]["nested"] = [{"_private": 1, "public": 2}]
    exported = public_document(document)

    assert "_source_path" not in exported
    assert "_baseline_scenario_path" not in exported["experiment"]
    assert "_variant_scenario_paths" not in exported["experiment"]
    assert exported["experiment"]["nested"] == [{"public": 2}]
