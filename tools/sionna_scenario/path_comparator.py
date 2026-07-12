"""Sionna-independent path-record summaries and A/B comparisons."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np


class PathComparisonError(ValueError):
    """Raised when path results are malformed or describe different endpoints."""


_PATH_CONTAINER_KEYS = ("paths", "path_records", "records")
_DISTANCE_KEYS = ("distance_m", "path_distance_m", "distance")
_DELAY_KEYS = ("delay_s", "tau_s", "delay", "tau")
_AMPLITUDE_KEYS = ("amplitude_magnitude", "amplitude", "magnitude")
_PATH_GAIN_KEYS = ("path_gain", "gain_linear", "path_gain_linear")
_PATH_GAIN_DB_KEYS = ("path_gain_db", "gain_db")


def _json_scalar(value: Any) -> Any:
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        return value if np.isfinite(value) else None
    return str(value)


def _looks_like_path_record(value: Mapping) -> bool:
    keys = set(value.keys())
    return bool(
        keys.intersection(
            {
                "path_type",
                "interaction_count",
                "distance_m",
                "delay_s",
                "amplitude_magnitude",
                "interaction_object_ids",
            }
        )
    )


def _columnar_records(value: Mapping) -> Optional[List[Dict[str, Any]]]:
    recognized = set(
        _DISTANCE_KEYS
        + _DELAY_KEYS
        + _AMPLITUDE_KEYS
        + _PATH_GAIN_KEYS
        + _PATH_GAIN_DB_KEYS
        + (
            "path_type",
            "interaction_count",
            "interaction_object_ids",
            "interaction_types",
            "transmitter",
            "receiver",
        )
    )
    columns = {}
    length = None
    for key, item in value.items():
        if key not in recognized or isinstance(item, (str, bytes, Mapping)):
            continue
        array = np.asarray(item, dtype=object)
        if array.ndim == 0:
            continue
        if length is None:
            length = len(array)
        elif len(array) != length:
            raise PathComparisonError("Columnar path arrays must have equal lengths.")
        columns[key] = array
    if length is None or not columns:
        return None
    return [
        {key: _json_scalar(column[index]) for key, column in columns.items()}
        for index in range(length)
    ]


def normalize_path_records(value: Any) -> List[Dict[str, Any]]:
    """Normalize common list, document, structured-array, and columnar inputs."""

    if value is None:
        raise PathComparisonError("Path result is missing.")
    if isinstance(value, Mapping):
        for key in _PATH_CONTAINER_KEYS:
            if key in value:
                return normalize_path_records(value[key])
        # A runner may keep LoS and reflection documents separately.
        nested = []
        for key in ("los", "los_result", "reflection", "reflection_result"):
            if key in value and value[key] is not None:
                try:
                    nested.extend(normalize_path_records(value[key]))
                except PathComparisonError:
                    pass
        if nested:
            return nested
        if _looks_like_path_record(value):
            return [dict(value)]
        columnar = _columnar_records(value)
        if columnar is not None:
            return columnar
        raise PathComparisonError("Path dictionary does not contain path records.")
    if isinstance(value, np.ndarray) and value.dtype.names:
        return [
            {name: _json_scalar(row[name]) for name in value.dtype.names}
            for row in value
        ]
    if isinstance(value, np.ndarray):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        records = []
        for item in value:
            if isinstance(item, Mapping):
                records.append(dict(item))
            elif isinstance(item, np.void) and item.dtype.names:
                records.append(
                    {name: _json_scalar(item[name]) for name in item.dtype.names}
                )
            else:
                raise PathComparisonError("Each path record must be a dictionary-like value.")
        return records
    raise PathComparisonError("Unsupported path result type: {}.".format(type(value).__name__))


def _numeric(record: Mapping, keys: Sequence[str]) -> Optional[float]:
    for key in keys:
        if key not in record or record[key] is None:
            continue
        try:
            value = float(record[key])
        except (TypeError, ValueError):
            continue
        return value if np.isfinite(value) else None
    return None


def _amplitude(record: Mapping) -> Optional[float]:
    direct = _numeric(record, _AMPLITUDE_KEYS)
    if direct is not None:
        return abs(direct)
    real = _numeric(record, ("amplitude_real", "a_real", "real"))
    imag = _numeric(record, ("amplitude_imag", "a_imag", "imag"))
    if real is not None or imag is not None:
        return float(np.hypot(real or 0.0, imag or 0.0))
    return None


def _flatten_ids(value: Any) -> Iterable[Any]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        for key in ("object_id", "object", "id", "shape_id"):
            if key in value:
                return [_json_scalar(value[key])]
        flattened = []
        for item in value.values():
            flattened.extend(_flatten_ids(item))
        return flattened
    if isinstance(value, (list, tuple, set, np.ndarray)):
        flattened = []
        for item in value:
            flattened.extend(_flatten_ids(item))
        return flattened
    return [_json_scalar(value)]


def _interaction_ids(record: Mapping) -> List[Any]:
    for key in ("interaction_object_ids", "object_ids", "interaction_objects"):
        if key in record:
            return [value for value in _flatten_ids(record[key]) if value is not None]
    interactions = record.get("interactions")
    if interactions is not None:
        return [value for value in _flatten_ids(interactions) if value is not None]
    if record.get("interaction_object_names") is not None:
        return [
            value
            for value in _flatten_ids(record["interaction_object_names"])
            if value is not None
        ]
    return []


def _interaction_names(record: Mapping) -> List[str]:
    raw = record.get("interaction_object_names")
    if raw is None:
        return []
    return [str(value) for value in _flatten_ids(raw) if value is not None]


def _interaction_points(record: Mapping) -> np.ndarray:
    raw = None
    for key in ("interaction_points_m", "interaction_points", "vertices_m"):
        if record.get(key) is not None:
            raw = record[key]
            break
    if raw is None:
        return np.empty((0, 3), dtype=float)
    try:
        points = np.asarray(raw, dtype=float)
    except (TypeError, ValueError):
        return np.empty((0, 3), dtype=float)
    if points.size == 0:
        return np.empty((0, 3), dtype=float)
    if points.ndim == 1 and points.size == 3:
        points = points.reshape((1, 3))
    if points.ndim != 2 or points.shape[1] != 3 or not np.all(np.isfinite(points)):
        return np.empty((0, 3), dtype=float)
    return points


def _path_kind(record: Mapping) -> str:
    raw = str(record.get("path_type", record.get("type", ""))).strip().lower()
    normalized = raw.replace("-", "_").replace(" ", "_")
    if normalized in ("los", "line_of_sight", "direct"):
        return "los"
    if "reflection" in normalized or normalized in ("specular", "reflected"):
        return "specular_reflection"
    interaction_types = record.get("interaction_types")
    if interaction_types is not None:
        flattened = [value for value in _flatten_ids(interaction_types) if value is not None]
        if not flattened:
            return "los"
        try:
            if all(int(value) == 1 for value in flattened):
                return "specular_reflection"
        except (TypeError, ValueError):
            pass
    count = record.get("interaction_count")
    try:
        if count is not None and int(count) == 0:
            return "los"
    except (TypeError, ValueError):
        pass
    return normalized or "other"


def _interaction_count(record: Mapping) -> int:
    if record.get("interaction_count") is not None:
        try:
            count = int(record["interaction_count"])
            return max(count, 0)
        except (TypeError, ValueError):
            pass
    types = record.get("interaction_types")
    if types is not None:
        return len(list(_flatten_ids(types)))
    return len(_interaction_ids(record))


def _values(records: Sequence[Mapping], extractor: Callable[[Mapping], Optional[float]]) -> np.ndarray:
    result = [extractor(record) for record in records]
    return np.asarray([value for value in result if value is not None], dtype=float)


def summarize_distribution(values: Any) -> Dict[str, Any]:
    """Return finite distribution statistics using JSON-native scalar types."""

    array = np.asarray(values, dtype=float).reshape(-1)
    finite = array[np.isfinite(array)]
    if finite.size == 0:
        return {
            "count": int(array.size),
            "finite_count": 0,
            "minimum": None,
            "maximum": None,
            "mean": None,
            "median": None,
            "percentile_05": None,
            "percentile_25": None,
            "percentile_75": None,
            "percentile_95": None,
        }
    percentiles = np.percentile(finite, [5.0, 25.0, 75.0, 95.0])
    return {
        "count": int(array.size),
        "finite_count": int(finite.size),
        "minimum": float(np.min(finite)),
        "maximum": float(np.max(finite)),
        "mean": float(np.mean(finite)),
        "median": float(np.median(finite)),
        "percentile_05": float(percentiles[0]),
        "percentile_25": float(percentiles[1]),
        "percentile_75": float(percentiles[2]),
        "percentile_95": float(percentiles[3]),
    }


def _id_map(values: Iterable[Any]) -> Dict[str, Any]:
    result = {}
    for value in values:
        normalized = _json_scalar(value)
        if normalized is not None:
            result[str(normalized)] = normalized
    return result


def _endpoints(records: Sequence[Mapping]) -> Dict[str, List[str]]:
    transmitters = sorted(
        {str(record["transmitter"]) for record in records if record.get("transmitter") is not None}
    )
    receivers = sorted(
        {str(record["receiver"]) for record in records if record.get("receiver") is not None}
    )
    return {"transmitters": transmitters, "receivers": receivers}


def summarize_paths(paths: Any) -> Dict[str, Any]:
    """Summarize path counts, interactions, and numeric distributions."""

    records = normalize_path_records(paths)
    kinds = [_path_kind(record) for record in records]
    interaction_values = [value for record in records for value in _interaction_ids(record)]
    interaction_names = sorted(
        {value for record in records for value in _interaction_names(record)}
    )
    ids = _id_map(interaction_values)
    counts_by_type = {}
    for kind in kinds:
        counts_by_type[kind] = counts_by_type.get(kind, 0) + 1
    distances = _values(records, lambda record: _numeric(record, _DISTANCE_KEYS))
    delays = _values(records, lambda record: _numeric(record, _DELAY_KEYS))
    amplitudes = _values(records, _amplitude)
    path_gain = _values(records, lambda record: _numeric(record, _PATH_GAIN_KEYS))
    path_gain_db = _values(records, lambda record: _numeric(record, _PATH_GAIN_DB_KEYS))
    return {
        "total_path_count": len(records),
        "los_path_exists": "los" in kinds,
        "los_path_count": int(counts_by_type.get("los", 0)),
        "specular_reflection_path_count": int(counts_by_type.get("specular_reflection", 0)),
        "other_path_count": int(
            len(records)
            - counts_by_type.get("los", 0)
            - counts_by_type.get("specular_reflection", 0)
        ),
        "path_counts_by_type": counts_by_type,
        "maximum_interaction_count": max(
            (_interaction_count(record) for record in records), default=0
        ),
        "interaction_object_ids": [ids[key] for key in sorted(ids)],
        "interaction_object_id_count": len(ids),
        "interaction_object_names": interaction_names,
        "endpoints": _endpoints(records),
        "distributions": {
            "path_distance_m": summarize_distribution(distances),
            "delay_s": summarize_distribution(delays),
            "amplitude_magnitude": summarize_distribution(amplitudes),
            "path_gain_linear": summarize_distribution(path_gain),
            "path_gain_db": summarize_distribution(path_gain_db),
        },
    }


def _distribution_change(
    baseline: np.ndarray,
    variant: np.ndarray,
    matched_values: Optional[Sequence[Tuple[Optional[float], Optional[float]]]] = None,
) -> Dict[str, Any]:
    baseline_summary = summarize_distribution(baseline)
    variant_summary = summarize_distribution(variant)
    if baseline.size and variant.size:
        mean_delta = float(np.mean(variant) - np.mean(baseline))
        median_delta = float(np.median(variant) - np.median(baseline))
    else:
        mean_delta = None
        median_delta = None
    paired_delta = []
    if matched_values is not None:
        for baseline_value, variant_value in matched_values:
            if baseline_value is not None and variant_value is not None:
                paired_delta.append(float(variant_value - baseline_value))
    elif baseline.size == variant.size and baseline.size:
        # Used only by callers without records. Path comparisons provide
        # structure-aware pairs below and never depend on solver path order.
        paired_delta = (np.sort(variant) - np.sort(baseline)).tolist()
    if paired_delta:
        absolute = np.abs(np.asarray(paired_delta, dtype=float))
        sorted_statistics = {
            "matched_count": int(len(paired_delta)),
            "mean_absolute_delta": float(np.mean(absolute)),
            "maximum_absolute_delta": float(np.max(absolute)),
            "percentile_95_absolute_delta": float(np.percentile(absolute, 95.0)),
        }
    else:
        sorted_statistics = {
            "matched_count": 0,
            "mean_absolute_delta": None,
            "maximum_absolute_delta": None,
            "percentile_95_absolute_delta": None,
        }
    return {
        "baseline": baseline_summary,
        "variant": variant_summary,
        "mean_delta": mean_delta,
        "median_delta": median_delta,
        "equal_finite_value_count": bool(baseline.size == variant.size),
        "absolute_sorted_delta": sorted_statistics,
    }


def _structure_key(record: Mapping) -> Tuple[str, str, str, Tuple[str, ...]]:
    """Return a path-order-independent structural identity.

    Interaction object order is intentionally preserved because it describes
    the physical bounce sequence. ``path_index`` is intentionally ignored.
    """

    return (
        str(record.get("transmitter", "")),
        str(record.get("receiver", "")),
        _path_kind(record),
        tuple(str(value) for value in _interaction_ids(record)),
    )


def _numeric_signature(record: Mapping) -> Tuple[float, ...]:
    values = (
        _numeric(record, _DISTANCE_KEYS),
        _numeric(record, _DELAY_KEYS),
        _amplitude(record),
        _numeric(record, _PATH_GAIN_KEYS),
        _numeric(record, _PATH_GAIN_DB_KEYS),
    )
    return tuple(float(value) if value is not None else float("inf") for value in values)


def _sort_signature(record: Mapping) -> Tuple[float, ...]:
    points = _interaction_points(record)
    return _numeric_signature(record) + tuple(points.reshape(-1).tolist())


def _canonical_record_groups(records: Sequence[Mapping]) -> Dict[Tuple[Any, ...], List[Mapping]]:
    groups = {}
    for record in records:
        groups.setdefault(_structure_key(record), []).append(record)
    for values in groups.values():
        values.sort(key=_sort_signature)
    return groups


def _structure_document(key: Tuple[Any, ...], count: int) -> Dict[str, Any]:
    return {
        "transmitter": key[0] or None,
        "receiver": key[1] or None,
        "path_type": key[2],
        "ordered_interaction_object_ids": list(key[3]),
        "count": int(count),
    }


def _canonical_matches(
    baseline_records: Sequence[Mapping], variant_records: Sequence[Mapping]
) -> Dict[str, Any]:
    baseline_groups = _canonical_record_groups(baseline_records)
    variant_groups = _canonical_record_groups(variant_records)
    pairs = []
    unmatched_baseline = []
    unmatched_variant = []
    all_keys = sorted(set(baseline_groups) | set(variant_groups))
    for key in all_keys:
        baseline_group = baseline_groups.get(key, [])
        variant_group = variant_groups.get(key, [])
        matched_count = min(len(baseline_group), len(variant_group))
        pairs.extend(zip(baseline_group[:matched_count], variant_group[:matched_count]))
        if len(baseline_group) > matched_count:
            unmatched_baseline.append(
                _structure_document(key, len(baseline_group) - matched_count)
            )
        if len(variant_group) > matched_count:
            unmatched_variant.append(
                _structure_document(key, len(variant_group) - matched_count)
            )
    return {
        "pairs": pairs,
        "matched_path_count": len(pairs),
        "unmatched_baseline": unmatched_baseline,
        "unmatched_variant": unmatched_variant,
    }


def canonicalize_path_records(paths: Any) -> List[Dict[str, Any]]:
    """Return JSON-safe structural/numeric signatures in deterministic order."""

    records = normalize_path_records(paths)
    groups = _canonical_record_groups(records)
    result = []
    for key in sorted(groups):
        for record in groups[key]:
            signature = _numeric_signature(record)
            result.append(
                {
                    **_structure_document(key, 1),
                    "numeric_signature": [
                        value if np.isfinite(value) else None for value in signature
                    ],
                    "interaction_points_m": _interaction_points(record).tolist(),
                }
            )
    return result


def _floor_for(noise_floors: Any, key: str) -> float:
    if noise_floors is None:
        return 0.0
    value = noise_floors
    if isinstance(noise_floors, Mapping):
        if isinstance(noise_floors.get("numerical_noise_floors"), Mapping):
            noise_floors = noise_floors["numerical_noise_floors"]
        elif isinstance(noise_floors.get("paths"), Mapping):
            noise_floors = noise_floors["paths"]
        elif isinstance(noise_floors.get("noise_floor"), Mapping):
            nested = noise_floors["noise_floor"]
            if isinstance(nested.get("paths"), Mapping):
                noise_floors = nested["paths"]
        if isinstance(noise_floors.get("numerical_noise_floors"), Mapping):
            noise_floors = noise_floors["numerical_noise_floors"]
        value = noise_floors.get(
            key, noise_floors.get("default", noise_floors.get("noise_floor", 0.0))
        )
        if isinstance(value, Mapping):
            value = value.get("maximum_absolute_repeat_delta", value.get("noise_floor", 0.0))
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PathComparisonError("Path noise floor for {} is not numeric.".format(key)) from exc
    if not np.isfinite(result) or result < 0.0:
        raise PathComparisonError("Path noise floors must be finite and non-negative.")
    return result


def compare_paths(
    baseline: Any,
    variant: Any,
    *,
    obstacle_object_ids: Optional[Sequence[Any]] = None,
    require_common_endpoints: bool = True,
    numerical_noise_floors: Any = None,
) -> Dict[str, Any]:
    """Compare path sets and report explicit LoS/obstacle evidence.

    Numeric distributions are compared after sorting when their finite counts
    match.  This avoids relying on solver-specific path ordering while still
    exposing repeat noise for deterministic runs.
    """

    baseline_records = normalize_path_records(baseline)
    variant_records = normalize_path_records(variant)
    baseline_summary = summarize_paths(baseline_records)
    variant_summary = summarize_paths(variant_records)
    baseline_endpoints = baseline_summary["endpoints"]
    variant_endpoints = variant_summary["endpoints"]
    endpoints_match = baseline_endpoints == variant_endpoints
    endpoints_known = bool(
        baseline_endpoints["transmitters"]
        or baseline_endpoints["receivers"]
        or variant_endpoints["transmitters"]
        or variant_endpoints["receivers"]
    )
    if require_common_endpoints and endpoints_known and not endpoints_match:
        raise PathComparisonError("Baseline and variant TX/RX endpoint sets do not match.")

    extractors = {
        "path_distance_m": lambda record: _numeric(record, _DISTANCE_KEYS),
        "delay_s": lambda record: _numeric(record, _DELAY_KEYS),
        "amplitude_magnitude": _amplitude,
        "path_gain_linear": lambda record: _numeric(record, _PATH_GAIN_KEYS),
        "path_gain_db": lambda record: _numeric(record, _PATH_GAIN_DB_KEYS),
    }
    canonical = _canonical_matches(baseline_records, variant_records)
    distribution_changes = {}
    numeric_change_above_noise = False
    for key, extractor in extractors.items():
        matched_values = [
            (extractor(baseline_record), extractor(variant_record))
            for baseline_record, variant_record in canonical["pairs"]
        ]
        change = _distribution_change(
            _values(baseline_records, extractor),
            _values(variant_records, extractor),
            matched_values=matched_values,
        )
        floor = _floor_for(numerical_noise_floors, key)
        maximum = change["absolute_sorted_delta"]["maximum_absolute_delta"]
        availability_changed = not change["equal_finite_value_count"]
        change["noise_floor"] = floor
        change["numeric_availability_changed"] = availability_changed
        change["change_exceeds_noise_floor"] = bool(
            availability_changed or (maximum is not None and maximum > floor)
        )
        numeric_change_above_noise = numeric_change_above_noise or change[
            "change_exceeds_noise_floor"
        ]
        distribution_changes[key] = change

    baseline_ids = _id_map(baseline_summary["interaction_object_ids"])
    variant_ids = _id_map(variant_summary["interaction_object_ids"])
    added_keys = sorted(set(variant_ids) - set(baseline_ids))
    removed_keys = sorted(set(baseline_ids) - set(variant_ids))
    common_keys = sorted(set(baseline_ids) & set(variant_ids))
    obstacle_ids = _id_map(obstacle_object_ids or [])
    obstacle_keys = set(obstacle_ids)
    baseline_identifiers = _id_map(
        list(baseline_summary["interaction_object_ids"])
        + list(baseline_summary["interaction_object_names"])
    )
    variant_identifiers = _id_map(
        list(variant_summary["interaction_object_ids"])
        + list(variant_summary["interaction_object_names"])
    )
    variant_obstacle_keys = sorted(set(variant_identifiers) & obstacle_keys)
    baseline_obstacle_keys = sorted(set(baseline_identifiers) & obstacle_keys)
    variant_obstacle_path_count = sum(
        bool(
            set(_id_map(_interaction_ids(record) + _interaction_names(record)))
            & obstacle_keys
        )
        for record in variant_records
    )
    baseline_obstacle_path_count = sum(
        bool(
            set(_id_map(_interaction_ids(record) + _interaction_names(record)))
            & obstacle_keys
        )
        for record in baseline_records
    )

    los_changed = bool(
        baseline_summary["los_path_exists"] != variant_summary["los_path_exists"]
        or baseline_summary["los_path_count"] != variant_summary["los_path_count"]
    )
    count_changes = {
        "los_path_count_delta": int(
            variant_summary["los_path_count"] - baseline_summary["los_path_count"]
        ),
        "specular_reflection_path_count_delta": int(
            variant_summary["specular_reflection_path_count"]
            - baseline_summary["specular_reflection_path_count"]
        ),
        "total_path_count_delta": int(
            variant_summary["total_path_count"] - baseline_summary["total_path_count"]
        ),
        "maximum_interaction_count_delta": int(
            variant_summary["maximum_interaction_count"]
            - baseline_summary["maximum_interaction_count"]
        ),
    }
    obstacle_interaction_evidence = bool(variant_obstacle_keys)
    evidence_basis = []
    if los_changed:
        evidence_basis.append("los_presence_or_count_changed")
    if obstacle_interaction_evidence:
        evidence_basis.append("variant_path_interacts_with_requested_obstacle")
    blocker_related_change = bool(los_changed or obstacle_interaction_evidence)
    any_count_change = any(value != 0 for value in count_changes.values())
    structural_change = bool(
        canonical["unmatched_baseline"] or canonical["unmatched_variant"]
    )
    return {
        "schema_version": "1.0",
        "baseline": baseline_summary,
        "variant": variant_summary,
        "endpoint_validation": {
            "matches": endpoints_match,
            "required": bool(require_common_endpoints),
            "metadata_available": endpoints_known,
        },
        "changes": {
            "los_path_exists_changed": bool(
                baseline_summary["los_path_exists"] != variant_summary["los_path_exists"]
            ),
            **count_changes,
            "distribution_changes": distribution_changes,
            "added_interaction_object_ids": [variant_ids[key] for key in added_keys],
            "removed_interaction_object_ids": [baseline_ids[key] for key in removed_keys],
            "common_interaction_object_ids": [baseline_ids[key] for key in common_keys],
        },
        "canonical_matching": {
            "identity_fields": [
                "transmitter",
                "receiver",
                "path_type",
                "ordered_interaction_object_ids",
            ],
            "within_group_order": [
                "distance_m",
                "delay_s",
                "amplitude_magnitude",
                "path_gain_linear",
                "path_gain_db",
            ],
            "matched_path_count": canonical["matched_path_count"],
            "unmatched_baseline_path_count": int(
                sum(value["count"] for value in canonical["unmatched_baseline"])
            ),
            "unmatched_variant_path_count": int(
                sum(value["count"] for value in canonical["unmatched_variant"])
            ),
            "unmatched_baseline_structures": canonical["unmatched_baseline"],
            "unmatched_variant_structures": canonical["unmatched_variant"],
            "structure_changed": structural_change,
        },
        "obstacle_evidence": {
            "requested_obstacle_object_ids": [obstacle_ids[key] for key in sorted(obstacle_ids)],
            "baseline_interacting_obstacle_ids": [
                baseline_identifiers[key] for key in baseline_obstacle_keys
            ],
            "variant_interacting_obstacle_ids": [
                variant_identifiers[key] for key in variant_obstacle_keys
            ],
            "baseline_obstacle_interaction_path_count": int(baseline_obstacle_path_count),
            "variant_obstacle_interaction_path_count": int(variant_obstacle_path_count),
            "has_obstacle_interaction_evidence": obstacle_interaction_evidence,
            "los_change_evidence": los_changed,
            "blocker_related_change": blocker_related_change,
            "evidence_basis": evidence_basis,
        },
        "path_configuration_changed": bool(
            any_count_change
            or structural_change
            or added_keys
            or removed_keys
            or numeric_change_above_noise
        ),
        "change_exceeds_numerical_noise": bool(
            any_count_change
            or structural_change
            or added_keys
            or removed_keys
            or numeric_change_above_noise
        ),
    }


def compare_path_sets(baseline: Any, variant: Any, **kwargs: Any) -> Dict[str, Any]:
    """Alias for :func:`compare_paths`."""

    return compare_paths(baseline, variant, **kwargs)


__all__ = [
    "PathComparisonError",
    "canonicalize_path_records",
    "compare_path_sets",
    "compare_paths",
    "normalize_path_records",
    "summarize_distribution",
    "summarize_paths",
]
