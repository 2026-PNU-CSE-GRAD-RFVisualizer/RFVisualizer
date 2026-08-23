"""Raw Sionna, Plain IDW, Residual IDW의 재현 가능한 정량 비교."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import numpy as np

from .analysis_compute import (
    compare_methods as compare_methods,
    compare_methods_by_segment as compare_methods_by_segment,
    idw_predict as idw_predict,
    regression_metrics as regression_metrics,
)
from .analysis_export import export_analysis as export_analysis
from .analysis_inputs import (
    AnalysisError as AnalysisError,
    CALIBRATION_WINDOW_COLUMNS as CALIBRATION_WINDOW_COLUMNS,
    SIONNA_GRID_COLUMNS as SIONNA_GRID_COLUMNS,
    SIONNA_POINT_COLUMNS as SIONNA_POINT_COLUMNS,
    TEST_POINT_COLUMNS as TEST_POINT_COLUMNS,
    _evaluation_policy,
    _method_settings,
    load_segments as load_segments,
    load_sionna_grid as load_sionna_grid,
    load_sionna_points as load_sionna_points,
    load_summary as load_summary,
)
from .contracts import load_json, resolve_path
from .reliability import (
    PredictionMetrics as PredictionMetrics,
    metrics_csv_rows as metrics_csv_rows,
    prediction_metrics as prediction_metrics,
)


def _input_provenance(
    primary_source: Path,
    points_source: Path,
    grid_source: Path,
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """입력 출처와 논문 근거 사용 가능 여부를 기록한다."""

    provenance: Dict[str, Any] = {
        "sionna_points_csv": str(points_source),
        "sionna_grid_csv": str(grid_source),
        "synthetic": False,
    }
    provenance.update(dict(extra or {}))
    report_candidates = (
        points_source.parent / "sionna_rssi_report.json",
        points_source.parent.parent / "sionna_rssi_report.json",
    )
    sionna_report_path = next(
        (path for path in report_candidates if path.is_file()), None
    )
    if sionna_report_path is not None:
        sionna_report = load_json(sionna_report_path)
        provenance.update(
            {
                "sionna_report_json": str(sionna_report_path),
                "sionna_paper_evidence_eligible": bool(
                    sionna_report.get("paper_evidence_eligible", False)
                ),
                "sionna_ready_input": bool(sionna_report.get("ready_input", False)),
            }
        )
    synthetic_report_path = primary_source.with_suffix(".synthetic_report.json")
    if synthetic_report_path.is_file():
        synthetic_report = load_json(synthetic_report_path)
        if synthetic_report.get("synthetic") is True:
            provenance.update(
                {
                    "synthetic": True,
                    "paper_evidence_eligible": False,
                    "synthetic_report_json": str(synthetic_report_path),
                    "warning": synthetic_report.get("warning"),
                }
            )
    return provenance


def run_analysis(
    summary_path: Any,
    sionna_points_path: Any,
    sionna_grid_path: Any,
    method_config_path: Any,
    output_directory: Any,
) -> Dict[str, Any]:
    """실험 전체 집계(measurements_summary.csv) 기준 비교.

    진단·호환용 경로다. 계획서 §7의 "각 Test 를 같은 시간창의 C1~C4 와 비교" 규칙을
    지키려면 `run_segment_analysis` 를 사용한다.
    """

    summary_source = resolve_path(summary_path)
    summary = load_summary(summary_source)
    points_source = resolve_path(sionna_points_path)
    grid_source = resolve_path(sionna_grid_path)
    points = load_sionna_points(points_source)
    grid = load_sionna_grid(grid_source)
    method_document = load_json(method_config_path)
    settings = _method_settings(method_document)
    comparison = compare_methods(summary, points, grid, settings)
    provenance = _input_provenance(
        summary_source,
        points_source,
        grid_source,
        {"summary_csv": str(summary_source)},
    )
    return export_analysis(
        comparison,
        summary,
        output_directory,
        method_config_path,
        input_provenance=provenance,
        evaluation_policy=_evaluation_policy(method_document),
    )


def _measured_points(comparison: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """measured_points.png 용 지점 목록(그림 전용, 지표 계산과 무관)."""

    rows: List[Dict[str, Any]] = [
        {
            "point_id": row["point_id"],
            "position": row["position"],
            "actual_rssi_dbm": row["actual_rssi_dbm"],
        }
        for row in comparison["calibration"]
    ]
    grouped: Dict[str, Dict[str, Any]] = {}
    for index, row in enumerate(comparison["test"]):
        bucket = grouped.setdefault(
            row["point_id"],
            {"point_id": row["point_id"], "position": row["position"], "values": []},
        )
        bucket["values"].append(float(comparison["test_actual"][index]))
    rows.extend(
        {
            "point_id": bucket["point_id"],
            "position": bucket["position"],
            "actual_rssi_dbm": float(np.mean(bucket["values"])),
        }
        for bucket in sorted(grouped.values(), key=lambda item: item["point_id"])
    )
    return rows


def run_segment_analysis(
    test_points_path: Any,
    calibration_window_path: Any,
    sionna_points_path: Any,
    sionna_grid_path: Any,
    method_config_path: Any,
    output_directory: Any,
) -> Dict[str, Any]:
    """TestSegment 단위 비교 (계획서 §7 규칙).

    각 Test 는 같은 `segment_id`(= 같은 기록 시간창)의 C1~C4 로만 예측하고,
    정방향·역방향 지표를 따로 낸다.
    """

    test_source = resolve_path(test_points_path)
    window_source = resolve_path(calibration_window_path)
    segments, unmatched = load_segments(test_source, window_source)
    points_source = resolve_path(sionna_points_path)
    grid_source = resolve_path(sionna_grid_path)
    points = load_sionna_points(points_source)
    grid = load_sionna_grid(grid_source)
    method_document = load_json(method_config_path)
    settings = _method_settings(method_document)
    comparison = compare_methods_by_segment(segments, points, grid, settings)
    provenance = _input_provenance(
        test_source,
        points_source,
        grid_source,
        {
            "test_points_csv": str(test_source),
            "calibration_window_csv": str(window_source),
            # Test 대표값이 없는 Segment = 그 위치 미수신. 평가에서 빠졌음을 남긴다.
            "segments_without_test_measurement": unmatched,
        },
    )
    return export_analysis(
        comparison,
        _measured_points(comparison),
        output_directory,
        method_config_path,
        input_provenance=provenance,
        evaluation_policy=_evaluation_policy(method_document),
    )
