"""Coverage map normalization and A/B comparison utilities.

The functions in this module deliberately do not depend on Sionna.  Solver
results can therefore be compared in the normal unit-test environment and can
be passed either as NumPy arrays or as small dictionaries produced by an
experiment runner.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict, Optional, Sequence, Tuple

import numpy as np


class CoverageComparisonError(ValueError):
    """Raised when two coverage maps cannot be compared safely."""


_VALUE_KEYS = (
    "values",
    "coverage_values",
    "coverage_db",
    "path_gain",
    "data",
)
_VALID_MASK_KEYS = ("valid_mask", "coverage_valid_mask", "is_valid")
_INSIDE_MASK_KEYS = ("inside_mask", "is_inside")
_GRID_KEYS = ("centers", "cell_centers", "grid", "grid_metadata")
_GRID_METADATA_KEYS = (
    "grid_shape_yx",
    "shape",
    "cell_size_m",
    "grid_origin_m",
    "origin_m",
    "center_m",
    "size_m",
    "z_height_m",
    "orientation",
    "x_m",
    "y_m",
)


def _first(mapping: Mapping, keys: Sequence[str]) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _unit_from_mapping(value: Mapping) -> Optional[str]:
    for key in ("unit", "value_unit", "coverage_unit", "display_unit"):
        if value.get(key) is not None:
            return str(value[key])
    metadata = value.get("metadata")
    if isinstance(metadata, Mapping):
        for key in ("unit", "value_unit", "coverage_unit", "display_unit"):
            if metadata.get(key) is not None:
                return str(metadata[key])
    return None


def _normalize_unit(unit: Optional[str]) -> str:
    if unit is None:
        return "db"
    normalized = str(unit).strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {
        "db",
        "decibel",
        "decibels",
        "path_gain_db",
        "power_db",
    }:
        return "db"
    if normalized in {
        "linear",
        "unitless_linear",
        "linear_path_gain",
        "path_gain",
        "power_linear",
    }:
        return "linear"
    raise CoverageComparisonError("Unsupported coverage unit: {!r}".format(unit))


def to_db(values: Any, unit: str = "db") -> np.ndarray:
    """Return floating-point dB values without double-converting dB input.

    Non-positive linear path-gain values cannot be represented in dB and are
    returned as ``NaN``.  They are excluded by :func:`compare_coverage` even if
    the caller's mask accidentally marks them as valid.
    """

    array = np.asarray(values)
    if np.iscomplexobj(array):
        raise CoverageComparisonError("Coverage values must be real numbers.")
    try:
        array = array.astype(float, copy=False)
    except (TypeError, ValueError) as exc:
        raise CoverageComparisonError("Coverage values must be numeric.") from exc
    if array.ndim == 0:
        raise CoverageComparisonError("Coverage values must be an array, not a scalar.")
    normalized = _normalize_unit(unit)
    if normalized == "db":
        return np.array(array, dtype=float, copy=True)
    result = np.full(array.shape, np.nan, dtype=float)
    usable = np.isfinite(array) & (array > 0.0)
    result[usable] = 10.0 * np.log10(array[usable])
    return result


def _extract_grid(mapping: Mapping) -> Any:
    direct = _first(mapping, _GRID_KEYS)
    if direct is not None:
        return direct
    metadata = mapping.get("metadata")
    candidates = {}
    for source in (mapping, metadata if isinstance(metadata, Mapping) else {}):
        for key in _GRID_METADATA_KEYS:
            if key in source and source[key] is not None:
                candidates[key] = source[key]
    return candidates or None


def _coverage_input(
    value: Any,
    unit: Optional[str],
    valid_mask: Any,
    inside_mask: Any,
    grid: Any,
) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        raw_values = _first(value, _VALUE_KEYS)
        if raw_values is None:
            raise CoverageComparisonError(
                "Coverage dictionary must contain one of: {}.".format(", ".join(_VALUE_KEYS))
            )
        if unit is None:
            unit = _unit_from_mapping(value)
        if valid_mask is None:
            valid_mask = _first(value, _VALID_MASK_KEYS)
        if inside_mask is None:
            inside_mask = _first(value, _INSIDE_MASK_KEYS)
        if grid is None:
            grid = _extract_grid(value)
    else:
        raw_values = value
    normalized_unit = _normalize_unit(unit)
    db_values = to_db(raw_values, normalized_unit)
    return {
        "values_db": db_values,
        "input_unit": normalized_unit,
        "valid_mask": valid_mask,
        "inside_mask": inside_mask,
        "grid": grid,
    }


def _as_mask(value: Any, shape: Tuple[int, ...], name: str) -> np.ndarray:
    if value is None:
        return np.ones(shape, dtype=bool)
    result = np.asarray(value)
    if result.shape != shape:
        raise CoverageComparisonError(
            "{} shape {} does not match coverage shape {}.".format(name, result.shape, shape)
        )
    if result.dtype.kind not in ("b", "i", "u"):
        raise CoverageComparisonError("{} must contain boolean values.".format(name))
    if result.dtype.kind != "b" and np.any((result != 0) & (result != 1)):
        raise CoverageComparisonError("{} may only contain 0/1 values.".format(name))
    return result.astype(bool, copy=False)


def _array_equal(left: Any, right: Any, atol: float) -> bool:
    try:
        left_array = np.asarray(left)
        right_array = np.asarray(right)
    except (TypeError, ValueError):
        return left == right
    if left_array.shape != right_array.shape:
        return False
    if left_array.dtype.kind in "biufc" and right_array.dtype.kind in "biufc":
        try:
            return bool(np.allclose(left_array, right_array, rtol=0.0, atol=atol, equal_nan=True))
        except TypeError:  # NumPy versions without equal_nan for an unusual dtype
            return bool(np.array_equal(left_array, right_array))
    return bool(np.array_equal(left_array, right_array))


def _compare_grid_mappings(left: Mapping, right: Mapping, atol: float) -> Tuple[bool, Sequence[str]]:
    keys = sorted(set(left.keys()) | set(right.keys()))
    checked = []
    for key in keys:
        if key not in left or key not in right:
            return False, keys
        checked.append(str(key))
        left_value, right_value = left[key], right[key]
        if isinstance(left_value, Mapping) and isinstance(right_value, Mapping):
            matches, _ = _compare_grid_mappings(left_value, right_value, atol)
        else:
            matches = _array_equal(left_value, right_value, atol)
        if not matches:
            return False, checked
    return True, checked


def validate_common_grid(
    baseline_grid: Any,
    variant_grid: Any,
    expected_shape: Optional[Tuple[int, ...]] = None,
    require_common_grid: bool = True,
    tolerance: float = 1e-9,
) -> Dict[str, Any]:
    """Validate grid coordinates/metadata and return a JSON-safe audit record.

    If neither input includes coordinate metadata, equal coverage array shapes
    are treated as an implicit common grid and the audit mode is ``shape_only``.
    Supplying metadata for just one side is considered a mismatch in strict
    mode because coordinates can no longer be proven equal.
    """

    if tolerance < 0.0 or not np.isfinite(tolerance):
        raise CoverageComparisonError("Grid tolerance must be finite and non-negative.")
    shape_json = list(expected_shape) if expected_shape is not None else None
    if baseline_grid is None and variant_grid is None:
        return {
            "matches": True,
            "required": bool(require_common_grid),
            "mode": "shape_only",
            "checked_fields": ["coverage_shape"],
            "coverage_shape": shape_json,
            "tolerance": float(tolerance),
        }
    if baseline_grid is None or variant_grid is None:
        matches, mode, checked = False, "metadata_missing", []
    elif isinstance(baseline_grid, Mapping) and isinstance(variant_grid, Mapping):
        matches, checked = _compare_grid_mappings(baseline_grid, variant_grid, tolerance)
        mode = "metadata"
    elif not isinstance(baseline_grid, Mapping) and not isinstance(variant_grid, Mapping):
        matches = _array_equal(baseline_grid, variant_grid, tolerance)
        checked = ["cell_centers"]
        mode = "cell_centers"
        if expected_shape is not None:
            for name, grid in (("baseline", baseline_grid), ("variant", variant_grid)):
                grid_shape = np.asarray(grid).shape
                if grid_shape[: len(expected_shape)] != expected_shape:
                    raise CoverageComparisonError(
                        "{} grid shape {} does not start with coverage shape {}.".format(
                            name, grid_shape, expected_shape
                        )
                    )
    else:
        matches, mode, checked = False, "incompatible_metadata_types", []
    document = {
        "matches": bool(matches),
        "required": bool(require_common_grid),
        "mode": mode,
        "checked_fields": list(checked),
        "coverage_shape": shape_json,
        "tolerance": float(tolerance),
    }
    if require_common_grid and not matches:
        raise CoverageComparisonError("Baseline and variant coverage grids do not match.")
    return document


def validate_common_valid_mask(
    baseline_mask: Any,
    variant_mask: Any,
    shape: Tuple[int, ...],
    require_common_valid_mask: bool = True,
) -> Dict[str, Any]:
    """Validate two masks, treating a missing mask as an all-valid mask."""

    baseline = _as_mask(baseline_mask, shape, "baseline valid mask")
    variant = _as_mask(variant_mask, shape, "variant valid mask")
    matches = bool(np.array_equal(baseline, variant))
    if require_common_valid_mask and not matches:
        raise CoverageComparisonError("Baseline and variant valid masks do not match.")
    return {
        "matches": matches,
        "required": bool(require_common_valid_mask),
        "baseline_valid_cell_count": int(np.count_nonzero(baseline)),
        "variant_valid_cell_count": int(np.count_nonzero(variant)),
        "mask_mismatch_cell_count": int(np.count_nonzero(baseline != variant)),
        "intersection_cell_count": int(np.count_nonzero(baseline & variant)),
    }


def _finite_float(value: Any) -> Optional[float]:
    result = float(value)
    return result if np.isfinite(result) else None


def _json_array(values: np.ndarray, valid: Optional[np.ndarray] = None) -> Any:
    values = np.asarray(values)
    if valid is None:
        valid = np.ones(values.shape, dtype=bool)
    valid = np.asarray(valid, dtype=bool)
    if values.ndim == 1:
        return [
            _finite_float(value) if is_valid and np.isfinite(value) else None
            for value, is_valid in zip(values, valid)
        ]
    return [_json_array(values[index], valid[index]) for index in range(values.shape[0])]


def _noise_floor_value(noise_floor: Any) -> float:
    if noise_floor is None:
        return 0.0
    if isinstance(noise_floor, Mapping):
        for key in (
            "noise_floor_db",
            "maximum_absolute_repeat_delta_db",
            "maximum_absolute_delta_db",
        ):
            if noise_floor.get(key) is not None:
                noise_floor = noise_floor[key]
                break
        else:
            coverage = noise_floor.get("coverage") or noise_floor.get("coverage_reproducibility")
            if isinstance(coverage, Mapping):
                return _noise_floor_value(coverage)
            nested = noise_floor.get("noise_floor")
            if isinstance(nested, Mapping) and nested.get("coverage_db") is not None:
                return _noise_floor_value(nested["coverage_db"])
            raise CoverageComparisonError("Noise-floor dictionary has no recognized dB value.")
    try:
        value = float(noise_floor)
    except (TypeError, ValueError) as exc:
        raise CoverageComparisonError("Noise floor must be a numeric dB value.") from exc
    if not np.isfinite(value) or value < 0.0:
        raise CoverageComparisonError("Noise floor must be finite and non-negative.")
    return value


def compare_coverage(
    baseline: Any,
    variant: Any,
    *,
    baseline_unit: Optional[str] = None,
    variant_unit: Optional[str] = None,
    baseline_valid_mask: Any = None,
    variant_valid_mask: Any = None,
    baseline_inside_mask: Any = None,
    variant_inside_mask: Any = None,
    baseline_grid: Any = None,
    variant_grid: Any = None,
    require_common_grid: bool = True,
    require_common_valid_mask: bool = True,
    grid_tolerance: float = 1e-9,
    changed_cell_threshold_db: float = 1.0,
    additional_thresholds_db: Sequence[float] = (3.0,),
    noise_floor_db: Any = 0.0,
) -> Dict[str, Any]:
    """Compare baseline and variant coverage maps in dB.

    Returned arrays contain ``None`` outside the common valid mask so the full
    document can be written with the standard :mod:`json` module without a
    custom NumPy encoder.
    """

    baseline_input = _coverage_input(
        baseline, baseline_unit, baseline_valid_mask, baseline_inside_mask, baseline_grid
    )
    variant_input = _coverage_input(
        variant, variant_unit, variant_valid_mask, variant_inside_mask, variant_grid
    )
    baseline_db = baseline_input["values_db"]
    variant_db = variant_input["values_db"]
    if baseline_db.shape != variant_db.shape:
        raise CoverageComparisonError(
            "Coverage shapes differ: {} versus {}.".format(baseline_db.shape, variant_db.shape)
        )
    shape = baseline_db.shape
    grid_validation = validate_common_grid(
        baseline_input["grid"],
        variant_input["grid"],
        expected_shape=shape,
        require_common_grid=require_common_grid,
        tolerance=grid_tolerance,
    )
    baseline_policy = _as_mask(baseline_input["valid_mask"], shape, "baseline valid mask")
    variant_policy = _as_mask(variant_input["valid_mask"], shape, "variant valid mask")
    baseline_inside = _as_mask(baseline_input["inside_mask"], shape, "baseline inside mask")
    variant_inside = _as_mask(variant_input["inside_mask"], shape, "variant inside mask")
    baseline_effective = baseline_policy & baseline_inside & np.isfinite(baseline_db)
    variant_effective = variant_policy & variant_inside & np.isfinite(variant_db)
    mask_validation = validate_common_valid_mask(
        baseline_effective,
        variant_effective,
        shape,
        require_common_valid_mask=require_common_valid_mask,
    )
    common_valid = baseline_effective & variant_effective
    common_count = int(np.count_nonzero(common_valid))
    if common_count == 0:
        raise CoverageComparisonError("Coverage maps have no common finite valid cells.")
    deltas = variant_db[common_valid] - baseline_db[common_valid]
    if not np.all(np.isfinite(deltas)):
        raise CoverageComparisonError("Coverage delta contains a non-finite common-valid value.")
    threshold = float(changed_cell_threshold_db)
    if not np.isfinite(threshold) or threshold < 0.0:
        raise CoverageComparisonError("Changed-cell threshold must be finite and non-negative.")
    thresholds = [1.0, 3.0, threshold]
    thresholds.extend(float(value) for value in additional_thresholds_db)
    if any(not np.isfinite(value) or value < 0.0 for value in thresholds):
        raise CoverageComparisonError("All coverage thresholds must be finite and non-negative.")
    thresholds = sorted(set(thresholds))
    threshold_counts = {
        "abs_delta_gt_{:g}_db_cell_count".format(value): int(
            np.count_nonzero(np.abs(deltas) > value)
        )
        for value in thresholds
    }
    noise = _noise_floor_value(noise_floor_db)
    significance_threshold = max(noise, threshold)
    delta_grid = np.full(shape, np.nan, dtype=float)
    delta_grid[common_valid] = variant_db[common_valid] - baseline_db[common_valid]
    percentiles = np.percentile(deltas, [5.0, 25.0, 75.0, 95.0])
    mean_absolute = float(np.mean(np.abs(deltas)))
    maximum_absolute = float(np.max(np.abs(deltas)))
    statistics = {
        "mean_delta_db": float(np.mean(deltas)),
        "mean_absolute_delta_db": mean_absolute,
        "median_delta_db": float(np.median(deltas)),
        "minimum_delta_db": float(np.min(deltas)),
        "maximum_delta_db": float(np.max(deltas)),
        "maximum_absolute_delta_db": maximum_absolute,
        "percentile_05_delta_db": float(percentiles[0]),
        "percentile_25_delta_db": float(percentiles[1]),
        "percentile_75_delta_db": float(percentiles[2]),
        "percentile_95_delta_db": float(percentiles[3]),
        "positive_delta_cell_count": int(np.count_nonzero(deltas > 0.0)),
        "negative_delta_cell_count": int(np.count_nonzero(deltas < 0.0)),
        "zero_delta_cell_count": int(np.count_nonzero(deltas == 0.0)),
        **threshold_counts,
    }
    result = {
        "schema_version": "1.0",
        "comparison_unit": "dB",
        "delta_definition": "variant_db - baseline_db",
        "baseline_input_unit": baseline_input["input_unit"],
        "variant_input_unit": variant_input["input_unit"],
        "grid_shape": list(shape),
        "total_cell_count": int(baseline_db.size),
        "common_valid_cell_count": common_count,
        "grid_validation": grid_validation,
        "valid_mask_validation": mask_validation,
        "statistics": statistics,
        # Frequently consumed fields are also available at the document root.
        **statistics,
        "noise_floor_db": noise,
        "changed_cell_threshold_db": threshold,
        "significance_threshold_db": significance_threshold,
        "abs_delta_above_noise_floor_cell_count": int(
            np.count_nonzero(np.abs(deltas) > noise)
        ),
        "meaningful_changed_cell_count": int(
            np.count_nonzero(np.abs(deltas) > significance_threshold)
        ),
        "ab_change_exceeds_noise_floor": bool(maximum_absolute > noise),
        "baseline_db": _json_array(baseline_db, baseline_effective),
        "variant_db": _json_array(variant_db, variant_effective),
        "delta_db": _json_array(delta_grid, common_valid),
        "baseline_valid_mask": baseline_effective.tolist(),
        "variant_valid_mask": variant_effective.tolist(),
        "common_valid_mask": common_valid.tolist(),
    }
    return result


def compare_coverage_maps(baseline: Any, variant: Any, **kwargs: Any) -> Dict[str, Any]:
    """Backward-friendly alias for :func:`compare_coverage`."""

    return compare_coverage(baseline, variant, **kwargs)


__all__ = [
    "CoverageComparisonError",
    "compare_coverage",
    "compare_coverage_maps",
    "to_db",
    "validate_common_grid",
    "validate_common_valid_mask",
]
