"""Baseline repeat analysis and numerical-noise-floor estimation."""

from __future__ import annotations

from collections.abc import Mapping
from itertools import combinations
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .coverage_comparator import CoverageComparisonError, compare_coverage
from .path_comparator import (
    PathComparisonError,
    canonicalize_path_records,
    compare_paths,
)


class ReproducibilityError(ValueError):
    """Raised when repeat results are incomplete or are not comparable."""


_NUMERIC_SIGNATURE_NAMES = (
    "path_distance_m",
    "delay_s",
    "amplitude_magnitude",
    "path_gain_linear",
    "path_gain_db",
)
_PATH_NOISE_METRIC_NAMES = _NUMERIC_SIGNATURE_NAMES + (
    "interaction_point_displacement_m",
)


def compute_noise_statistics(deltas: Any) -> Dict[str, Any]:
    """Compute an absolute repeat-error summary from arbitrary-shaped deltas.

    The maximum absolute repeat delta is selected as the conservative noise
    floor.  The mean and 95th percentile are retained for diagnostics.
    """

    try:
        array = np.asarray(deltas, dtype=float).reshape(-1)
    except (TypeError, ValueError) as exc:
        raise ReproducibilityError("Repeat deltas must be numeric.") from exc
    finite = array[np.isfinite(array)]
    if finite.size == 0:
        return {
            "sample_count": 0,
            "mean_repeat_delta": None,
            "mean_absolute_repeat_delta": None,
            "maximum_absolute_repeat_delta": None,
            "percentile_95_absolute_repeat_delta": None,
            "noise_floor": 0.0,
            "noise_floor_method": "maximum_absolute_repeat_delta",
        }
    absolute = np.abs(finite)
    maximum = float(np.max(absolute))
    return {
        "sample_count": int(finite.size),
        "mean_repeat_delta": float(np.mean(finite)),
        "mean_absolute_repeat_delta": float(np.mean(absolute)),
        "maximum_absolute_repeat_delta": maximum,
        "percentile_95_absolute_repeat_delta": float(np.percentile(absolute, 95.0)),
        "noise_floor": maximum,
        "noise_floor_method": "maximum_absolute_repeat_delta",
    }


def compute_numerical_noise_floor(deltas: Any) -> Dict[str, Any]:
    """Alias for :func:`compute_noise_statistics`."""

    return compute_noise_statistics(deltas)


def _validate_tolerance(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ReproducibilityError("{} must be numeric.".format(name)) from exc
    if not np.isfinite(result) or result < 0.0:
        raise ReproducibilityError("{} must be finite and non-negative.".format(name))
    return result


def _delta_array(document: Mapping) -> np.ndarray:
    try:
        result = np.asarray(document["delta_db"], dtype=float)
    except (KeyError, TypeError, ValueError) as exc:
        raise ReproducibilityError("Coverage comparison did not contain a numeric delta map.") from exc
    return result[np.isfinite(result)]


def _compact_coverage_pair(document: Mapping, first: int, second: int) -> Dict[str, Any]:
    return {
        "repeat_indices": [int(first), int(second)],
        "common_valid_cell_count": document["common_valid_cell_count"],
        "grid_validation": document["grid_validation"],
        "valid_mask_validation": document["valid_mask_validation"],
        "mean_absolute_repeat_delta_db": document["mean_absolute_delta_db"],
        "maximum_absolute_repeat_delta_db": document["maximum_absolute_delta_db"],
        "percentile_95_repeat_delta_db": float(
            np.percentile(np.abs(_delta_array(document)), 95.0)
        ),
    }


def compare_coverage_repeats(
    repeats: Sequence[Any],
    *,
    coverage_unit: Optional[str] = None,
    require_common_grid: bool = True,
    require_common_valid_mask: bool = True,
    grid_tolerance: float = 1e-9,
    deterministic_tolerance_db: float = 0.0,
) -> Dict[str, Any]:
    """Compare every pair of repeated coverage runs and estimate dB noise."""

    values = list(repeats)
    if len(values) < 2:
        raise ReproducibilityError("At least two coverage repeats are required.")
    tolerance = _validate_tolerance(
        deterministic_tolerance_db, "deterministic coverage tolerance"
    )
    all_deltas = []
    pairs = []
    try:
        for first, second in combinations(range(len(values)), 2):
            comparison = compare_coverage(
                values[first],
                values[second],
                baseline_unit=coverage_unit,
                variant_unit=coverage_unit,
                require_common_grid=require_common_grid,
                require_common_valid_mask=require_common_valid_mask,
                grid_tolerance=grid_tolerance,
                noise_floor_db=0.0,
            )
            delta = _delta_array(comparison)
            all_deltas.append(delta)
            pairs.append(_compact_coverage_pair(comparison, first, second))
    except CoverageComparisonError as exc:
        raise ReproducibilityError("Coverage repeats are not comparable: {}".format(exc)) from exc
    combined = np.concatenate(all_deltas) if all_deltas else np.empty(0, dtype=float)
    noise = compute_noise_statistics(combined)
    maximum = noise["maximum_absolute_repeat_delta"]
    maximum = float(maximum) if maximum is not None else 0.0
    return {
        "repeat_count": len(values),
        "pair_count": len(pairs),
        "comparison_unit": "dB",
        "common_grid_required": bool(require_common_grid),
        "common_valid_mask_required": bool(require_common_valid_mask),
        "all_grids_match": all(pair["grid_validation"]["matches"] for pair in pairs),
        "all_valid_masks_match": all(
            pair["valid_mask_validation"]["matches"] for pair in pairs
        ),
        "sample_count": noise["sample_count"],
        "mean_absolute_repeat_delta_db": noise["mean_absolute_repeat_delta"],
        "maximum_absolute_repeat_delta_db": noise["maximum_absolute_repeat_delta"],
        "percentile_95_absolute_repeat_delta_db": noise[
            "percentile_95_absolute_repeat_delta"
        ],
        "percentile_95_repeat_delta_db": noise[
            "percentile_95_absolute_repeat_delta"
        ],
        "noise_floor_db": noise["noise_floor"],
        "noise_floor_method": noise["noise_floor_method"],
        "exactly_deterministic": bool(maximum == 0.0),
        "deterministic_tolerance_db": tolerance,
        "reproducible_within_tolerance": bool(maximum <= tolerance),
        "pairs": pairs,
    }


def _canonical_groups(documents: Sequence[Mapping]) -> Dict[Tuple[Any, ...], List[Mapping]]:
    groups = {}
    for value in documents:
        key = (
            value.get("transmitter"),
            value.get("receiver"),
            value.get("path_type"),
            tuple(value.get("ordered_interaction_object_ids", [])),
        )
        groups.setdefault(key, []).append(value)
    return groups


def _canonical_numeric_deltas(
    baseline: Any, variant: Any
) -> Tuple[Dict[str, List[float]], bool, bool]:
    baseline_groups = _canonical_groups(canonicalize_path_records(baseline))
    variant_groups = _canonical_groups(canonicalize_path_records(variant))
    deltas = {name: [] for name in _PATH_NOISE_METRIC_NAMES}
    structure_matches = set(baseline_groups) == set(variant_groups)
    numeric_availability_matches = True
    for key in set(baseline_groups) | set(variant_groups):
        left = baseline_groups.get(key, [])
        right = variant_groups.get(key, [])
        if len(left) != len(right):
            structure_matches = False
        for baseline_record, variant_record in zip(left, right):
            for index, name in enumerate(_NUMERIC_SIGNATURE_NAMES):
                baseline_value = baseline_record["numeric_signature"][index]
                variant_value = variant_record["numeric_signature"][index]
                if baseline_value is not None and variant_value is not None:
                    deltas[name].append(float(variant_value - baseline_value))
                elif (baseline_value is None) != (variant_value is None):
                    numeric_availability_matches = False
            baseline_points = np.asarray(
                baseline_record.get("interaction_points_m", []), dtype=float
            )
            variant_points = np.asarray(
                variant_record.get("interaction_points_m", []), dtype=float
            )
            if (
                baseline_points.shape == variant_points.shape
                and baseline_points.ndim == 2
                and baseline_points.shape[-1:] == (3,)
                and baseline_points.size
            ):
                displacement = np.linalg.norm(variant_points - baseline_points, axis=1)
                deltas["interaction_point_displacement_m"].extend(
                    displacement.tolist()
                )
            elif baseline_points.shape != variant_points.shape:
                numeric_availability_matches = False
    return deltas, structure_matches, numeric_availability_matches


def _path_tolerance(tolerances: Any, name: str) -> float:
    if tolerances is None:
        return 0.0
    if isinstance(tolerances, Mapping):
        value = tolerances.get(name, tolerances.get("default", 0.0))
    else:
        value = tolerances
    return _validate_tolerance(value, "{} path tolerance".format(name))


def compare_path_repeats(
    repeats: Sequence[Any],
    *,
    require_common_endpoints: bool = True,
    deterministic_tolerances: Any = None,
) -> Dict[str, Any]:
    """Compare repeated path sets using canonical structural matching.

    Paths are grouped by TX, RX, path type, and ordered interaction-object IDs.
    Numeric signatures only order duplicate paths within one such group; a
    solver's changing ``path_index`` or returned record order has no effect.
    """

    values = list(repeats)
    if len(values) < 2:
        raise ReproducibilityError("At least two path repeats are required.")
    aggregate_deltas = {name: [] for name in _PATH_NOISE_METRIC_NAMES}
    pairs = []
    structures_match = True
    numeric_availability_matches = True
    counts_match = True
    try:
        for first, second in combinations(range(len(values)), 2):
            comparison = compare_paths(
                values[first],
                values[second],
                require_common_endpoints=require_common_endpoints,
            )
            (
                numeric_deltas,
                pair_structures_match,
                pair_numeric_availability_matches,
            ) = _canonical_numeric_deltas(values[first], values[second])
            for name, deltas in numeric_deltas.items():
                aggregate_deltas[name].extend(deltas)
            count_delta = comparison["changes"]["total_path_count_delta"]
            pair_counts_match = count_delta == 0
            counts_match = counts_match and pair_counts_match
            structures_match = structures_match and pair_structures_match
            numeric_availability_matches = (
                numeric_availability_matches and pair_numeric_availability_matches
            )
            pairs.append(
                {
                    "repeat_indices": [first, second],
                    "path_counts_match": pair_counts_match,
                    "structures_match": pair_structures_match,
                    "numeric_availability_matches": pair_numeric_availability_matches,
                    "total_path_count_delta": count_delta,
                    "los_path_count_delta": comparison["changes"]["los_path_count_delta"],
                    "specular_reflection_path_count_delta": comparison["changes"][
                        "specular_reflection_path_count_delta"
                    ],
                    "matched_path_count": comparison["canonical_matching"][
                        "matched_path_count"
                    ],
                }
            )
    except PathComparisonError as exc:
        raise ReproducibilityError("Path repeats are not comparable: {}".format(exc)) from exc
    distributions = {}
    exact_numeric = True
    within_tolerance = True
    numerical_noise_floors = {}
    for name in _PATH_NOISE_METRIC_NAMES:
        noise = compute_noise_statistics(aggregate_deltas[name])
        tolerance = _path_tolerance(deterministic_tolerances, name)
        maximum = noise["maximum_absolute_repeat_delta"]
        maximum = float(maximum) if maximum is not None else 0.0
        exact_numeric = exact_numeric and maximum == 0.0
        within_tolerance = within_tolerance and maximum <= tolerance
        numerical_noise_floors[name] = noise["noise_floor"]
        distributions[name] = {
            **noise,
            "deterministic_tolerance": tolerance,
            "exactly_deterministic": bool(maximum == 0.0),
            "reproducible_within_tolerance": bool(maximum <= tolerance),
        }
    return {
        "repeat_count": len(values),
        "pair_count": len(pairs),
        "canonical_identity_fields": [
            "transmitter",
            "receiver",
            "path_type",
            "ordered_interaction_object_ids",
        ],
        "path_counts_match": counts_match,
        "path_structures_match": structures_match,
        "numeric_availability_matches": numeric_availability_matches,
        "distributions": distributions,
        "numerical_noise_floors": numerical_noise_floors,
        "exactly_deterministic": bool(
            counts_match
            and structures_match
            and numeric_availability_matches
            and exact_numeric
        ),
        "reproducible_within_tolerance": bool(
            counts_match
            and structures_match
            and numeric_availability_matches
            and within_tolerance
        ),
        "pairs": pairs,
    }


def _parts(run: Any) -> Tuple[Any, Any]:
    if isinstance(run, np.ndarray):
        return None, run
    if isinstance(run, (list, tuple)):
        # A list of records is a path result; a numeric nested list is coverage.
        if not run or isinstance(run[0], Mapping):
            return run, None
        return None, np.asarray(run)
    if not isinstance(run, Mapping):
        raise ReproducibilityError("Each repeat must be a result dictionary or array.")
    paths = None
    for key in ("paths", "path_records", "path_result", "path_results"):
        if run.get(key) is not None:
            paths = run[key]
            break
    coverage = None
    for key in ("coverage", "coverage_result", "radio_map"):
        if run.get(key) is not None:
            coverage = run[key]
            break
    if coverage is None and any(
        key in run for key in ("values", "coverage_values", "coverage_db", "path_gain")
    ):
        coverage = run
    if paths is None and coverage is None:
        # A direct path document commonly has only a top-level records key.
        if any(key in run for key in ("records", "los", "reflection")):
            paths = run
        else:
            raise ReproducibilityError("Repeat dictionary contains no path or coverage result.")
    return paths, coverage


def _collect_seed_values(
    value: Any, output: Dict[str, int], prefix: str = ""
) -> None:
    if not isinstance(value, Mapping):
        return
    for key, item in value.items():
        qualified = "{}.{}".format(prefix, key) if prefix else str(key)
        if "seed" in str(key).lower() and item is not None:
            try:
                output[qualified] = int(item)
            except (TypeError, ValueError):
                pass
        elif isinstance(item, Mapping):
            _collect_seed_values(item, output, qualified)


def analyze_reproducibility(
    repeats: Sequence[Any],
    *,
    coverage_unit: Optional[str] = None,
    require_common_grid: bool = True,
    require_common_valid_mask: bool = True,
    grid_tolerance: float = 1e-9,
    coverage_tolerance_db: float = 0.0,
    path_tolerances: Any = None,
    require_common_endpoints: bool = True,
) -> Dict[str, Any]:
    """Analyze complete baseline reruns and produce reusable noise floors."""

    runs = list(repeats)
    if len(runs) < 2:
        raise ReproducibilityError("At least two baseline repeats are required.")
    path_results, coverage_results = [], []
    seed_configurations = []
    for run in runs:
        paths, coverage = _parts(run)
        path_results.append(paths)
        coverage_results.append(coverage)
        seed_configuration = {}
        _collect_seed_values(run, seed_configuration)
        seed_configurations.append(seed_configuration)
    if any(value is None for value in path_results) and any(
        value is not None for value in path_results
    ):
        raise ReproducibilityError("Every repeat must include paths when one repeat includes them.")
    if any(value is None for value in coverage_results) and any(
        value is not None for value in coverage_results
    ):
        raise ReproducibilityError(
            "Every repeat must include coverage when one repeat includes it."
        )
    path_document = None
    if all(value is not None for value in path_results):
        path_document = compare_path_repeats(
            path_results,
            require_common_endpoints=require_common_endpoints,
            deterministic_tolerances=path_tolerances,
        )
    coverage_document = None
    if all(value is not None for value in coverage_results):
        coverage_document = compare_coverage_repeats(
            coverage_results,
            coverage_unit=coverage_unit,
            require_common_grid=require_common_grid,
            require_common_valid_mask=require_common_valid_mask,
            grid_tolerance=grid_tolerance,
            deterministic_tolerance_db=coverage_tolerance_db,
        )
    if path_document is None and coverage_document is None:
        raise ReproducibilityError("No reproducibility result was provided.")
    exact = all(
        document is None or document["exactly_deterministic"]
        for document in (path_document, coverage_document)
    )
    within = all(
        document is None or document["reproducible_within_tolerance"]
        for document in (path_document, coverage_document)
    )
    seed_metadata_available = any(seed_configurations)
    same_seed_configuration = all(
        configuration == seed_configurations[0]
        for configuration in seed_configurations[1:]
    )
    if seed_metadata_available and not same_seed_configuration:
        exact = False
        within = False
    return {
        "schema_version": "1.0",
        "repeat_count": len(runs),
        "seed_configurations": seed_configurations,
        "same_seed": same_seed_configuration if seed_metadata_available else None,
        "paths": path_document,
        "coverage": coverage_document,
        "noise_floor": {
            "coverage_db": coverage_document["noise_floor_db"]
            if coverage_document is not None
            else None,
            "paths": path_document["numerical_noise_floors"]
            if path_document is not None
            else None,
        },
        "exactly_deterministic": exact,
        "reproducible_within_tolerance": within,
        "status": "pass" if within else "warning",
    }


def compare_repeated_runs(repeats: Sequence[Any], **kwargs: Any) -> Dict[str, Any]:
    """Alias for :func:`analyze_reproducibility`."""

    return analyze_reproducibility(repeats, **kwargs)


def analyze_baseline_reproducibility(
    repeats: Sequence[Any], **kwargs: Any
) -> Dict[str, Any]:
    """Explicitly named alias used by A/B experiment runners."""

    return analyze_reproducibility(repeats, **kwargs)


__all__ = [
    "ReproducibilityError",
    "analyze_baseline_reproducibility",
    "analyze_reproducibility",
    "compare_coverage_repeats",
    "compare_path_repeats",
    "compare_repeated_runs",
    "compute_noise_statistics",
    "compute_numerical_noise_floor",
]
