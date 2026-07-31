"""Raw Sionna, Plain IDW, Residual IDW의 재현 가능한 정량 비교."""

from __future__ import annotations

from typing import Any, Dict

from .analysis_compute import (
    compare_methods as compare_methods,
    idw_predict as idw_predict,
    regression_metrics as regression_metrics,
)
from .analysis_export import export_analysis as export_analysis
from .analysis_inputs import (
    AnalysisError as AnalysisError,
    SIONNA_GRID_COLUMNS as SIONNA_GRID_COLUMNS,
    SIONNA_POINT_COLUMNS as SIONNA_POINT_COLUMNS,
    _method_settings,
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


def run_analysis(
    summary_path: Any,
    sionna_points_path: Any,
    sionna_grid_path: Any,
    method_config_path: Any,
    output_directory: Any,
) -> Dict[str, Any]:
    summary_source = resolve_path(summary_path)
    summary = load_summary(summary_source)
    points_source = resolve_path(sionna_points_path)
    grid_source = resolve_path(sionna_grid_path)
    points = load_sionna_points(points_source)
    grid = load_sionna_grid(grid_source)
    method_document = load_json(method_config_path)
    settings = _method_settings(method_document)
    comparison = compare_methods(summary, points, grid, settings)
    provenance: Dict[str, Any] = {
        "summary_csv": str(summary_source),
        "sionna_points_csv": str(points_source),
        "sionna_grid_csv": str(grid_source),
        "synthetic": False,
    }
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
    synthetic_report_path = summary_source.with_suffix(".synthetic_report.json")
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
    return export_analysis(
        comparison,
        summary,
        output_directory,
        method_config_path,
        input_provenance=provenance,
    )
