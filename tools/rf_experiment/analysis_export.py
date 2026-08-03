"""분석 CSV, 그림, JSON 보고서 내보내기."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

import numpy as np

from tools.sionna_smoke_test.io_utils import (
    SmokeTestIOError,
    atomic_write_text,
    write_csv,
    write_json,
)

from .analysis_inputs import AnalysisError
from .analysis_plots import (
    _plot_heatmap,
    _plot_measured_points,
    _plot_prediction_vs_measurement,
)
from .contracts import resolve_path
from .reliability import metrics_csv_rows


def _write_csv(
    path: Path, fieldnames: Sequence[str], rows: Sequence[Mapping[str, Any]]
) -> None:
    try:
        write_csv(path, fieldnames, rows)
    except SmokeTestIOError as exc:
        raise AnalysisError("CSV를 저장할 수 없습니다: {}".format(exc)) from exc


def export_analysis(
    comparison: Mapping[str, Any],
    summary: Sequence[Mapping[str, Any]],
    output_directory: Any,
    method_config_path: Any,
    input_provenance: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    output = resolve_path(output_directory)
    processed = output / "processed"
    figures = output / "figures"
    processed.mkdir(parents=True, exist_ok=True)
    figures.mkdir(parents=True, exist_ok=True)
    method_source = resolve_path(method_config_path)
    provenance = dict(input_provenance or {})
    synthetic = bool(provenance.get("synthetic", False))
    paper_evidence_eligible = bool(
        not synthetic and provenance.get("sionna_paper_evidence_eligible", True)
    )

    test_rows = []
    actual = comparison["test_actual"]
    predictions = comparison["test_predictions"]
    for index, row in enumerate(comparison["test"]):
        test_rows.append(
            {
                "point_id": row["point_id"],
                "node_id": row["node_id"],
                "x": row["position"][0],
                "y": row["position"][1],
                "z": row["position"][2],
                "measured_rssi_dbm": actual[index],
                "raw_sionna_rssi_dbm": predictions["raw_sionna"][index],
                "raw_sionna_abs_error_db": abs(actual[index] - predictions["raw_sionna"][index]),
                "plain_idw_rssi_dbm": predictions["plain_idw"][index],
                "plain_idw_abs_error_db": abs(actual[index] - predictions["plain_idw"][index]),
                "residual_idw_rssi_dbm": predictions["residual_idw"][index],
                "residual_idw_abs_error_db": abs(
                    actual[index] - predictions["residual_idw"][index]
                ),
            }
        )
    comparison_path = processed / "comparison_results.csv"
    _write_csv(comparison_path, list(test_rows[0].keys()), test_rows)
    metric_rows = metrics_csv_rows(comparison["metrics"])
    metrics_path = processed / "metrics.csv"
    _write_csv(metrics_path, tuple(metric_rows[0]), metric_rows)

    grid_rows = []
    for index, grid_id in enumerate(comparison["grid_ids"]):
        position = comparison["grid_positions"][index]
        grid_rows.append(
            {
                "grid_id": grid_id,
                "row": comparison["grid_rows"][index],
                "column": comparison["grid_columns"][index],
                "x": position[0],
                "y": position[1],
                "z": position[2],
                "raw_sionna_rssi_dbm": comparison["grid_predictions"]["raw_sionna"][index],
                "plain_idw_rssi_dbm": comparison["grid_predictions"]["plain_idw"][index],
                "residual_idw_rssi_dbm": comparison["grid_predictions"]["residual_idw"][index],
            }
        )
    grid_path = processed / "grid_predictions.csv"
    _write_csv(grid_path, list(grid_rows[0].keys()), grid_rows)

    all_grid = np.concatenate(list(comparison["grid_predictions"].values()))
    vmin, vmax = float(np.min(all_grid)), float(np.max(all_grid))
    if abs(vmax - vmin) <= 1.0e-12:
        vmin, vmax = vmin - 1.0, vmax + 1.0
    measured_path = figures / "measured_points.png"
    prediction_path = figures / "prediction_vs_measurement.png"
    _plot_measured_points(measured_path, summary)
    _plot_prediction_vs_measurement(prediction_path, comparison)
    titles = {
        "raw_sionna": "Raw Sionna RT",
        "plain_idw": "Plain IDW from calibration measurements",
        "residual_idw": "Sionna RT + Residual IDW",
    }
    heatmap_paths = {}
    for name, filename in (
        ("raw_sionna", "raw_sionna_heatmap.png"),
        ("plain_idw", "plain_idw_heatmap.png"),
        ("residual_idw", "residual_idw_heatmap.png"),
    ):
        path = figures / filename
        _plot_heatmap(
            path,
            comparison["grid_positions"],
            comparison["grid_predictions"][name],
            comparison["calibration"],
            comparison["test"],
            titles[name],
            (vmin, vmax),
        )
        heatmap_paths[name] = str(path.resolve())

    report_path = processed / "analysis_report.json"
    report = {
        "schema_version": "1.0",
        "success": True,
        "paper_evidence_eligible": paper_evidence_eligible,
        "input_provenance": {"synthetic": synthetic, **provenance},
        "method_config": str(method_source),
        "metrics": comparison["metrics"],
        "data_split_validation": comparison["data_split_validation"],
        "shared_heatmap_color_limits_dbm": [vmin, vmax],
        "minimum_success_condition": {
            "residual_idw_better_than_plain_idw_mae": comparison["metrics"]["residual_idw"]["mae"]
            < comparison["metrics"]["plain_idw"]["mae"],
            "residual_idw_better_than_plain_idw_rmse": comparison["metrics"]["residual_idw"]["rmse"]
            < comparison["metrics"]["plain_idw"]["rmse"],
        },
        "files": {
            "comparison_results_csv": str(comparison_path.resolve()),
            "metrics_csv": str(metrics_path.resolve()),
            "grid_predictions_csv": str(grid_path.resolve()),
            "measured_points_png": str(measured_path.resolve()),
            "prediction_vs_measurement_png": str(prediction_path.resolve()),
            "heatmaps": heatmap_paths,
        },
    }
    readme_path = output / "README.md"
    table = "\n".join(
        "| {} | {:.6f} | {:.6f} |".format(row["method"], row["mae_db"], row["rmse_db"])
        for row in metric_rows
    )
    atomic_write_text(
        readme_path,
        """# RFVisualizer 실험 분석 결과

## 한 줄 결론

{summary_text}

| 방법 | MAE (dB) | RMSE (dB) |
|---|---:|---:|
{table}

## 검증

- IDW와 Residual IDW fitting에는 calibration 위치만 사용했다.
- Test 실제값은 지표 계산에만 사용했다.
- 세 히트맵은 `{vmin:.3f}`–`{vmax:.3f}` dBm의 동일한 색상 범위를 사용했다.
""".format(
            summary_text=(
                "**SYNTHETIC DRY RUN ONLY — 이 수치와 그림은 논문 근거로 사용할 수 없다.**"
                if synthetic
                else (
                    "**DRAFT SIONNA INPUT — 초안 Scene 결과이므로 논문 근거로 사용할 수 없다.**"
                    if not paper_evidence_eligible
                    else "세 방법을 보정 위치와 분리된 Test 위치에서 비교했으며, 아래 값은 `corrected_rssi` 기준이다."
                )
            ),
            table=table,
            vmin=vmin,
            vmax=vmax,
        ),
    )
    report["files"]["analysis_report_json"] = str(report_path.resolve())
    report["files"]["readme"] = str(readme_path.resolve())
    write_json(report_path, report)
    return report
