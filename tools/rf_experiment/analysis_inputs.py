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
