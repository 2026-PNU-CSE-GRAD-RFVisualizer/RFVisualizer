"""실제 Sionna 출력으로 분석 연결만 검증하는 합성 Summary 생성기."""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any, Dict, List

from tools.sionna_smoke_test.io_utils import SmokeTestIOError, write_csv, write_json

from .analysis import SIONNA_POINT_COLUMNS
from .contracts import SUMMARY_REQUIRED_COLUMNS, resolve_path, validate_csv_contract


class DryRunError(ValueError):
    """합성 Dry Run 입력이나 출력이 유효하지 않을 때 발생한다."""


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    try:
        write_csv(path, SUMMARY_REQUIRED_COLUMNS, rows)
    except SmokeTestIOError as exc:
        raise DryRunError("합성 Summary CSV를 저장할 수 없습니다: {}".format(exc)) from exc


def generate_synthetic_summary(
    sionna_points_path: Any,
    output_path: Any,
    residual_bias_db: float = 4.0,
) -> Dict[str, Any]:
    """Sionna 값에 고정 잔차를 더해 데이터 연결만 검증한다."""

    source = resolve_path(sionna_points_path)
    output = resolve_path(output_path)
    try:
        bias = float(residual_bias_db)
    except (TypeError, ValueError, OverflowError) as exc:
        raise DryRunError("합성 residual bias는 숫자여야 합니다.") from exc
    if not math.isfinite(bias):
        raise DryRunError("합성 residual bias는 유한한 숫자여야 합니다.")
    if not source.is_file():
        raise DryRunError("Sionna point CSV를 찾을 수 없습니다: {}".format(source))
    try:
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = tuple(reader.fieldnames or ())
            required = SIONNA_POINT_COLUMNS + ("point_role",)
            missing = [field for field in required if field not in fields]
            if missing:
                raise DryRunError("Sionna point CSV 필수 열이 없습니다: {}".format(missing))
            source_rows = list(reader)
    except OSError as exc:
        raise DryRunError("Sionna point CSV를 읽을 수 없습니다: {}".format(exc)) from exc
    if not source_rows:
        raise DryRunError("Sionna point CSV에 데이터 행이 없습니다.")
    rows = []
    for index, row in enumerate(source_rows, start=1):
        role = str(row["point_role"]).strip()
        if role not in {"calibration", "test"}:
            raise DryRunError("합성 Summary의 역할은 calibration 또는 test여야 합니다.")
        try:
            x, y, z = (float(row[field]) for field in ("x", "y", "z"))
            sionna = float(row["sionna_rssi_dbm"])
        except (TypeError, ValueError, OverflowError) as exc:
            raise DryRunError("Sionna point CSV에 숫자가 아닌 값이 있습니다.") from exc
        if not all(math.isfinite(value) for value in (x, y, z, sionna)):
            raise DryRunError("Sionna point CSV 숫자에 NaN 또는 Inf가 있습니다.")
        corrected = sionna + bias
        rows.append(
            {
                "point_id": row["point_id"],
                "point_role": role,
                "node_id": "synthetic-node-{:02d}".format(index),
                "x": x,
                "y": y,
                "z": z,
                "sample_count": 30,
                "median_raw": corrected - 0.2,
                "median_filtered": corrected,
                "mean_filtered": corrected,
                "std_filtered": 0.8,
                "device_offset_db": 0.0,
                "corrected_rssi": corrected,
            }
        )
    _write_csv(output, rows)
    contract = validate_csv_contract(output, "summary", require_rows=True)
    calibration_count = sum(row["point_role"] == "calibration" for row in rows)
    test_count = sum(row["point_role"] == "test" for row in rows)
    report_path = output.with_suffix(".synthetic_report.json")
    report = {
        "schema_version": "1.0",
        "success": True,
        "synthetic": True,
        "paper_evidence_eligible": False,
        "warning": "SYNTHETIC DRY RUN ONLY — 실제 측정 결과가 아닙니다.",
        "construction": "corrected_rssi = sionna_rssi_dbm + fixed_residual_bias_db",
        "fixed_residual_bias_db": bias,
        "calibration_count": calibration_count,
        "test_count": test_count,
        "csv_contract": contract,
        "files": {
            "source_sionna_points_csv": str(source),
            "synthetic_summary_csv": str(output),
            "report_json": str(report_path),
        },
    }
    write_json(report_path, report)
    return report
