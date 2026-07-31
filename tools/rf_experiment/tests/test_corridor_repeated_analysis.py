from pathlib import Path

import pytest

from tools.rf_experiment.corridor_repeated_analysis import run_corridor_analysis


def test_corridor_analysis_uses_only_matching_environment_runs(tmp_path: Path):
    # Given: Test 1/2 share the Proxy environment while Test 3 does not.
    # When: the repeated corridor analysis is exported.
    report = run_corridor_analysis(tmp_path)

    # Then: Test 3 is excluded and the held-out Test result is reproducible.
    assert report.included_runs == ("Test_1_004838", "Test_2_010416")
    assert report.excluded_runs == ("Test_3_011702",)
    assert report.primary_variant == (
        "doors_glass_diffraction_scattering_authored_100m_d5"
    )
    assert report.primary_method == "global_bias_all4"
    assert report.primary_evaluation_scope == "repeat_mean_6"
    assert report.stable_calibration_points == ("cal-04",)
    assert report.primary_mae_db == pytest.approx(7.4765, abs=1.0e-4)
    expected = (
        "RESULTS_SUMMARY.md",
        "processed/measurements_reconstructed.csv",
        "processed/calibration_qc.csv",
        "processed/predictions.csv",
        "processed/metrics.csv",
        "processed/repeatability.csv",
        "processed/held_out_test_comparison.csv",
        "processed/analysis_report.json",
        "figures/primary_prediction_vs_measurement.png",
        "figures/solver_comparison.png",
        "figures/raw_rf_heatmap.png",
        "figures/calibrated_rf_heatmap.png",
    )
    assert all((tmp_path / relative).is_file() for relative in expected)
