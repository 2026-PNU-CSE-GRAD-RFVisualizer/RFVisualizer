"""복도 반복 분석의 표, 그림, 요약 내보내기."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, TypeVar

import numpy as np
from pydantic import BaseModel

from tools.sionna_smoke_test.io_utils import atomic_write_text

from .corridor_measurements import Measurement
from .corridor_heatmap import export_global_bias_heatmaps
from .corridor_paper_figures import export_kmms_figures
from .corridor_repeated_compute import (
    PRIMARY_METHOD,
    PRIMARY_SCOPE,
    PRIMARY_VARIANT,
    VARIANTS,
)
from .corridor_repeated_models import (
    AnalysisReport,
    CalibrationQc,
    HeldOutComparisonRow,
    MetricRow,
    PredictionRow,
    RepeatabilityRow,
)


RowT = TypeVar("RowT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class ExportBundle:
    measurements: tuple[Measurement, ...]
    calibration_qc: tuple[CalibrationQc, ...]
    predictions: tuple[PredictionRow, ...]
    metrics: tuple[MetricRow, ...]
    repeatability: tuple[RepeatabilityRow, ...]
    report: AnalysisReport


def _write_csv(path: Path, rows: Sequence[RowT]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [row.model_dump(mode="json") for row in rows]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(data[0]))
        writer.writeheader()
        writer.writerows(data)


def _metric(metrics: tuple[MetricRow, ...], scope: str, method: str) -> MetricRow:
    return next(
        row
        for row in metrics
        if row.variant == PRIMARY_VARIANT
        and row.scope == scope
        and row.method == method
    )


def _solver_metric(
    metrics: tuple[MetricRow, ...], variant: str, method: str
) -> MetricRow:
    return next(
        row
        for row in metrics
        if row.variant == variant
        and row.scope == PRIMARY_SCOPE
        and row.method == method
    )


def _mean_prediction(
    predictions: tuple[PredictionRow, ...], point_id: str, method: str
) -> tuple[float, float]:
    rows = tuple(
        row
        for row in predictions
        if row.variant == PRIMARY_VARIANT
        and row.point_id == point_id
        and row.method == method
    )
    return (
        float(np.mean([row.measured_rssi_dbm for row in rows])),
        float(np.mean([row.predicted_rssi_dbm for row in rows])),
    )


def _held_out_rows(
    predictions: tuple[PredictionRow, ...],
) -> tuple[HeldOutComparisonRow, ...]:
    rows = []
    for point_id in (f"test-{index:02d}" for index in range(1, 7)):
        measured, raw = _mean_prediction(predictions, point_id, "raw_sionna")
        _, calibrated = _mean_prediction(predictions, point_id, PRIMARY_METHOD)
        rows.append(
            HeldOutComparisonRow(
                point_id=point_id,
                measured_mean_dbm=measured,
                raw_sionna_dbm=raw,
                calibrated_sionna_dbm=calibrated,
                raw_absolute_error_db=abs(raw - measured),
                calibrated_absolute_error_db=abs(calibrated - measured),
            )
        )
    return tuple(rows)


def _plots(output: Path, bundle: ExportBundle) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures = output / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    primary = tuple(
        row
        for row in bundle.predictions
        if row.variant == PRIMARY_VARIANT
        and row.method in {"raw_sionna", PRIMARY_METHOD}
    )
    colors = {"raw_sionna": "#377eb8", PRIMARY_METHOD: "#4daf4a"}
    figure, axis = plt.subplots(figsize=(8, 8))
    for method, color in colors.items():
        rows = tuple(row for row in primary if row.method == method)
        axis.scatter(
            [row.measured_rssi_dbm for row in rows],
            [row.predicted_rssi_dbm for row in rows],
            label=method,
            color=color,
        )
    bounds = (-76.0, -25.0)
    axis.plot(bounds, bounds, "k--", linewidth=1)
    axis.set(
        xlim=bounds,
        ylim=bounds,
        xlabel="Measured RSSI (dBm)",
        ylabel="Predicted RSSI (dBm)",
        title="Test 1 + Test 2: held-out Test predictions",
    )
    axis.set_aspect("equal", adjustable="box")
    axis.legend()
    figure.tight_layout()
    figure.savefig(figures / "primary_prediction_vs_measurement.png", dpi=180)
    plt.close(figure)

    names = [variant.name for variant in VARIANTS]
    raw = [_solver_metric(bundle.metrics, name, "raw_sionna").mae_db for name in names]
    calibrated = [
        _solver_metric(bundle.metrics, name, PRIMARY_METHOD).mae_db for name in names
    ]
    x = np.arange(len(names))
    figure, axis = plt.subplots(figsize=(9, 5))
    axis.bar(x - 0.18, raw, 0.36, label="Raw Sionna")
    axis.bar(x + 0.18, calibrated, 0.36, label="All-4 global bias")
    axis.set(
        xticks=x,
        xticklabels=names,
        ylabel="MAE (dB)",
        title="Solver and calibration comparison",
    )
    axis.legend()
    figure.tight_layout()
    figure.savefig(figures / "solver_comparison.png", dpi=180)
    plt.close(figure)


def _summary(bundle: ExportBundle) -> str:
    raw = _metric(bundle.metrics, PRIMARY_SCOPE, "raw_sionna")
    primary = _metric(bundle.metrics, PRIMARY_SCOPE, PRIMARY_METHOD)
    raw_pooled = _metric(bundle.metrics, "pooled_12", "raw_sionna")
    pooled = _metric(bundle.metrics, "pooled_12", PRIMARY_METHOD)
    solver_rows = tuple(
        _solver_metric(bundle.metrics, variant.name, method)
        for variant in VARIANTS
        for method in ("raw_sionna", PRIMARY_METHOD)
    )
    solver_table = "\n".join(
        f"| {row.variant} | {row.method} | {row.mae_db:.2f} | {row.rmse_db:.2f} |"
        for row in solver_rows
    )
    held_out_table = "\n".join(
        f"| {row.point_id} | {row.measured_mean_dbm:.2f} | {row.raw_sionna_dbm:.2f} | {row.calibrated_sionna_dbm:.2f} | {row.calibrated_absolute_error_db:.2f} |"
        for row in _held_out_rows(bundle.predictions)
    )
    report = bundle.report
    return f"""# PNU 4F Corridor Test 1·2 결과

## 한 줄 결론

회절+산란 Raw Sionna의 6개 Test 위치 MAE는 **{raw.mae_db:.2f} dB**, 네 Calibration 위치를 모두 쓴 전역 편향 보정 후에는 **{primary.mae_db:.2f} dB**다. Test 3은 철문 상태가 달라 제외했다.

## 최종 비교

| 결과 | MAE (dB) | RMSE (dB) | Pearson r |
|---|---:|---:|---:|
| 단순 Sionna RT: 회절+산란 | {raw.mae_db:.2f} | {raw.rmse_db:.2f} | {raw.pearson_r:.3f} |
| Calibration 보정: all-4 global bias | {primary.mae_db:.2f} | {primary.rmse_db:.2f} | {primary.pearson_r:.3f} |

- 주 평가는 Test 1·2의 같은 위치를 먼저 평균한 **6개 독립 위치** 기준이다.
- 보정 MAE의 위치 bootstrap 95% 구간은 **{primary.mae_ci95_low_db:.2f}–{primary.mae_ci95_high_db:.2f} dB**다.
- 12개 반복 관측을 그대로 합친 MAE는 Raw **{raw_pooled.mae_db:.2f} dB**, 보정 **{pooled.mae_db:.2f} dB**다.

## Held-out Test 실제값 vs 예측값

| 위치 | 실제 평균 (dBm) | Raw Sionna (dBm) | 보정 Sionna (dBm) | 보정 절대오차 (dB) |
|---|---:|---:|---:|---:|
{held_out_table}

## Solver 비교

| Solver | 방법 | 6개 위치 MAE (dB) | RMSE (dB) |
|---|---|---:|---:|
{solver_table}

세 Solver의 차이는 반복 측정 오차와 함께 해석해야 하며, 작은 MAE 차이만으로 물리 모델의 우열을 단정할 수 없다.

## 신뢰도 제한

- 장치 보정 뒤 Calibration 반복 차이는 평균 **{report.calibration_repeatability_mean_absolute_difference_db:.2f} dB**, 최대 **{report.calibration_repeatability_maximum_absolute_difference_db:.2f} dB**다. 5 dB 이내인 점은 `cal-04` 하나뿐이다.
- Test 1·2 동일 위치의 평균 절대 차이는 **{report.test_repeatability_mean_absolute_difference_db:.2f} dB**, 최대 **{report.test_repeatability_maximum_absolute_difference_db:.2f} dB**다.
- 실측 TX x=3.13 m와 Sionna TX x=3.15 m 사이에 0.02 m 차이가 있다.
- 따라서 개별 위치의 절대 RSSI 신뢰도는 낮고, 큰 공간 경향의 신뢰도만 중간 수준으로 해석한다.
- Scene/Marker와 작성된 재질 계수는 아직 provisional이므로 확정된 물성값처럼 쓰지 않는다.
"""


def export_results(output: Path, bundle: ExportBundle) -> None:
    processed = output / "processed"
    _write_csv(processed / "measurements_reconstructed.csv", bundle.measurements)
    _write_csv(processed / "calibration_qc.csv", bundle.calibration_qc)
    _write_csv(processed / "predictions.csv", bundle.predictions)
    _write_csv(processed / "metrics.csv", bundle.metrics)
    _write_csv(processed / "repeatability.csv", bundle.repeatability)
    _write_csv(
        processed / "held_out_test_comparison.csv",
        _held_out_rows(bundle.predictions),
    )
    processed.mkdir(parents=True, exist_ok=True)
    (processed / "analysis_report.json").write_text(
        bundle.report.model_dump_json(indent=2), encoding="utf-8"
    )
    _plots(output, bundle)
    export_global_bias_heatmaps(output, bundle.measurements, VARIANTS[-1].points_csv)
    export_kmms_figures(output, bundle.measurements, bundle.predictions)
    atomic_write_text(output / "RESULTS_SUMMARY.md", _summary(bundle))
