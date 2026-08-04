# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib>=3.10,<4", "numpy>=2.3,<3", "pydantic>=2.12,<3"]
# ///
# ─── How to run ───
# python -m tools.rf_experiment.corridor_repeated_analysis
"""Test 1·2 실측과 세 Sionna 해석의 Calibration/Test 비교."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

import numpy as np

from .corridor_measurements import MARKERS_PATH, PROJECT_ROOT, TESTS_ROOT, load_run
from .corridor_repeated_compute import (
    EXCLUDED_RUNS,
    INCLUDED_RUNS,
    PRIMARY_METHOD,
    PRIMARY_SCOPE,
    PRIMARY_VARIANT,
    VARIANTS,
    build_calibration_qc,
    build_metrics,
    build_predictions,
    build_repeatability,
)
from .corridor_repeated_export import ExportBundle, export_results
from .corridor_repeated_models import (
    AnalysisReport,
    CalibrationQc,
    MetricRow,
    RepeatabilityRow,
)


DEFAULT_OUTPUT: Final = (
    PROJECT_ROOT
    / "scenes/pnu_4f_corridor/rf_experiment/spreadsheet/doors_glass_100m_d5_tests_1_2"
)


def _primary(metrics: tuple[MetricRow, ...], scope: str, method: str) -> MetricRow:
    return next(
        row
        for row in metrics
        if row.variant == PRIMARY_VARIANT
        and row.scope == scope
        and row.method == method
    )


def _sources() -> tuple[tuple[str, str], ...]:
    paths = (
        MARKERS_PATH,
        *(TESTS_ROOT / run / "raw/measurements_raw.csv" for run in INCLUDED_RUNS),
        *(TESTS_ROOT / run / "config/device_offsets.json" for run in INCLUDED_RUNS),
        *(TESTS_ROOT / run / "config/tx_rx.json" for run in INCLUDED_RUNS),
        *(variant.points_csv for variant in VARIANTS),
    )
    return tuple(
        (
            str(path.relative_to(PROJECT_ROOT)),
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in paths
    )


def _report(
    calibration_qc: tuple[CalibrationQc, ...],
    metrics: tuple[MetricRow, ...],
    repeatability: tuple[RepeatabilityRow, ...],
) -> AnalysisReport:
    primary = _primary(metrics, PRIMARY_SCOPE, PRIMARY_METHOD)
    pooled = _primary(metrics, "pooled_12", PRIMARY_METHOD)
    calibration_differences = [
        row.corrected_absolute_difference_db for row in calibration_qc
    ]
    return AnalysisReport(
        schema_version="1.1",
        status="provisional_real_measurements",
        included_runs=INCLUDED_RUNS,
        excluded_runs=EXCLUDED_RUNS,
        stable_calibration_points=tuple(
            row.point_id for row in calibration_qc if row.stable_after_device_correction
        ),
        unstable_calibration_points=tuple(
            row.point_id
            for row in calibration_qc
            if not row.stable_after_device_correction
        ),
        primary_variant=PRIMARY_VARIANT,
        primary_method=PRIMARY_METHOD,
        primary_evaluation_scope=PRIMARY_SCOPE,
        primary_mae_db=primary.mae_db,
        primary_rmse_db=primary.rmse_db,
        primary_pearson_r=primary.pearson_r,
        primary_mae_ci95_db=(primary.mae_ci95_low_db, primary.mae_ci95_high_db),
        pooled_repeated_mae_db=pooled.mae_db,
        calibration_repeatability_mean_absolute_difference_db=float(
            np.mean(calibration_differences)
        ),
        calibration_repeatability_maximum_absolute_difference_db=max(
            calibration_differences
        ),
        test_repeatability_mean_absolute_difference_db=float(
            np.mean([row.absolute_difference_db for row in repeatability])
        ),
        test_repeatability_maximum_absolute_difference_db=max(
            row.absolute_difference_db for row in repeatability
        ),
        paper_evidence_eligible=False,
        limitations=(
            "Test 3은 철문 상태가 Proxy와 달라 제외했다.",
            "Backend 좌표·역할 누락을 기존 장치 배치 계약으로 복원했다.",
            "장치 보정 후 5 dB 이내로 반복된 Calibration 위치는 cal-04 한 곳뿐이다.",
            "실측 TX x=3.13 m와 Sionna TX x=3.15 m 사이에 0.02 m 차이가 있다.",
            "Test 위치는 6개뿐이며 두 반복의 평균 절대 차이는 6 dB를 넘는다.",
            "Scene/Marker와 작성된 재질 계수는 아직 provisional이다.",
        ),
        source_sha256=_sources(),
    )


def run_corridor_analysis(output_directory: Path) -> AnalysisReport:
    runs = {run_id: load_run(run_id) for run_id in INCLUDED_RUNS}
    calibration_qc = build_calibration_qc(runs)
    predictions = build_predictions(runs)
    metrics = build_metrics(predictions)
    repeatability = build_repeatability(runs)
    report = _report(calibration_qc, metrics, repeatability)
    export_results(
        output_directory,
        ExportBundle(
            measurements=tuple(row for run in runs.values() for row in run),
            calibration_qc=calibration_qc,
            predictions=predictions,
            metrics=metrics,
            repeatability=repeatability,
            report=report,
        ),
    )
    return report


if __name__ == "__main__":
    print(run_corridor_analysis(DEFAULT_OUTPUT).model_dump_json(indent=2))
