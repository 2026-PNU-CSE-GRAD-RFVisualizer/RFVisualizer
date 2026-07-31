"""IDW 예측과 방법별 정량 비교."""

from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Sequence

import numpy as np

from .analysis_inputs import AnalysisError
from .reliability import PredictionMetrics, prediction_metrics


def _finite_array(value: Any, field: str, dimensions: int) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.ndim != dimensions or not np.all(np.isfinite(array)):
        raise AnalysisError("{}는 유한한 {}차원 숫자 배열이어야 합니다.".format(field, dimensions))
    return array


def idw_predict(
    sample_positions: Any,
    sample_values: Any,
    query_positions: Any,
    power: float = 2.0,
    epsilon_distance_power: float = 1.0e-12,
    exact_match_tolerance_m: float = 1.0e-9,
) -> np.ndarray:
    samples = _finite_array(sample_positions, "sample_positions", 2)
    values = _finite_array(sample_values, "sample_values", 1)
    queries = _finite_array(query_positions, "query_positions", 2)
    if samples.shape[1] != 3 or queries.shape[1] != 3:
        raise AnalysisError("IDW 위치는 N×3 [x,y,z]여야 합니다.")
    if len(samples) == 0 or len(values) != len(samples):
        raise AnalysisError("IDW sample 위치와 값의 개수가 맞지 않습니다.")
    p = float(power)
    epsilon = float(epsilon_distance_power)
    tolerance = float(exact_match_tolerance_m)
    if not math.isfinite(p) or p <= 0.0:
        raise AnalysisError("IDW power는 유한한 양수여야 합니다.")
    if not math.isfinite(epsilon) or epsilon <= 0.0:
        raise AnalysisError("IDW epsilon은 유한한 양수여야 합니다.")
    if not math.isfinite(tolerance) or tolerance < 0.0:
        raise AnalysisError("IDW exact match tolerance는 유한한 0 이상 값이어야 합니다.")

    distances = np.linalg.norm(queries[:, None, :] - samples[None, :, :], axis=2)
    predictions = np.empty(len(queries), dtype=float)
    for index, row in enumerate(distances):
        exact = row <= tolerance
        if np.any(exact):
            predictions[index] = float(np.mean(values[exact]))
            continue
        weights = 1.0 / (np.power(row, p) + epsilon)
        denominator = float(np.sum(weights))
        if not math.isfinite(denominator) or denominator <= 0.0:
            raise AnalysisError("IDW 가중치 합이 유효하지 않습니다.")
        predictions[index] = float(np.dot(weights, values) / denominator)
    return predictions


def regression_metrics(actual: Any, predicted: Any) -> PredictionMetrics:
    target = _finite_array(actual, "actual", 1)
    estimate = _finite_array(predicted, "predicted", 1)
    if len(target) == 0 or target.shape != estimate.shape:
        raise AnalysisError("평가 실제값과 예측값의 개수가 맞지 않습니다.")
    return prediction_metrics(target, estimate)


def compare_methods(
    summary: Sequence[Mapping[str, Any]],
    sionna_points: Mapping[str, Mapping[str, Any]],
    sionna_grid: Sequence[Mapping[str, Any]],
    idw_settings: Mapping[str, float],
    coordinate_tolerance_m: float = 1.0e-6,
) -> Dict[str, Any]:
    calibration = [row for row in summary if row["role"] == "calibration"]
    test = [row for row in summary if row["role"] == "test"]
    missing = [row["point_id"] for row in summary if row["point_id"] not in sionna_points]
    if missing:
        raise AnalysisError("Sionna point 예측이 없는 위치가 있습니다: {}".format(missing))
    for row in summary:
        source = sionna_points[row["point_id"]]
        error = float(np.linalg.norm(row["position"] - source["position"]))
        if error > coordinate_tolerance_m:
            raise AnalysisError(
                "{}의 Summary/Sionna 좌표가 다릅니다: {:.6g}m".format(row["point_id"], error)
            )

    calibration_positions = np.asarray([row["position"] for row in calibration])
    calibration_actual = np.asarray([row["actual_rssi_dbm"] for row in calibration])
    calibration_sionna = np.asarray(
        [sionna_points[row["point_id"]]["sionna_rssi_dbm"] for row in calibration]
    )
    test_positions = np.asarray([row["position"] for row in test])
    test_actual = np.asarray([row["actual_rssi_dbm"] for row in test])
    raw_test = np.asarray(
        [sionna_points[row["point_id"]]["sionna_rssi_dbm"] for row in test]
    )
    plain_test = idw_predict(
        calibration_positions, calibration_actual, test_positions, **idw_settings
    )
    calibration_residuals = calibration_actual - calibration_sionna
    residual_test = raw_test + idw_predict(
        calibration_positions, calibration_residuals, test_positions, **idw_settings
    )

    grid_positions = np.asarray([row["position"] for row in sionna_grid])
    raw_grid = np.asarray([row["sionna_rssi_dbm"] for row in sionna_grid])
    plain_grid = idw_predict(
        calibration_positions, calibration_actual, grid_positions, **idw_settings
    )
    residual_grid = raw_grid + idw_predict(
        calibration_positions, calibration_residuals, grid_positions, **idw_settings
    )
    predictions = {
        "raw_sionna": raw_test,
        "plain_idw": plain_test,
        "residual_idw": residual_test,
    }
    metrics = {
        name: regression_metrics(test_actual, values)
        for name, values in predictions.items()
    }
    return {
        "calibration": calibration,
        "test": test,
        "test_actual": test_actual,
        "test_predictions": predictions,
        "calibration_residuals": calibration_residuals,
        "grid_positions": grid_positions,
        "grid_ids": [row["grid_id"] for row in sionna_grid],
        "grid_rows": [int(row["row"]) for row in sionna_grid],
        "grid_columns": [int(row["column"]) for row in sionna_grid],
        "grid_predictions": {
            "raw_sionna": raw_grid,
            "plain_idw": plain_grid,
            "residual_idw": residual_grid,
        },
        "metrics": metrics,
        "data_split_validation": {
            "fit_roles": ["calibration"],
            "evaluation_roles": ["test"],
            "calibration_count": len(calibration),
            "test_count": len(test),
            "test_values_used_in_fitting": False,
            "success": True,
        },
    }
