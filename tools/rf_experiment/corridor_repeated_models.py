"""Test 1·2 반복 분석의 직렬화 계약."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict


RunScope = Literal["Test_1_004838", "Test_2_010416", "pooled_12", "repeat_mean_6"]
Method = Literal[
    "raw_sionna",
    "plain_idw_all4",
    "residual_idw_all4",
    "global_bias_all4",
]


@dataclass(frozen=True, slots=True)
class SolverVariant:
    name: str
    points_csv: Path


class SionnaPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    point_id: str
    x: float
    y: float
    z: float
    sionna_rssi_dbm: float


class CalibrationQc(BaseModel):
    model_config = ConfigDict(frozen=True)

    point_id: str
    node_id: str
    test_1_median_filtered_dbm: float
    test_2_median_filtered_dbm: float
    raw_absolute_difference_db: float
    test_1_corrected_rssi_dbm: float
    test_2_corrected_rssi_dbm: float
    corrected_absolute_difference_db: float
    stable_after_device_correction: bool


class PredictionRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    variant: str
    run_id: str
    point_id: str
    method: Method
    measured_rssi_dbm: float
    predicted_rssi_dbm: float
    error_predicted_minus_measured_db: float
    absolute_error_db: float


class MetricRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    variant: str
    scope: RunScope
    method: Method
    unique_test_locations: int
    sample_count: int
    mae_db: float
    rmse_db: float
    mean_error_db: float
    median_absolute_error_db: float
    maximum_absolute_error_db: float
    pearson_r: float | None
    mae_ci95_low_db: float
    mae_ci95_high_db: float
    small_sample_warning: bool


class RepeatabilityRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    point_id: str
    test_1_corrected_rssi_dbm: float
    test_2_corrected_rssi_dbm: float
    difference_test_2_minus_test_1_db: float
    absolute_difference_db: float


class HeldOutComparisonRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    point_id: str
    measured_mean_dbm: float
    raw_sionna_dbm: float
    calibrated_sionna_dbm: float
    raw_absolute_error_db: float
    calibrated_absolute_error_db: float


class AnalysisReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: str
    status: str
    included_runs: tuple[str, ...]
    excluded_runs: tuple[str, ...]
    stable_calibration_points: tuple[str, ...]
    unstable_calibration_points: tuple[str, ...]
    primary_variant: str
    primary_method: str
    primary_evaluation_scope: str
    primary_mae_db: float
    primary_rmse_db: float
    primary_pearson_r: float | None
    primary_mae_ci95_db: tuple[float, float]
    pooled_repeated_mae_db: float
    calibration_repeatability_mean_absolute_difference_db: float
    calibration_repeatability_maximum_absolute_difference_db: float
    test_repeatability_mean_absolute_difference_db: float
    test_repeatability_maximum_absolute_difference_db: float
    paper_evidence_eligible: bool
    limitations: tuple[str, ...]
    source_sha256: tuple[tuple[str, str], ...]
