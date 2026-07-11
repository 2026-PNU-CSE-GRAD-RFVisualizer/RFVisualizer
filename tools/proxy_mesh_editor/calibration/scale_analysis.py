"""여러 기준 길이에서 단일 meters-per-scene-unit 축척을 진단한다."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List

import numpy as np


class ScaleAnalysisError(ValueError):
    """축척 기준이나 추정기 설정에 문제가 있을 때 발생한다."""


def _reference_values(references: List[Dict[str, Any]]):
    scene = np.asarray([float(item["scene_distance"]) for item in references], dtype=float)
    real = np.asarray(
        [float(item["assumed_real_distance_m"]) for item in references], dtype=float
    )
    weights = np.asarray([float(item.get("weight", 1.0)) for item in references], dtype=float)
    if (
        np.any(~np.isfinite(scene))
        or np.any(~np.isfinite(real))
        or np.any(~np.isfinite(weights))
        or np.any(scene <= 0.0)
        or np.any(real <= 0.0)
        or np.any(weights <= 0.0)
    ):
        raise ScaleAnalysisError("scene distance, real distance, weight는 유한한 양수여야 합니다.")
    return scene, real, weights


def _residuals(
    references: List[Dict[str, Any]], scale: float
) -> List[Dict[str, Any]]:
    result = []
    for item in references:
        scene = float(item["scene_distance"])
        target = float(item["assumed_real_distance_m"])
        predicted = scale * scene
        error = predicted - target
        result.append(
            {
                "reference_name": str(item["name"]),
                "predicted_metric_distance_m": float(predicted),
                "target_metric_distance_m": target,
                "signed_error_m": float(error),
                "absolute_error_m": float(abs(error)),
                "relative_error": float(error / target),
                "absolute_relative_error": float(abs(error) / target),
            }
        )
    return result


def analyze_scale_references(
    references: List[Dict[str, Any]], settings: Dict[str, Any]
) -> Dict[str, Any]:
    if not references:
        raise ScaleAnalysisError("축척 기준이 하나 이상 필요합니다.")
    scene, real, weights = _reference_values(references)
    ratios = real / scene
    scales = {
        "arithmetic_mean_of_ratios": float(np.mean(ratios)),
        "weighted_mean_of_ratios": float(np.sum(weights * ratios) / np.sum(weights)),
        "weighted_least_squares": float(
            np.sum(weights * scene * real) / np.sum(weights * np.square(scene))
        ),
        "median_of_ratios": float(np.median(ratios)),
    }
    supported = set(settings["supported_estimators"])
    estimators = {}
    for name, scale in scales.items():
        if name in supported:
            estimators[name] = {
                "meters_per_scene_unit": scale,
                "reference_residuals": _residuals(references, scale),
            }
    recommended_name = str(settings["recommended_estimator"])
    if recommended_name not in estimators:
        raise ScaleAnalysisError("추천 estimator 결과를 계산하지 못했습니다.")

    mean_scale = float(np.mean(ratios))
    relative_spread = float((np.max(ratios) - np.min(ratios)) / mean_scale)
    warning_limit = float(settings["warning_relative_spread"])
    failure_limit = float(settings["failure_relative_spread"])
    if relative_spread > failure_limit:
        spread_status = "failure"
    elif relative_spread > warning_limit:
        spread_status = "warning"
    else:
        spread_status = "pass"

    reference_results = []
    for index, item in enumerate(references):
        reference_results.append(
            {
                **item,
                "individual_meters_per_scene_unit": float(ratios[index]),
            }
        )
    return {
        "uniform_scale_only": True,
        "references": reference_results,
        "estimators": estimators,
        "recommended_estimator": recommended_name,
        "recommended_meters_per_scene_unit": estimators[recommended_name][
            "meters_per_scene_unit"
        ],
        "recommended_reference_residuals": estimators[recommended_name][
            "reference_residuals"
        ],
        "individual_scale_minimum": float(np.min(ratios)),
        "individual_scale_maximum": float(np.max(ratios)),
        "individual_scale_mean": mean_scale,
        "relative_spread": relative_spread,
        "warning_relative_spread": warning_limit,
        "failure_relative_spread": failure_limit,
        "spread_status": spread_status,
    }


def write_scale_analysis_csv(path: Path, analysis: Dict[str, Any]) -> None:
    rows = []
    for estimator_name, estimator in analysis["estimators"].items():
        for residual in estimator["reference_residuals"]:
            rows.append(
                {
                    "estimator": estimator_name,
                    "meters_per_scene_unit": estimator["meters_per_scene_unit"],
                    **residual,
                }
            )
    output = Path(path)
    temporary = output.with_suffix(output.suffix + ".tmp")
    fields = (
        "estimator",
        "meters_per_scene_unit",
        "reference_name",
        "predicted_metric_distance_m",
        "target_metric_distance_m",
        "signed_error_m",
        "absolute_error_m",
        "relative_error",
        "absolute_relative_error",
    )
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(output)
    except OSError as exc:
        raise ScaleAnalysisError("scale CSV를 저장하지 못했습니다: {}".format(exc)) from exc
