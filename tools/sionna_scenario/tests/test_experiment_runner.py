from types import SimpleNamespace

import pytest

from tools.sionna_scenario.experiment_runner import (
    ExperimentRunError,
    _assert_common_setup,
)


def _prepared(config_path, obstacles):
    return SimpleNamespace(
        scenario={
            "_phase2a_config_path": str(config_path),
            "synthetic_validation": bool(obstacles),
        },
        settings={"input": {"metric_obj": "room.obj"}},
        positions=[
            {
                "kind": "transmitter",
                "name": "tx",
                "resolved_position_m": [0, 0, 1.5],
            }
        ],
        obstacle_records=obstacles,
    )


def test_ab_setup_requires_the_same_phase2a_config(tmp_path):
    baseline = _prepared(tmp_path / "base.yaml", [])
    variant = _prepared(
        tmp_path / "other.yaml",
        [{"id": "blocker", "purpose": "validation_only"}],
    )
    with pytest.raises(ExperimentRunError, match="같은 Phase 2-A config"):
        _assert_common_setup(baseline, variant)

    variant.scenario["_phase2a_config_path"] = str(tmp_path / "base.yaml")
    _assert_common_setup(baseline, variant)

    variant.scenario["synthetic_validation"] = False
    with pytest.raises(ExperimentRunError, match="synthetic validation_only"):
        _assert_common_setup(baseline, variant)
