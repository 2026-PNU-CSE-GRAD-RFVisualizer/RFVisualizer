import csv
from pathlib import Path

import numpy as np

from tools.sionna_scenario.exporter import write_coverage_delta_csv


def test_delta_csv_common_mask_requires_inside_valid_and_finite(tmp_path: Path):
    centers = np.asarray([[[0, 0, 1.5], [1, 0, 1.5], [2, 0, 1.5]]], dtype=float)
    baseline = np.asarray([[-10.0, -20.0, -30.0]])
    variant = np.asarray([[-11.0, np.nan, -33.0]])
    inside = np.asarray([[True, True, False]])
    valid = np.asarray([[True, True, True]])
    path = tmp_path / "delta.csv"
    write_coverage_delta_csv(
        path,
        centers,
        baseline,
        variant,
        inside,
        valid,
        valid,
        variant_inside=np.asarray([[True, True, True]]),
    )
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["is_common_valid"] for row in rows] == ["True", "False", "False"]
    assert rows[0]["delta_db"] == "-1.0"
    assert rows[1]["delta_db"] == ""
    assert rows[2]["delta_db"] == ""
