"""복도 반복 실험의 예측과 통계 계산."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping, Sequence

import numpy as np

from .analysis import idw_predict, regression_metrics
from .corridor_measurements import PROJECT_ROOT, Measurement
from .corridor_repeated_models import (
    CalibrationQc,
    Method,
    MetricRow,
    PredictionRow,
    RepeatabilityRow,
    RunScope,
    SionnaPoint,
    SolverVariant,
)


INCLUDED_RUNS: Final = ("Test_1_004838", "Test_2_010416")
EXCLUDED_RUNS: Final = ("Test_3_011702",)
CALIBRATION_REPEATABILITY_LIMIT_DB: Final = 5.0
PRIMARY_VARIANT: Final = "doors_glass_diffraction_scattering_authored_100m_d5"
PRIMARY_METHOD: Final = "global_bias_all4"
PRIMARY_SCOPE: Final = "repeat_mean_6"
METHODS: Final[tuple[Method, ...]] = (
    "raw_sionna",
    "plain_idw_all4",
    "residual_idw_all4",
    "global_bias_all4",
)
VARIANTS: Final = (
    SolverVariant(
        "doors_glass_base",
        PROJECT_ROOT
        / "scenes/pnu_4f_corridor/rf_experiment/doors_glass_base/processed/sionna_points.csv",
    ),
    SolverVariant(
        "doors_glass_diffraction",
        PROJECT_ROOT
        / "scenes/pnu_4f_corridor/rf_experiment/doors_glass_diffraction/processed/sionna_points.csv",
    ),
    SolverVariant(
        PRIMARY_VARIANT,
        PROJECT_ROOT
        / "scenes/pnu_4f_corridor/rf_experiment/doors_glass_diffraction_scattering_authored_100m_d5/processed/sionna_points.csv",
    ),
)


@dataclass(frozen=True, slots=True)
class CoordinateMismatchError(Exception):
    variant: str
    point_id: str

    def __str__(self) -> str:
        return f"{self.variant} {self.point_id}: 실측/Sionna 좌표가 다릅니다."


def _read_sionna(path: Path) -> Mapping[str, SionnaPoint]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = tuple(SionnaPoint.model_validate(row) for row in csv.DictReader(handle))
    return {row.point_id: row for row in rows}


def _metric(scope: RunScope, rows: Sequence[PredictionRow]) -> MetricRow:
    actual = np.asarray([row.measured_rssi_dbm for row in rows])
    predicted = np.asarray([row.predicted_rssi_dbm for row in rows])
    values = regression_metrics(actual, predicted)
    return MetricRow(
        variant=rows[0].variant,
        scope=scope,
        method=rows[0].method,
        unique_test_locations=len({row.point_id for row in rows}),
        sample_count=values["sample_count"],
        mae_db=values["mae"],
        rmse_db=values["rmse"],
        mean_error_db=values["mean_error_db"],
        median_absolute_error_db=values["median_absolute_error_db"],
        maximum_absolute_error_db=values["maximum_absolute_error_db"],
        pearson_r=values["pearson_r"],
        mae_ci95_low_db=values["mae_ci95_low_db"],
        mae_ci95_high_db=values["mae_ci95_high_db"],
        small_sample_warning=values["small_sample_warning"],
    )


def _predictions(
    variant: SolverVariant,
    measurements: tuple[Measurement, ...],
) -> tuple[PredictionRow, ...]:
    sionna = _read_sionna(variant.points_csv)
    calibration = tuple(row for row in measurements if row.role == "calibration")
    test = tuple(row for row in measurements if row.role == "test")
    for row in measurements:
        simulated = sionna[row.point_id]
        if not np.allclose(
            (row.x, row.y, row.z), (simulated.x, simulated.y, simulated.z)
        ):
            raise CoordinateMismatchError(variant.name, row.point_id)
    cal_positions = np.asarray([(row.x, row.y, row.z) for row in calibration])
    test_positions = np.asarray([(row.x, row.y, row.z) for row in test])
    cal_actual = np.asarray([row.corrected_rssi for row in calibration])
    cal_raw = np.asarray([sionna[row.point_id].sionna_rssi_dbm for row in calibration])
    test_raw = np.asarray([sionna[row.point_id].sionna_rssi_dbm for row in test])
    residuals = cal_actual - cal_raw
    methods: tuple[tuple[Method, np.ndarray], ...] = (
        ("raw_sionna", test_raw),
        ("plain_idw_all4", idw_predict(cal_positions, cal_actual, test_positions)),
        (
            "residual_idw_all4",
            test_raw + idw_predict(cal_positions, residuals, test_positions),
        ),
        ("global_bias_all4", test_raw + float(np.mean(residuals))),
    )
    return tuple(
        PredictionRow(
            variant=variant.name,
            run_id=test_row.run_id,
            point_id=test_row.point_id,
            method=method,
            measured_rssi_dbm=test_row.corrected_rssi,
            predicted_rssi_dbm=float(predicted[index]),
            error_predicted_minus_measured_db=float(
                predicted[index] - test_row.corrected_rssi
            ),
            absolute_error_db=float(abs(predicted[index] - test_row.corrected_rssi)),
        )
        for method, predicted in methods
        for index, test_row in enumerate(test)
    )


def build_calibration_qc(
    runs: Mapping[str, tuple[Measurement, ...]],
) -> tuple[CalibrationQc, ...]:
    by_point = {
        run_id: {row.point_id: row for row in measurements}
        for run_id, measurements in runs.items()
    }
    return tuple(
        CalibrationQc(
            point_id=point_id,
            node_id=by_point[INCLUDED_RUNS[0]][point_id].node_id,
            test_1_median_filtered_dbm=by_point[INCLUDED_RUNS[0]][
                point_id
            ].median_filtered,
            test_2_median_filtered_dbm=by_point[INCLUDED_RUNS[1]][
                point_id
            ].median_filtered,
            raw_absolute_difference_db=abs(
                by_point[INCLUDED_RUNS[1]][point_id].median_filtered
                - by_point[INCLUDED_RUNS[0]][point_id].median_filtered
            ),
            test_1_corrected_rssi_dbm=by_point[INCLUDED_RUNS[0]][
                point_id
            ].corrected_rssi,
            test_2_corrected_rssi_dbm=by_point[INCLUDED_RUNS[1]][
                point_id
            ].corrected_rssi,
            corrected_absolute_difference_db=abs(
                by_point[INCLUDED_RUNS[1]][point_id].corrected_rssi
                - by_point[INCLUDED_RUNS[0]][point_id].corrected_rssi
            ),
            stable_after_device_correction=abs(
                by_point[INCLUDED_RUNS[1]][point_id].corrected_rssi
                - by_point[INCLUDED_RUNS[0]][point_id].corrected_rssi
            )
            <= CALIBRATION_REPEATABILITY_LIMIT_DB,
        )
        for point_id in ("cal-01", "cal-02", "cal-03", "cal-04")
    )


def build_predictions(
    runs: Mapping[str, tuple[Measurement, ...]],
) -> tuple[PredictionRow, ...]:
    return tuple(
        row
        for variant in VARIANTS
        for run in runs.values()
        for row in _predictions(variant, run)
    )


def build_metrics(predictions: tuple[PredictionRow, ...]) -> tuple[MetricRow, ...]:
    metrics: list[MetricRow] = []
    for variant in VARIANTS:
        for method in METHODS:
            rows = tuple(
                row
                for row in predictions
                if row.variant == variant.name and row.method == method
            )
            for run_id in INCLUDED_RUNS:
                metrics.append(
                    _metric(run_id, tuple(row for row in rows if row.run_id == run_id))
                )
            metrics.append(_metric("pooled_12", rows))
            repeat_means = tuple(
                _repeat_mean(point_id, rows)
                for point_id in (f"test-{index:02d}" for index in range(1, 7))
            )
            metrics.append(_metric("repeat_mean_6", repeat_means))
    return tuple(metrics)


def _repeat_mean(
    point_id: str,
    rows: tuple[PredictionRow, ...],
) -> PredictionRow:
    matches = tuple(row for row in rows if row.point_id == point_id)
    actual = float(np.mean([row.measured_rssi_dbm for row in matches]))
    predicted = float(np.mean([row.predicted_rssi_dbm for row in matches]))
    return PredictionRow(
        variant=matches[0].variant,
        run_id="repeat_mean_6",
        point_id=point_id,
        method=matches[0].method,
        measured_rssi_dbm=actual,
        predicted_rssi_dbm=predicted,
        error_predicted_minus_measured_db=predicted - actual,
        absolute_error_db=abs(predicted - actual),
    )


def build_repeatability(
    runs: Mapping[str, tuple[Measurement, ...]],
) -> tuple[RepeatabilityRow, ...]:
    by_point = {
        run_id: {row.point_id: row for row in measurements}
        for run_id, measurements in runs.items()
    }
    return tuple(
        RepeatabilityRow(
            point_id=point_id,
            test_1_corrected_rssi_dbm=by_point[INCLUDED_RUNS[0]][
                point_id
            ].corrected_rssi,
            test_2_corrected_rssi_dbm=by_point[INCLUDED_RUNS[1]][
                point_id
            ].corrected_rssi,
            difference_test_2_minus_test_1_db=(
                by_point[INCLUDED_RUNS[1]][point_id].corrected_rssi
                - by_point[INCLUDED_RUNS[0]][point_id].corrected_rssi
            ),
            absolute_difference_db=abs(
                by_point[INCLUDED_RUNS[1]][point_id].corrected_rssi
                - by_point[INCLUDED_RUNS[0]][point_id].corrected_rssi
            ),
        )
        for point_id in (f"test-{index:02d}" for index in range(1, 7))
    )
