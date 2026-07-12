"""Sionna PathSolver 실행과 LoS·정반사 경로 추출."""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from .io_utils import write_json


SPEED_OF_LIGHT_M_PER_S = 299792458.0


class PathTestError(RuntimeError):
    """Sionna 경로 계산 또는 결과 검증에 실패했을 때 발생한다."""


def _numpy(value):
    try:
        return np.asarray(value.numpy())
    except AttributeError:
        return np.asarray(value)


def _amplitude_arrays(paths):
    real, imag = paths.a
    real_array, imag_array = _numpy(real), _numpy(imag)
    if real_array.ndim == 5:
        real_array = real_array[:, 0, :, 0, :]
        imag_array = imag_array[:, 0, :, 0, :]
    return real_array, imag_array


def extract_path_records(
    arrays: Dict[str, np.ndarray],
    tx_names: List[str],
    rx_names: List[str],
    receiver_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    valid = np.asarray(arrays["valid"], dtype=bool)
    tau = np.asarray(arrays["tau"], dtype=float)
    interactions = np.asarray(arrays["interactions"], dtype=np.uint32)
    vertices = np.asarray(arrays["vertices"], dtype=float)
    objects = np.asarray(arrays.get("objects", np.zeros_like(interactions)), dtype=np.uint32)
    records = []
    for rx_index, rx_name in enumerate(rx_names):
        if receiver_filter is not None and rx_name != receiver_filter:
            continue
        for tx_index, tx_name in enumerate(tx_names):
            for path_index in range(valid.shape[-1]):
                if not valid[rx_index, tx_index, path_index]:
                    continue
                values = interactions[:, rx_index, tx_index, path_index] if interactions.shape[0] else np.empty(0, dtype=np.uint32)
                nonzero = np.flatnonzero(values != 0)
                interaction_types = values[nonzero].astype(int).tolist()
                if len(interaction_types) == 0:
                    path_type = "los"
                elif all(value == 1 for value in interaction_types):
                    path_type = "specular_reflection"
                else:
                    path_type = "mixed_or_other"
                interaction_points = []
                object_ids = []
                for depth in nonzero:
                    interaction_points.append(
                        vertices[depth, rx_index, tx_index, path_index].astype(float).tolist()
                    )
                    object_ids.append(int(objects[depth, rx_index, tx_index, path_index]))
                delay = float(tau[rx_index, tx_index, path_index])
                real = float(arrays["a_real"][rx_index, tx_index, path_index])
                imag = float(arrays["a_imag"][rx_index, tx_index, path_index])
                records.append(
                    {
                        "path_index": path_index,
                        "transmitter": tx_name,
                        "receiver": rx_name,
                        "path_type": path_type,
                        "interaction_count": len(interaction_types),
                        "interaction_types": interaction_types,
                        "interaction_object_ids": object_ids,
                        "interaction_points_m": interaction_points,
                        "delay_s": delay,
                        "distance_m": delay * SPEED_OF_LIGHT_M_PER_S,
                        "theta_t_rad": float(arrays["theta_t"][rx_index, tx_index, path_index]),
                        "phi_t_rad": float(arrays["phi_t"][rx_index, tx_index, path_index]),
                        "theta_r_rad": float(arrays["theta_r"][rx_index, tx_index, path_index]),
                        "phi_r_rad": float(arrays["phi_r"][rx_index, tx_index, path_index]),
                        "amplitude_real": real,
                        "amplitude_imag": imag,
                        "amplitude_magnitude": float(np.hypot(real, imag)),
                    }
                )
    return records


def arrays_from_paths(paths) -> Dict[str, np.ndarray]:
    real, imag = _amplitude_arrays(paths)
    interactions = _numpy(paths.interactions)
    vertices = _numpy(paths.vertices)
    objects = _numpy(paths.objects)
    return {
        "valid": _numpy(paths.valid),
        "tau": _numpy(paths.tau),
        "theta_t": _numpy(paths.theta_t),
        "phi_t": _numpy(paths.phi_t),
        "theta_r": _numpy(paths.theta_r),
        "phi_r": _numpy(paths.phi_r),
        "a_real": real,
        "a_imag": imag,
        "interactions": interactions,
        "vertices": vertices,
        "objects": objects,
    }


def validate_los_records(
    records: List[Dict[str, Any]],
    transmitter_position: np.ndarray,
    receiver_position: np.ndarray,
    minimum_count: int,
    tolerance_m: float,
) -> Dict[str, Any]:
    los = [value for value in records if value["path_type"] == "los"]
    euclidean = float(np.linalg.norm(np.asarray(receiver_position) - np.asarray(transmitter_position)))
    if los:
        nearest = min(los, key=lambda value: abs(value["distance_m"] - euclidean))
        sionna_distance = nearest["distance_m"]
        error = abs(sionna_distance - euclidean)
    else:
        nearest = None
        sionna_distance = None
        error = None
    success = bool(len(los) >= minimum_count and error is not None and error <= tolerance_m)
    return {
        "path_count": len(records),
        "los_path_count": len(los),
        "euclidean_distance_m": euclidean,
        "sionna_los_distance_m": sionna_distance,
        "distance_error_m": error,
        "matched_path_index": nearest["path_index"] if nearest else None,
        "success": success,
    }


def validate_reflection_records(records: List[Dict[str, Any]], max_depth: int) -> Dict[str, Any]:
    reflections = [value for value in records if value["path_type"] == "specular_reflection"]
    finite = all(
        np.isfinite(value["distance_m"])
        and np.isfinite(value["delay_s"])
        and np.isfinite(value["amplitude_magnitude"])
        for value in records
    )
    return {
        "path_count": len(records),
        "reflection_path_count": len(reflections),
        "maximum_interaction_count": max((value["interaction_count"] for value in records), default=0),
        "configured_max_depth": max_depth,
        "all_numeric_values_finite": finite,
        "status": "pass" if reflections and finite else ("warning" if finite else "failure"),
        "warning": None if reflections else "계산은 완료됐지만 정반사 경로를 찾지 못했습니다.",
    }


def _write_records_csv(path: Path, records: List[Dict[str, Any]]) -> None:
    fields = [
        "path_index",
        "transmitter",
        "receiver",
        "path_type",
        "interaction_count",
        "distance_m",
        "delay_s",
        "theta_t_rad",
        "phi_t_rad",
        "theta_r_rad",
        "phi_r_rad",
        "amplitude_real",
        "amplitude_imag",
        "amplitude_magnitude",
        "interaction_types",
        "interaction_object_ids",
        "interaction_points_m",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            row = dict(record)
            for key in ("interaction_types", "interaction_object_ids", "interaction_points_m"):
                row[key] = json.dumps(row[key], ensure_ascii=False)
            writer.writerow(row)


def run_path_tests(scene, settings: Dict[str, Any], positions: List[Dict[str, Any]], output: Path):
    from sionna.rt import PathSolver

    tx_names = list(scene.transmitters.keys())
    rx_names = list(scene.receivers.keys())
    tx_position = np.asarray(next(value["resolved_position_m"] for value in positions if value["kind"] == "transmitter"))
    rx_los_name = "rx_los" if "rx_los" in rx_names else rx_names[0]
    rx_reflection_name = "rx_reflection" if "rx_reflection" in rx_names else rx_names[-1]
    position_by_name = {value["name"]: np.asarray(value["resolved_position_m"]) for value in positions}
    solver = PathSolver()
    options = settings["path_test"]
    common = {
        "scene": scene,
        "samples_per_src": int(options["samples_per_src"]),
        "synthetic_array": bool(options["synthetic_array"]),
        "los": bool(options["enable_los"]),
        "specular_reflection": bool(options["enable_reflection"]),
        "diffuse_reflection": bool(options["enable_scattering"]),
        "refraction": bool(options["enable_refraction"]),
        "diffraction": bool(options["enable_diffraction"]),
        "edge_diffraction": False,
        "seed": int(options["seed"]),
    }
    start = time.perf_counter()
    los_paths = solver(max_depth=0, **common)
    los_time = time.perf_counter() - start
    los_records = extract_path_records(
        arrays_from_paths(los_paths), tx_names, rx_names, receiver_filter=rx_los_name
    )
    los_validation = validate_los_records(
        los_records,
        tx_position,
        position_by_name[rx_los_name],
        int(settings["validation"]["minimum_path_count_los_case"]),
        float(settings["validation"]["maximum_los_distance_error_m"]),
    )
    start = time.perf_counter()
    reflection_paths = solver(max_depth=int(options["max_depth"]), **common)
    reflection_time = time.perf_counter() - start
    reflection_records = extract_path_records(
        arrays_from_paths(reflection_paths), tx_names, rx_names, receiver_filter=rx_reflection_name
    )
    reflection_validation = validate_reflection_records(
        reflection_records, int(options["max_depth"])
    )
    path_directory = Path(output) / "paths"
    path_directory.mkdir(parents=True, exist_ok=True)
    los_document = {
        "schema_version": "1.0",
        "status": settings["status"],
        "receiver": rx_los_name,
        "solver_options": {**common, "scene": str(type(scene).__name__), "max_depth": 0},
        "validation": los_validation,
        "paths": los_records,
        "solve_time_seconds": los_time,
    }
    reflection_document = {
        "schema_version": "1.0",
        "status": settings["status"],
        "receiver": rx_reflection_name,
        "solver_options": {**common, "scene": str(type(scene).__name__), "max_depth": int(options["max_depth"])},
        "validation": reflection_validation,
        "paths": reflection_records,
        "solve_time_seconds": reflection_time,
    }
    write_json(path_directory / "paths_los.json", los_document)
    write_json(path_directory / "paths_reflection.json", reflection_document)
    _write_records_csv(path_directory / "paths_los.csv", los_records)
    _write_records_csv(path_directory / "paths_reflection.csv", reflection_records)
    if not los_validation["success"]:
        raise PathTestError("LoS path 거리 검증에 실패했습니다.")
    if reflection_validation["status"] == "failure":
        raise PathTestError("Reflection path 결과에 NaN 또는 Inf가 있습니다.")
    return {
        "los": los_document,
        "reflection": reflection_document,
        "paths_object_los": los_paths,
        "paths_object_reflection": reflection_paths,
    }
