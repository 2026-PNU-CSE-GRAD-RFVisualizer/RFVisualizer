import csv
from pathlib import Path

import pytest

from tools.rf_experiment.contracts import (
    ContractError,
    RAW_REQUIRED_COLUMNS,
    SUMMARY_REQUIRED_COLUMNS,
    load_json,
    validate_contract_bundle,
    validate_csv_contract,
    validate_marker_document,
    validate_scene_document,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIRECTORY = (
    PROJECT_ROOT / "tools" / "rf_experiment" / "tests" / "fixtures" / "configs"
)


def _scene_report():
    return validate_scene_document(load_json(CONFIG_DIRECTORY / "scene.json"))


def _ready_markers():
    receivers = []
    for index in range(3):
        point_id = "cal-{:02d}".format(index + 1)
        receivers.append(
            {
                "id": "rx-{}".format(point_id),
                "point_id": point_id,
                "name": "보정 위치 {}".format(index + 1),
                "role": "calibration",
                "position_m": [1.0 + index * 2.0, 1.0 + index, 0.8 + index * 0.1],
            }
        )
    for index in range(15):
        point_id = "test-{:02d}".format(index + 1)
        receivers.append(
            {
                "id": "rx-{}".format(point_id),
                "point_id": point_id,
                "name": "시험 위치 {}".format(index + 1),
                "role": "test",
                "position_m": [0.5 + index % 5 * 2.5, 1.0 + index // 5 * 3.0, 1.2],
            }
        )
    return {
        "schema_version": "1.0",
        "scene_id": "classroom_20260723",
        "coordinate_system_id": "pnu_classroom_field_v1",
        "status": "ready",
        "requirements": {
            "transmitter_count": 1,
            "calibration_receiver_count": 3,
            "test_receiver_count": 15,
        },
        "tx": [
            {
                "id": "tx-01",
                "name": "실험 전용 AP",
                "position_m": [2.1, 1.8, 0.82],
                "frequency_hz": 2.4e9,
                "power_dbm": 20.0,
            }
        ],
        "rx": receivers,
    }


def test_checked_in_contracts_are_structurally_valid_but_not_ready():
    report = validate_contract_bundle(
        CONFIG_DIRECTORY / "scene.json",
        CONFIG_DIRECTORY / "tx_rx.json",
        CONFIG_DIRECTORY / "method_config.json",
    )

    assert report["success"] is True
    assert report["ready"] is False
    assert report["scene"]["dimensions_m"]["width_x"] == pytest.approx(15.4)
    assert report["scene"]["dimensions_m"]["depth_y"] == pytest.approx(10.8)
    assert report["markers"]["expected_counts"] == {
        "transmitter_count": 1,
        "calibration_receiver_count": 3,
        "test_receiver_count": 15,
    }
    assert report["warnings"]


def test_require_ready_rejects_unbuilt_scene_and_empty_markers():
    with pytest.raises(ContractError, match="ready 상태가 아닌"):
        validate_contract_bundle(
            CONFIG_DIRECTORY / "scene.json",
            CONFIG_DIRECTORY / "tx_rx.json",
            CONFIG_DIRECTORY / "method_config.json",
            require_ready=True,
        )


def test_ready_marker_counts_and_positions_pass():
    report = validate_marker_document(_ready_markers(), _scene_report())

    assert report["status"] == "ready"
    assert report["actual_counts"] == report["expected_counts"]
    assert report["warnings"] == []


def test_marker_coordinate_id_mismatch_is_rejected():
    markers = _ready_markers()
    markers["coordinate_system_id"] = "legacy_negative_xy"

    with pytest.raises(ContractError, match="coordinate_system_id"):
        validate_marker_document(markers, _scene_report())


def test_marker_outside_measured_room_is_rejected():
    markers = _ready_markers()
    markers["tx"][0]["position_m"][0] = 15.41

    with pytest.raises(ContractError, match="X 좌표"):
        validate_marker_document(markers, _scene_report())


def _write_csv(path, fieldnames, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_summary_csv_contract_accepts_finite_analysis_row(tmp_path):
    path = tmp_path / "measurements_summary.csv"
    row = {
        "point_id": "test-01",
        "point_role": "test",
        "node_id": "node-04",
        "x": "2.0",
        "y": "3.0",
        "z": "1.2",
        "sample_count": "30",
        "median_raw": "-60.0",
        "median_filtered": "-59.5",
        "mean_filtered": "-59.7",
        "std_filtered": "1.2",
        "device_offset_db": "0.5",
        "corrected_rssi": "-59.0",
    }
    _write_csv(path, SUMMARY_REQUIRED_COLUMNS, [row])

    report = validate_csv_contract(path, "summary", require_rows=True)

    assert report["row_count"] == 1
    assert report["point_count"] == 1


def test_raw_csv_header_only_is_valid_draft_with_warning(tmp_path):
    path = tmp_path / "measurements_raw.csv"
    _write_csv(path, RAW_REQUIRED_COLUMNS, [])

    report = validate_csv_contract(path, "raw")

    assert report["row_count"] == 0
    assert report["warnings"]


def test_csv_missing_required_column_is_rejected(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("point_id,point_role\ntest-01,test\n", encoding="utf-8")

    with pytest.raises(ContractError, match="필수 열"):
        validate_csv_contract(path, "summary")
