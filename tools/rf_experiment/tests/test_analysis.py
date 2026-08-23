import csv
import json
import math
from pathlib import Path

import numpy as np
import pytest

from tools.rf_experiment.analysis import (
    AnalysisError,
    compare_methods,
    compare_methods_by_segment,
    idw_predict,
    load_segments,
    load_sionna_grid,
    load_sionna_points,
    load_summary,
    regression_metrics,
    run_analysis,
    run_segment_analysis,
)
from tools.rf_experiment.contracts import SUMMARY_REQUIRED_COLUMNS


PROJECT_ROOT = Path(__file__).resolve().parents[3]
METHOD_CONFIG = (
    PROJECT_ROOT
    / "tools"
    / "rf_experiment"
    / "tests"
    / "fixtures"
    / "configs"
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


TEST_POINT_FIELDS = (
    "run_id", "direction", "pass_index", "segment_id", "point_id", "attempt_index",
    "recording_started_at_ms", "recording_ended_at_ms",
    "node_id", "sample_count", "median_filtered", "device_offset_db", "corrected_rssi",
    "x", "y", "z",
)
CALIBRATION_WINDOW_FIELDS = (
    "run_id", "direction", "pass_index", "segment_id", "test_point_id",
    "calibration_point_id", "node_id", "window_started_at_ms", "window_ended_at_ms",
    "sample_count", "median_filtered", "device_offset_db", "corrected_rssi", "x", "y", "z",
)
CALIBRATION_XY = ((1.0, 1.0), (13.0, 1.0), (1.0, 9.0), (13.0, 9.0))
TEST_XY = ((2.0, 2.0), (4.5, 5.0), (7.0, 8.0), (9.5, 5.0), (12.0, 2.0))


def _segment_inputs(tmp_path, orphan_segment=False):
    """정·역방향 Run 2개의 Segment 단위 Backend Export 를 흉내낸다.

    Segment 마다 서로 다른 bias 를 주므로, 같은 시간창의 calibration 을 써야만
    Residual IDW 가 오차 0으로 복원된다. Run 전체 평균을 쓰면 복원되지 않는다.
    """

    tmp_path.mkdir(parents=True, exist_ok=True)
    calibration = [
        ("cal-{:02d}".format(index), x, y)
        for index, (x, y) in enumerate(CALIBRATION_XY, start=1)
    ]
    test = [
        ("test-{:02d}".format(index), x, y)
        for index, (x, y) in enumerate(TEST_XY, start=1)
    ]

    sionna_point_rows = [
        {"point_id": pid, "x": x, "y": y, "z": 1.2, "sionna_rssi_dbm": _sionna_rssi(x, y)}
        for pid, x, y in calibration + test
    ]
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

    test_rows = []
    window_rows = []
    counter = 0
    for direction in ("forward", "reverse"):
        ordered = test if direction == "forward" else list(reversed(test))
        run_id = "run-{}".format(direction)
        for order_index, (point_id, x, y) in enumerate(ordered, start=1):
            counter += 1
            bias = 4.0 + 0.5 * counter  # 시간에 따라 변하는 편차
            segment_id = "{}__{}__a1".format(run_id, point_id)
            started = 1_000_000 + counter * 200_000
            test_rows.append(
                {
                    "run_id": run_id,
                    "direction": direction,
                    "pass_index": 1,
                    "segment_id": segment_id,
                    "point_id": point_id,
                    "attempt_index": 1,
                    "recording_started_at_ms": started,
                    "recording_ended_at_ms": started + 120_000,
                    "node_id": "node-02",
                    "sample_count": 120,
                    "median_filtered": _sionna_rssi(x, y) + bias,
                    "device_offset_db": 0.0,
                    "corrected_rssi": _sionna_rssi(x, y) + bias,
                    "x": x,
                    "y": y,
                    "z": 1.2,
                }
            )
            for node_index, (cal_id, cal_x, cal_y) in enumerate(calibration, start=1):
                window_rows.append(
                    {
                        "run_id": run_id,
                        "direction": direction,
                        "pass_index": 1,
                        "segment_id": segment_id,
                        "test_point_id": point_id,
                        "calibration_point_id": cal_id,
                        "node_id": "node-{:02d}".format(node_index),
                        "window_started_at_ms": started,
                        "window_ended_at_ms": started + 120_000,
                        "sample_count": 120,
                        "median_filtered": _sionna_rssi(cal_x, cal_y) + bias,
                        "device_offset_db": 0.0,
                        "corrected_rssi": _sionna_rssi(cal_x, cal_y) + bias,
                        "x": cal_x,
                        "y": cal_y,
                        "z": 1.2,
                    }
                )
    if orphan_segment:
        # Test 미수신: calibration 행만 있고 test_points 행이 없는 Segment
        for node_index, (cal_id, cal_x, cal_y) in enumerate(calibration, start=1):
            window_rows.append(
                {
                    "run_id": "run-forward",
                    "direction": "forward",
                    "pass_index": 1,
                    "segment_id": "run-forward__test-99__a1",
                    "test_point_id": "test-99",
                    "calibration_point_id": cal_id,
                    "node_id": "node-{:02d}".format(node_index),
                    "window_started_at_ms": 9_000_000,
                    "window_ended_at_ms": 9_120_000,
                    "sample_count": 120,
                    "median_filtered": _sionna_rssi(cal_x, cal_y),
                    "device_offset_db": 0.0,
                    "corrected_rssi": _sionna_rssi(cal_x, cal_y),
                    "x": cal_x,
                    "y": cal_y,
                    "z": 1.2,
                }
            )

    test_points_path = tmp_path / "test_points.csv"
    window_path = tmp_path / "calibration_by_test_window.csv"
    points_path = tmp_path / "sionna_points.csv"
    grid_path = tmp_path / "sionna_grid.csv"
    _write_csv(test_points_path, TEST_POINT_FIELDS, test_rows)
    _write_csv(window_path, CALIBRATION_WINDOW_FIELDS, window_rows)
    _write_csv(points_path, ("point_id", "x", "y", "z", "sionna_rssi_dbm"), sionna_point_rows)
    _write_csv(
        grid_path,
        ("grid_id", "row", "column", "x", "y", "z", "sionna_rssi_dbm"),
        grid_rows,
    )
    return test_points_path, window_path, points_path, grid_path


def test_each_test_point_is_compared_with_its_own_time_window(tmp_path):
    # Given: Segment 마다 편차가 다른 정·역방향 측정.
    test_points_path, window_path, points_path, grid_path = _segment_inputs(tmp_path)
    segments, unmatched = load_segments(test_points_path, window_path)
    points = load_sionna_points(points_path)
    grid = load_sionna_grid(grid_path)

    # When: Segment 단위로 비교한다.
    comparison = compare_methods_by_segment(segments, points, grid, IDW_SETTINGS)

    # Then: 같은 시간창의 calibration 으로 보정했으므로 잔차가 정확히 상쇄된다.
    # (Run 전체 평균을 썼다면 Segment 별 편차 차이만큼 오차가 남는다.)
    assert unmatched == []
    assert comparison["metrics"]["residual_idw"]["mae"] < 1.0e-10
    assert comparison["metrics"]["residual_idw"]["mae"] < comparison["metrics"]["plain_idw"]["mae"]
    assert comparison["data_split_validation"]["evaluation_mode"] == "per_test_segment_window"
    assert comparison["data_split_validation"]["segment_count"] == 10
    assert comparison["data_split_validation"]["segments_by_direction"] == {
        "forward": 5,
        "reverse": 5,
    }
    assert set(comparison["metrics_by_direction"]) == {"forward", "reverse"}


def test_one_window_change_does_not_move_other_segments(tmp_path):
    test_points_path, window_path, points_path, grid_path = _segment_inputs(tmp_path)
    segments, _ = load_segments(test_points_path, window_path)
    points = load_sionna_points(points_path)
    grid = load_sionna_grid(grid_path)
    original = compare_methods_by_segment(segments, points, grid, IDW_SETTINGS)

    changed_segments = [dict(segment) for segment in segments]
    changed_segments[0]["calibration"] = [
        {**entry, "actual_rssi_dbm": entry["actual_rssi_dbm"] + 10.0}
        for entry in changed_segments[0]["calibration"]
    ]
    changed = compare_methods_by_segment(changed_segments, points, grid, IDW_SETTINGS)

    for method in ("plain_idw", "residual_idw"):
        assert changed["test_predictions"][method][0] != pytest.approx(
            original["test_predictions"][method][0]
        )
        assert changed["test_predictions"][method][1:] == pytest.approx(
            original["test_predictions"][method][1:]
        )


def test_segment_test_measurements_are_not_used_to_fit_predictions(tmp_path):
    test_points_path, window_path, points_path, grid_path = _segment_inputs(tmp_path)
    segments, _ = load_segments(test_points_path, window_path)
    points = load_sionna_points(points_path)
    grid = load_sionna_grid(grid_path)
    original = compare_methods_by_segment(segments, points, grid, IDW_SETTINGS)

    changed_segments = [
        {**segment, "actual_rssi_dbm": segment["actual_rssi_dbm"] + 100.0}
        for segment in segments
    ]
    changed = compare_methods_by_segment(changed_segments, points, grid, IDW_SETTINGS)

    for method in ("raw_sionna", "plain_idw", "residual_idw"):
        assert changed["test_predictions"][method] == pytest.approx(
            original["test_predictions"][method]
        )
    assert original["data_split_validation"]["test_values_used_in_fitting"] is False


def test_segment_analysis_reports_direction_metrics_and_missing_measurements(tmp_path):
    test_points_path, window_path, points_path, grid_path = _segment_inputs(
        tmp_path, orphan_segment=True
    )
    output = tmp_path / "segment_analysis"

    report = run_segment_analysis(
        test_points_path,
        window_path,
        points_path,
        grid_path,
        METHOD_CONFIG,
        output,
    )

    assert report["success"] is True
    assert report["evaluation_mode"] == "per_test_segment_window"
    assert set(report["metrics_by_direction"]) == {"forward", "reverse"}
    # 미수신 Segment 는 실패가 아니라 기록으로 남는다.
    assert report["input_provenance"]["segments_without_test_measurement"] == [
        "run-forward__test-99__a1"
    ]
    assert (output / "processed" / "metrics_by_direction.csv").is_file()
    with (output / "processed" / "comparison_results.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 10
    assert {row["direction"] for row in rows} == {"forward", "reverse"}
    assert rows[0]["segment_id"]
    readme = (output / "README.md").read_text(encoding="utf-8")
    assert "방향별 지표" in readme
    assert "per_test_segment_window" in readme


def test_segment_loader_rejects_test_without_matching_window(tmp_path):
    test_points_path, window_path, _, _ = _segment_inputs(tmp_path)
    rows = list(csv.DictReader(window_path.open(encoding="utf-8", newline="")))
    kept = [row for row in rows if "test-01" not in row["segment_id"]]
    _write_csv(window_path, CALIBRATION_WINDOW_FIELDS, kept)

    with pytest.raises(AnalysisError, match="같은 시간창"):
        load_segments(test_points_path, window_path)


def test_analysis_records_missing_measurement_policy(tmp_path):
    test_points_path, window_path, points_path, grid_path = _segment_inputs(
        tmp_path, orphan_segment=True
    )
    output = tmp_path / "policy_analysis"

    report = run_segment_analysis(
        test_points_path,
        window_path,
        points_path,
        grid_path,
        METHOD_CONFIG,
        output,
    )

    assert report["evaluation_policy"]["missing_measurement_rule"] == "exclude_and_report"
    assert report["evaluation_policy"]["imputation"] == "none"


def test_unimplemented_missing_measurement_rule_fails_loudly(tmp_path):
    test_points_path, window_path, points_path, grid_path = _segment_inputs(tmp_path)
    method_document = json.loads(METHOD_CONFIG.read_text(encoding="utf-8"))
    method_document["method_config"]["evaluation"]["missing_measurement_policy"] = {
        "rule": "impute_sensitivity_floor",
        "imputation": "receiver_sensitivity_floor_dbm",
    }
    method_path = tmp_path / "method_config.json"
    method_path.write_text(json.dumps(method_document), encoding="utf-8")

    with pytest.raises(AnalysisError, match="미수신 처리 규칙"):
        run_segment_analysis(
            test_points_path,
            window_path,
            points_path,
            grid_path,
            method_path,
            tmp_path / "rejected",
        )
