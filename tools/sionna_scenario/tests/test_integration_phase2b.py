import os
from pathlib import Path

import numpy as np
import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_SIONNA_PHASE2B_INTEGRATION") != "1",
    reason=(
        "RUN_SIONNA_PHASE2B_INTEGRATION=1일 때만 실제 empty room 대 synthetic "
        "blocker Sionna RT A/B 통합 시험을 실행합니다."
    ),
)


def test_actual_sionna_empty_vs_synthetic_blocker_changes_los_and_coverage(
    tmp_path: Path,
):
    pytest.importorskip(
        "sionna.rt", reason="현재 Python 환경에 실제 Sionna RT가 없습니다."
    )
    from tools.sionna_scenario.config import load_experiment
    from tools.sionna_scenario.experiment_runner import run_ab_experiment

    project_root = Path(__file__).resolve().parents[3]
    experiment_path = (
        project_root
        / "configs"
        / "sionna"
        / "experiments"
        / "pnu_classroom_phase2b_ab.yaml"
    )
    result = run_ab_experiment(
        load_experiment(experiment_path), tmp_path / "phase2b_integration"
    )

    rx_los = result["path_comparison"]["rx_los"]
    assert rx_los["baseline"]["los_path_exists"] is True
    assert rx_los["variant"]["los_path_exists"] is False
    assert rx_los["obstacle_evidence"]["blocker_related_change"] is True

    coverage = result["coverage_comparison"]
    assert coverage["common_valid_cell_count"] > 0
    assert np.isfinite(coverage["mean_delta_db"])
    assert np.isfinite(coverage["mean_absolute_delta_db"])
    assert np.isfinite(coverage["maximum_absolute_delta_db"])
    assert coverage["maximum_absolute_delta_db"] > 0.0
    assert coverage["ab_change_exceeds_noise_floor"] is True

    manifest = result["variant_run"]["manifest"]
    assert manifest["object_layers_independent"] is True
    assert manifest["room_object_count"] == 6
    assert manifest["obstacle_object_count"] == 1
    assert manifest["base_scene"]["room_envelope_modified"] is False
    assert manifest["coordinate_bridge_validation"]["success"] is True
    assert result["validation"]["overall_success"] is True

