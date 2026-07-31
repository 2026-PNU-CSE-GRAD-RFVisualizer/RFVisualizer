import csv
from pathlib import Path

import pytest

from tools.rf_experiment.contracts import SUMMARY_REQUIRED_COLUMNS
from tools.rf_experiment.dry_run import DryRunError, generate_synthetic_summary


POINT_FIELDS = (
    "point_id",
    "x",
    "y",
    "z",
    "sionna_rssi_dbm",
    "point_role",
)


def _write_points(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=POINT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_synthetic_summary_preserves_ids_coordinates_and_adds_fixed_bias(tmp_path):
    source = tmp_path / "sionna_points.csv"
    _write_points(
        source,
        [
            {
                "point_id": "cal-01",
                "point_role": "calibration",
                "x": 1.0,
                "y": 2.0,
                "z": 1.2,
                "sionna_rssi_dbm": -50.0,
            },
            {
                "point_id": "test-01",
                "point_role": "test",
                "x": 3.0,
                "y": 4.0,
                "z": 1.2,
                "sionna_rssi_dbm": -60.0,
            },
        ],
    )
    output = tmp_path / "summary.csv"

    report = generate_synthetic_summary(source, output, residual_bias_db=4.0)

    with output.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert tuple(rows[0].keys()) == SUMMARY_REQUIRED_COLUMNS
    assert rows[0]["point_id"] == "cal-01"
    assert float(rows[0]["corrected_rssi"]) == pytest.approx(-46.0)
    assert float(rows[1]["corrected_rssi"]) == pytest.approx(-56.0)
    assert report["paper_evidence_eligible"] is False
    assert Path(report["files"]["report_json"]).is_file()


def test_synthetic_summary_rejects_non_experiment_role(tmp_path):
    source = tmp_path / "sionna_points.csv"
    _write_points(
        source,
        [
            {
                "point_id": "dry-01",
                "point_role": "dry_run",
                "x": 1.0,
                "y": 2.0,
                "z": 1.2,
                "sionna_rssi_dbm": -50.0,
            }
        ],
    )

    with pytest.raises(DryRunError, match="calibration 또는 test"):
        generate_synthetic_summary(source, tmp_path / "summary.csv")
