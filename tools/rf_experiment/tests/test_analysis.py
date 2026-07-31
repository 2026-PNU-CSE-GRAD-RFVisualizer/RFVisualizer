import csv
import json
import math
from pathlib import Path

import numpy as np
import pytest

from tools.rf_experiment.analysis import (
    compare_methods,
    idw_predict,
    load_sionna_grid,
    load_sionna_points,
    load_summary,
    regression_metrics,
    run_analysis,
)
from tools.rf_experiment.contracts import SUMMARY_REQUIRED_COLUMNS


PROJECT_ROOT = Path(__file__).resolve().parents[3]
METHOD_CONFIG = (
    PROJECT_ROOT
    / "configs"
    / "rf_experiment"
    / "classroom_20260723"
    / "method_config.json"
)
IDW_SETTINGS = {
    "power": 2.0,
    "epsilon_distance_power": 1.0e-12,
    "exact_match_tolerance_m": 1.0e-9,
}


def _sionna_rssi(x, y):
    distance_term = 1.0 + (x - 1.5) ** 2 + 0.7 * (y - 1.0) ** 2
    return -36.0 - 10.0 * math.log10(distance_term)


def _write_csv(path, fieldnames, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _synthetic_inputs(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    calibration_xy = [(1.0, 1.0), (13.0, 1.0), (1.0, 9.0), (13.0, 9.0)]
    test_xy = [
        (x, y)
        for y in (2.0, 5.0, 8.0)
        for x in (2.0, 4.5, 7.0, 9.5, 12.0)
    ]
    points = [
        ("cal-{:02d}".format(index), "calibration", x, y)
        for index, (x, y) in enumerate(calibration_xy, start=1)
    ] + [
        ("test-{:02d}".format(index), "test", x, y)
        for index, (x, y) in enumerate(test_xy, start=1)
    ]
    summary_rows = []
    sionna_point_rows = []
    for index, (point_id, role, x, y) in enumerate(points, start=1):
        predicted = _sionna_rssi(x, y)
        measured = predicted + 4.0
        summary_rows.append(
            {
                "point_id": point_id,
                "point_role": role,
                "node_id": "node-{:02d}".format(index),
                "x": x,
                "y": y,
                "z": 1.2,
                "sample_count": 30,
                "median_raw": measured - 0.2,
                "median_filtered": measured,
                "mean_filtered": measured,
                "std_filtered": 0.8,
                "device_offset_db": 0.0,
                "corrected_rssi": measured,
            }
        )
        sionna_point_rows.append(
            {
                "point_id": point_id,
                "x": x,
                "y": y,
                "z": 1.2,
                "sionna_rssi_dbm": predicted,
            }
        )
    grid_rows = []
    for row, y in enumerate((1.0, 3.0, 5.0, 7.0, 9.0)):
        for column, x in enumerate((1.0, 4.0, 7.0, 10.0, 13.0)):
            grid_rows.append(
                {
                    "grid_id": "grid-{:02d}-{:02d}".format(row, column),
                    "row": row,
                    "column": column,
                    "x": x,
                    "y": y,
                    "z": 1.2,
                    "sionna_rssi_dbm": _sionna_rssi(x, y),
                }
            )
    summary_path = tmp_path / "measurements_summary.csv"
    points_path = tmp_path / "sionna_points.csv"
    grid_path = tmp_path / "sionna_grid.csv"
    _write_csv(summary_path, SUMMARY_REQUIRED_COLUMNS, summary_rows)
    _write_csv(
        points_path,
        ("point_id", "x", "y", "z", "sionna_rssi_dbm"),
        sionna_point_rows,
    )
    _write_csv(
        grid_path,
        ("grid_id", "row", "column", "x", "y", "z", "sionna_rssi_dbm"),
        grid_rows,
    )
    return summary_path, points_path, grid_path


def test_idw_returns_exact_sample_and_weighted_value():
    samples = np.asarray([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]])
    values = np.asarray([10.0, 20.0])
    queries = np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])

    result = idw_predict(samples, values, queries, **IDW_SETTINGS)

    assert result == pytest.approx([10.0, 15.0])


def test_regression_metrics_reports_uncertainty_for_six_held_out_points():
    # Given: six held-out Test measurements and predictions with known errors.
    actual = np.asarray([-40.0, -45.0, -50.0, -55.0, -60.0, -65.0])
    predicted = actual + np.asarray([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])

    # When: prediction reliability is evaluated.
    result = regression_metrics(actual, predicted)

    # Then: accuracy, bias, association, uncertainty, and sample sufficiency
    # are all explicit instead of treating MAE/RMSE as complete confidence.
    assert result["sample_count"] == 6
    assert result["mae"] == pytest.approx(3.5)
    assert result["mean_error_db"] == pytest.approx(3.5)
    assert result["maximum_absolute_error_db"] == pytest.approx(6.0)
    assert result["pearson_r"] == pytest.approx(1.0)
    assert result["mae_ci95_low_db"] <= result["mae"]
    assert result["mae_ci95_high_db"] >= result["mae"]
    assert result["small_sample_warning"] is True


def test_test_measurements_are_not_used_to_fit_predictions(tmp_path):
    summary_path, points_path, grid_path = _synthetic_inputs(tmp_path)
    summary = load_summary(summary_path)
    points = load_sionna_points(points_path)
    grid = load_sionna_grid(grid_path)
    original = compare_methods(summary, points, grid, IDW_SETTINGS)
    changed_summary = [dict(row) for row in summary]
    for row in changed_summary:
        if row["role"] == "test":
            row["actual_rssi_dbm"] += 100.0

    changed = compare_methods(changed_summary, points, grid, IDW_SETTINGS)

    for method in ("raw_sionna", "plain_idw", "residual_idw"):
        assert changed["test_predictions"][method] == pytest.approx(
            original["test_predictions"][method]
        )
        assert changed["grid_predictions"][method] == pytest.approx(
            original["grid_predictions"][method]
        )
    assert original["data_split_validation"]["test_values_used_in_fitting"] is False


def test_end_to_end_analysis_writes_metrics_and_shared_scale_heatmaps(tmp_path):
    summary_path, points_path, grid_path = _synthetic_inputs(tmp_path)
    output = tmp_path / "analysis"

    report = run_analysis(
        summary_path,
        points_path,
        grid_path,
        METHOD_CONFIG,
        output,
    )

    assert report["success"] is True
    assert report["metrics"]["residual_idw"]["mae"] < 1.0e-10
    assert (
        report["metrics"]["residual_idw"]["mae"]
        < report["metrics"]["plain_idw"]["mae"]
    )
    assert all(report["minimum_success_condition"].values())
    assert len(report["shared_heatmap_color_limits_dbm"]) == 2
    for filename in (
        "measured_points.png",
        "prediction_vs_measurement.png",
        "raw_sionna_heatmap.png",
        "plain_idw_heatmap.png",
        "residual_idw_heatmap.png",
    ):
        assert (output / "figures" / filename).is_file()
    stored = json.loads((output / "processed" / "analysis_report.json").read_text())
    assert stored["files"]["analysis_report_json"].endswith("analysis_report.json")
    assert stored["files"]["readme"].endswith("README.md")
    with (output / "processed" / "metrics.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        metric_columns = tuple(csv.DictReader(handle).fieldnames or ())
    assert "mean_error_db" in metric_columns
    assert "mae_ci95_low_db" in metric_columns
    assert "small_sample_warning" in metric_columns


def test_analysis_propagates_adjacent_synthetic_provenance(tmp_path):
    summary_path, points_path, grid_path = _synthetic_inputs(tmp_path)
    summary_path.with_suffix(".synthetic_report.json").write_text(
        json.dumps(
            {
                "synthetic": True,
                "paper_evidence_eligible": False,
                "warning": "SYNTHETIC DRY RUN ONLY",
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "synthetic_analysis"

    report = run_analysis(
        summary_path,
        points_path,
        grid_path,
        METHOD_CONFIG,
        output,
    )

    assert report["paper_evidence_eligible"] is False
    assert report["input_provenance"]["synthetic"] is True
    assert "SYNTHETIC DRY RUN ONLY" in (output / "README.md").read_text(
        encoding="utf-8"
    )


def test_analysis_propagates_draft_sionna_provenance(tmp_path):
    input_directory = tmp_path / "sionna" / "processed"
    summary_path, points_path, grid_path = _synthetic_inputs(input_directory)
    (input_directory.parent / "sionna_rssi_report.json").write_text(
        json.dumps(
            {
                "success": True,
                "ready_input": False,
                "paper_evidence_eligible": False,
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "draft_sionna_analysis"

    report = run_analysis(
        summary_path,
        points_path,
        grid_path,
        METHOD_CONFIG,
        output,
    )

    assert report["paper_evidence_eligible"] is False
    assert report["input_provenance"]["sionna_ready_input"] is False
    assert "DRAFT SIONNA INPUT" in (output / "README.md").read_text(
        encoding="utf-8"
    )
