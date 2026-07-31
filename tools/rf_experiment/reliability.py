"""Held-out RSSI prediction accuracy and uncertainty metrics."""

from __future__ import annotations

from typing import Final, Mapping, TypedDict

import numpy as np
import numpy.typing as npt


BOOTSTRAP_SAMPLES: Final = 10_000
BOOTSTRAP_SEED: Final = 0
SMALL_SAMPLE_LIMIT: Final = 10

FloatArray = npt.NDArray[np.float64]


class PredictionMetrics(TypedDict):
    sample_count: int
    mae: float
    rmse: float
    mean_error_db: float
    median_absolute_error_db: float
    maximum_absolute_error_db: float
    pearson_r: float | None
    mae_ci95_low_db: float
    mae_ci95_high_db: float
    mae_ci95_method: str
    small_sample_warning: bool


class MetricsCsvRow(TypedDict):
    method: str
    sample_count: int
    mae_db: float
    rmse_db: float
    mean_error_db: float
    median_absolute_error_db: float
    maximum_absolute_error_db: float
    pearson_r: float | None
    mae_ci95_low_db: float
    mae_ci95_high_db: float
    mae_ci95_method: str
    small_sample_warning: bool


def prediction_metrics(actual: FloatArray, predicted: FloatArray) -> PredictionMetrics:
    """Summarize held-out errors; inputs are validated by the analysis boundary."""

    signed_error = predicted - actual
    absolute_error = np.abs(signed_error)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    indices = rng.integers(
        0, len(absolute_error), size=(BOOTSTRAP_SAMPLES, len(absolute_error))
    )
    bootstrap_mae = np.mean(absolute_error[indices], axis=1)
    ci_low, ci_high = np.percentile(bootstrap_mae, (2.5, 97.5))
    pearson_r = None
    if (
        len(actual) >= 2
        and float(np.std(actual)) > 0.0
        and float(np.std(predicted)) > 0.0
    ):
        pearson_r = float(np.corrcoef(actual, predicted)[0, 1])
    return {
        "sample_count": len(actual),
        "mae": float(np.mean(absolute_error)),
        "rmse": float(np.sqrt(np.mean(np.square(signed_error)))),
        "mean_error_db": float(np.mean(signed_error)),
        "median_absolute_error_db": float(np.median(absolute_error)),
        "maximum_absolute_error_db": float(np.max(absolute_error)),
        "pearson_r": pearson_r,
        "mae_ci95_low_db": float(ci_low),
        "mae_ci95_high_db": float(ci_high),
        "mae_ci95_method": "percentile_bootstrap_10000_seed_0",
        "small_sample_warning": len(actual) < SMALL_SAMPLE_LIMIT,
    }


def metrics_csv_rows(
    metrics: Mapping[str, PredictionMetrics],
) -> list[MetricsCsvRow]:
    """Convert method-keyed metrics to the stable CSV output contract."""

    return [
        {
            "method": name,
            "sample_count": values["sample_count"],
            "mae_db": values["mae"],
            "rmse_db": values["rmse"],
            "mean_error_db": values["mean_error_db"],
            "median_absolute_error_db": values["median_absolute_error_db"],
            "maximum_absolute_error_db": values["maximum_absolute_error_db"],
            "pearson_r": values["pearson_r"],
            "mae_ci95_low_db": values["mae_ci95_low_db"],
            "mae_ci95_high_db": values["mae_ci95_high_db"],
            "mae_ci95_method": values["mae_ci95_method"],
            "small_sample_warning": values["small_sample_warning"],
        }
        for name, values in metrics.items()
    ]
