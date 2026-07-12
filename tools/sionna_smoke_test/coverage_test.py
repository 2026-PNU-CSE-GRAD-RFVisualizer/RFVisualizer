"""Sionna RadioMapSolver로 저해상도 수평 path-gain 지도를 계산한다."""

from __future__ import annotations

import time
from typing import Any, Dict, List

import numpy as np


class CoverageTestError(RuntimeError):
    """Coverage 계산 또는 유효 셀 검증에 실패했을 때 발생한다."""


def _numpy(value):
    try:
        return np.asarray(value.numpy())
    except AttributeError:
        return np.asarray(value)


def run_coverage_solver(scene, settings: Dict[str, Any], room, positions: List[Dict[str, Any]]):
    from sionna.rt import RadioMapSolver

    coverage = settings["coverage"]
    margin = float(coverage["margin_m"])
    minimum = room.bounds_min[:2] + margin
    maximum = room.bounds_max[:2] - margin
    size = maximum - minimum
    if np.any(size <= 0.0):
        raise CoverageTestError("Coverage margin을 제외한 영역이 비어 있습니다.")
    cell_size = float(coverage["cell_size_m"])
    cells_xy = np.ceil(size / cell_size).astype(int)
    if int(np.prod(cells_xy)) > int(coverage["max_cells"]):
        raise CoverageTestError("Coverage cell 수가 max_cells를 넘습니다.")
    center = [
        float((minimum[0] + maximum[0]) / 2.0),
        float((minimum[1] + maximum[1]) / 2.0),
        float(coverage["z_height_m"]),
    ]
    solver = RadioMapSolver()
    start = time.perf_counter()
    radio_map = solver(
        scene=scene,
        center=center,
        orientation=[0.0, 0.0, 0.0],
        size=size.tolist(),
        cell_size=[cell_size, cell_size],
        samples_per_tx=int(coverage["samples_per_tx"]),
        max_depth=int(coverage["max_depth"]),
        los=bool(coverage["enable_los"]),
        specular_reflection=bool(coverage["enable_reflection"]),
        diffuse_reflection=bool(coverage["enable_scattering"]),
        refraction=bool(coverage["enable_refraction"]),
        diffraction=bool(coverage["enable_diffraction"]),
        edge_diffraction=False,
        seed=int(coverage["seed"]),
    )
    elapsed = time.perf_counter() - start
    values = _numpy(radio_map.path_gain)
    if values.ndim != 3 or values.shape[0] < 1:
        raise CoverageTestError("RadioMap path_gain 배열 모양이 예상과 다릅니다: {}".format(values.shape))
    values = values[0].astype(float)
    centers = _numpy(radio_map.cell_centers).astype(float)
    if centers.shape[:2] != values.shape or centers.shape[-1] != 3:
        raise CoverageTestError("RadioMap cell center 배열과 값 배열이 일치하지 않습니다.")
    inside = np.zeros(values.shape, dtype=bool)
    for row in range(values.shape[0]):
        for column in range(values.shape[1]):
            inspection = room.inspect_point(centers[row, column], 0.0)
            inside[row, column] = inspection["inside_room"]
    finite = np.isfinite(values)
    positive = values > 0.0
    valid = inside & finite & positive
    inside_count = int(np.count_nonzero(inside))
    valid_count = int(np.count_nonzero(valid))
    valid_ratio = float(valid_count / inside_count) if inside_count else 0.0
    finite_values = values[valid]
    metadata = {
        "schema_version": "1.0",
        "status": settings["status"],
        "confidence": settings["confidence"],
        "physically_validated": settings["physically_validated"],
        "metric": "path_gain",
        "value_unit": "unitless_linear",
        "display_unit": "dB",
        "grid_shape_yx": list(values.shape),
        "cell_size_m": [cell_size, cell_size],
        "center_m": center,
        "size_m": size.tolist(),
        "z_height_m": float(coverage["z_height_m"]),
        "total_cell_count": int(values.size),
        "inside_cell_count": inside_count,
        "valid_cell_count": valid_count,
        "valid_ratio_of_inside": valid_ratio,
        "nan_count": int(np.count_nonzero(np.isnan(values))),
        "inf_count": int(np.count_nonzero(np.isinf(values))),
        "zero_or_negative_count": int(np.count_nonzero(values <= 0.0)),
        "value_min_linear": float(np.min(finite_values)) if valid_count else None,
        "value_mean_linear": float(np.mean(finite_values)) if valid_count else None,
        "value_max_linear": float(np.max(finite_values)) if valid_count else None,
        "value_min_db": float(10.0 * np.log10(np.min(finite_values))) if valid_count else None,
        "value_mean_db": float(np.mean(10.0 * np.log10(finite_values))) if valid_count else None,
        "value_max_db": float(10.0 * np.log10(np.max(finite_values))) if valid_count else None,
        "solver_options": {
            "samples_per_tx": int(coverage["samples_per_tx"]),
            "max_depth": int(coverage["max_depth"]),
            "los": coverage["enable_los"],
            "specular_reflection": coverage["enable_reflection"],
            "refraction": coverage["enable_refraction"],
            "diffraction": coverage["enable_diffraction"],
            "diffuse_reflection": coverage["enable_scattering"],
            "seed": int(coverage["seed"]),
        },
        "solve_time_seconds": elapsed,
    }
    success = bool(
        inside_count > 0
        and valid_ratio >= float(settings["validation"]["minimum_valid_coverage_ratio"])
        and (not settings["validation"]["require_finite_coverage_values"] or valid_count > 0)
    )
    metadata["success"] = success
    if not success:
        raise CoverageTestError("Coverage valid cell 비율 검증에 실패했습니다.")
    return {
        "radio_map": radio_map,
        "values": values,
        "centers": centers,
        "inside_mask": inside,
        "valid_mask": valid,
        "metadata": metadata,
    }
