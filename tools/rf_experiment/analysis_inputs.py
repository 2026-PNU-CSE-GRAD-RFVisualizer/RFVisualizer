"""CSV 입력과 분석 설정 검증."""

from __future__ import annotations

import csv
import math
from typing import Any, Dict, List, Mapping, Sequence

import numpy as np

from .contracts import resolve_path, validate_csv_contract, validate_method_document


class AnalysisError(ValueError):
    """실험 데이터가 비교 분석 조건을 만족하지 않을 때 발생한다."""


SIONNA_POINT_COLUMNS = ("point_id", "x", "y", "z", "sionna_rssi_dbm")
SIONNA_GRID_COLUMNS = ("grid_id", "row", "column", "x", "y", "z", "sionna_rssi_dbm")


def _read_rows(path: Any, required: Sequence[str], label: str) -> List[Dict[str, str]]:
    source = resolve_path(path)
    if not source.is_file():
        raise AnalysisError("{} 파일을 찾을 수 없습니다: {}".format(label, source))
    try:
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = tuple(reader.fieldnames or ())
            missing = [field for field in required if field not in columns]
            if missing:
                raise AnalysisError("{} 필수 열이 없습니다: {}".format(label, missing))
            rows = list(reader)
    except OSError as exc:
        raise AnalysisError("{} 파일을 읽을 수 없습니다: {}".format(label, exc)) from exc
    if not rows:
        raise AnalysisError("{}에 데이터 행이 없습니다.".format(label))
    return rows


def _number(row: Mapping[str, str], field: str, label: str) -> float:
    try:
        value = float(row.get(field, ""))
    except (TypeError, ValueError, OverflowError) as exc:
        raise AnalysisError("{} {}가 숫자가 아닙니다.".format(label, field)) from exc
    if not math.isfinite(value):
        raise AnalysisError("{} {}가 유한한 숫자가 아닙니다.".format(label, field))
    return value


def load_summary(path: Any) -> List[Dict[str, Any]]:
    validate_csv_contract(path, "summary", require_rows=True)
    rows = _read_rows(
        path,
        ("point_id", "point_role", "node_id", "x", "y", "z", "corrected_rssi"),
        "Summary CSV",
    )
    result = []
    seen = set()
    for index, row in enumerate(rows, start=2):
        point_id = str(row["point_id"]).strip()
        if point_id in seen:
            raise AnalysisError("Summary CSV point_id가 중복됩니다: {}".format(point_id))
        seen.add(point_id)
        role = str(row["point_role"]).strip()
        if role not in {"calibration", "test"}:
            continue
        result.append(
            {
                "point_id": point_id,
                "role": role,
                "node_id": str(row["node_id"]).strip(),
                "position": np.asarray(
                    [
                        _number(row, "x", "Summary {}행".format(index)),
                        _number(row, "y", "Summary {}행".format(index)),
                        _number(row, "z", "Summary {}행".format(index)),
                    ],
                    dtype=float,
                ),
                "actual_rssi_dbm": _number(
                    row, "corrected_rssi", "Summary {}행".format(index)
                ),
            }
        )
    if not any(row["role"] == "calibration" for row in result):
        raise AnalysisError("Summary CSV에 calibration 위치가 없습니다.")
    if not any(row["role"] == "test" for row in result):
        raise AnalysisError("Summary CSV에 test 위치가 없습니다.")
    return result


def load_sionna_points(path: Any) -> Dict[str, Dict[str, Any]]:
    rows = _read_rows(path, SIONNA_POINT_COLUMNS, "Sionna point CSV")
    result = {}
    for index, row in enumerate(rows, start=2):
        point_id = str(row["point_id"]).strip()
        if not point_id or point_id in result:
            raise AnalysisError("Sionna point_id가 비었거나 중복됩니다: {}".format(point_id))
        result[point_id] = {
            "position": np.asarray(
                [
                    _number(row, "x", "Sionna point {}행".format(index)),
                    _number(row, "y", "Sionna point {}행".format(index)),
                    _number(row, "z", "Sionna point {}행".format(index)),
                ],
                dtype=float,
            ),
            "sionna_rssi_dbm": _number(
                row, "sionna_rssi_dbm", "Sionna point {}행".format(index)
            ),
        }
    return result


def load_sionna_grid(path: Any) -> List[Dict[str, Any]]:
    rows = _read_rows(path, SIONNA_GRID_COLUMNS, "Sionna grid CSV")
    result = []
    ids = set()
    for index, row in enumerate(rows, start=2):
        grid_id = str(row["grid_id"]).strip()
        if not grid_id or grid_id in ids:
            raise AnalysisError("Sionna grid_id가 비었거나 중복됩니다: {}".format(grid_id))
        ids.add(grid_id)
        result.append(
            {
                "grid_id": grid_id,
                "row": int(_number(row, "row", "Sionna grid {}행".format(index))),
                "column": int(
                    _number(row, "column", "Sionna grid {}행".format(index))
                ),
                "position": np.asarray(
                    [
                        _number(row, "x", "Sionna grid {}행".format(index)),
                        _number(row, "y", "Sionna grid {}행".format(index)),
                        _number(row, "z", "Sionna grid {}행".format(index)),
                    ],
                    dtype=float,
                ),
                "sionna_rssi_dbm": _number(
                    row, "sionna_rssi_dbm", "Sionna grid {}행".format(index)
                ),
            }
        )
    return result


def _method_settings(method_document: Mapping[str, Any]) -> Dict[str, float]:
    validate_method_document(method_document)
    idw = method_document["method_config"]["idw"]
    return {
        "power": float(idw["power"]),
        "epsilon_distance_power": float(idw["epsilon_distance_power"]),
        "exact_match_tolerance_m": float(idw["exact_match_tolerance_m"]),
    }


TEST_POINT_COLUMNS = (
    "run_id",
    "direction",
    "segment_id",
    "point_id",
    "attempt_index",
    "node_id",
    "x",
    "y",
    "z",
    "corrected_rssi",
)
CALIBRATION_WINDOW_COLUMNS = (
    "run_id",
    "direction",
    "segment_id",
    "test_point_id",
    "calibration_point_id",
    "node_id",
    "x",
    "y",
    "z",
    "corrected_rssi",
)


def _row_position(row: Mapping[str, str], label: str) -> np.ndarray:
    return np.asarray(
        [
            _number(row, "x", label),
            _number(row, "y", label),
            _number(row, "z", label),
        ],
        dtype=float,
    )


def load_segments(
    test_points_path: Any, calibration_window_path: Any
) -> tuple[List[Dict[str, Any]], List[str]]:
    """TestSegment 단위 평가 입력.

    각 Test 를 **같은 `segment_id`(= 같은 기록 시간창)** 의 Calibration 과 짝짓는다.
    Run 전체 평균을 모든 Test 에 공통 적용하지 않기 위한 입력이며,
    정방향·역방향은 `run_id`/`direction` 으로 분리된 채 유지된다.

    반환값은 (Segment 목록, Test 대표값이 없는 Segment id 목록)이다.
    두 번째 값은 실패가 아니라 **Test 미수신 기록**이다. 해당 위치에서 유효 표본이
    하나도 없으면 Backend Export 가 test_points 행을 만들지 않기 때문이다.
    """

    test_rows = _read_rows(test_points_path, TEST_POINT_COLUMNS, "Test point CSV")
    window_rows = _read_rows(
        calibration_window_path, CALIBRATION_WINDOW_COLUMNS, "Calibration window CSV"
    )

    windows: Dict[str, List[Dict[str, Any]]] = {}
    for index, row in enumerate(window_rows, start=2):
        label = "Calibration window {}행".format(index)
        segment_id = str(row["segment_id"]).strip()
        if not segment_id:
            raise AnalysisError("{} segment_id가 비어 있습니다.".format(label))
        point_id = str(row["calibration_point_id"]).strip()
        if not point_id:
            raise AnalysisError("{} calibration_point_id가 비어 있습니다.".format(label))
        bucket = windows.setdefault(segment_id, [])
        if any(entry["point_id"] == point_id for entry in bucket):
            raise AnalysisError(
                "Segment {}에 calibration {}가 중복됩니다.".format(segment_id, point_id)
            )
        bucket.append(
            {
                "point_id": point_id,
                "node_id": str(row["node_id"]).strip(),
                "position": _row_position(row, label),
                "actual_rssi_dbm": _number(row, "corrected_rssi", label),
            }
        )

    segments: List[Dict[str, Any]] = []
    seen: set = set()
    for index, row in enumerate(test_rows, start=2):
        label = "Test point {}행".format(index)
        segment_id = str(row["segment_id"]).strip()
        if not segment_id:
            raise AnalysisError("{} segment_id가 비어 있습니다.".format(label))
        if segment_id in seen:
            raise AnalysisError("Test point CSV segment_id가 중복됩니다: {}".format(segment_id))
        seen.add(segment_id)
        calibration = windows.get(segment_id)
        if not calibration:
            raise AnalysisError(
                "Segment {}에 같은 시간창의 calibration 행이 없습니다. "
                "Backend Export 의 calibration_by_test_window.csv 를 확인하십시오.".format(segment_id)
            )
        point_id = str(row["point_id"]).strip()
        if not point_id:
            raise AnalysisError("{} point_id가 비어 있습니다.".format(label))
        segments.append(
            {
                "segment_id": segment_id,
                "run_id": str(row["run_id"]).strip(),
                "direction": str(row["direction"]).strip() or "unknown",
                "attempt_index": int(_number(row, "attempt_index", label)),
                "point_id": point_id,
                "node_id": str(row["node_id"]).strip(),
                "position": _row_position(row, label),
                "actual_rssi_dbm": _number(row, "corrected_rssi", label),
                "calibration": calibration,
            }
        )

    # Test 대표값이 없는 Segment = 그 위치에서 유효 표본 0건(미수신). 결과로 보고한다.
    unmatched = sorted(set(windows) - seen)
    return segments, unmatched


SUPPORTED_MISSING_MEASUREMENT_RULES = ("exclude_and_report",)


def _evaluation_policy(method_document: Mapping[str, Any]) -> Dict[str, Any]:
    """평가 규칙(미수신 처리 포함)을 읽고 구현된 규칙인지 확인한다.

    미수신 지점을 임의 값으로 대입(imputation)하면 그 값이 MAE 를 좌우하므로
    구현하지 않는다. 설정이 대입을 요구하면 조용히 무시하지 않고 실패시킨다.
    """

    evaluation = dict(method_document["method_config"]["evaluation"])
    policy = dict(evaluation.get("missing_measurement_policy") or {})
    rule = str(policy.get("rule", "exclude_and_report"))
    if rule not in SUPPORTED_MISSING_MEASUREMENT_RULES:
        raise AnalysisError(
            "구현되지 않은 미수신 처리 규칙입니다: {} (지원: {})".format(
                rule, ", ".join(SUPPORTED_MISSING_MEASUREMENT_RULES)
            )
        )
    imputation = str(policy.get("imputation", "none"))
    if imputation != "none":
        raise AnalysisError(
            "미수신 지점의 값 대입(imputation={})은 구현하지 않았습니다. "
            "대입값이 MAE 를 좌우하므로 제외 후 보고만 지원합니다.".format(imputation)
        )
    return {
        "target_column": evaluation.get("target_column"),
        "metrics": evaluation.get("metrics"),
        "missing_measurement_rule": rule,
        "imputation": imputation,
        "receiver_sensitivity_floor_dbm": policy.get("receiver_sensitivity_floor_dbm"),
        "note_ko": policy.get("note_ko"),
    }
