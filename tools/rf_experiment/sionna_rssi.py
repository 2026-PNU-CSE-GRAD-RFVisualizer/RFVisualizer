"""Metric Proxy Scene에서 지점·평면 Sionna RSSI(dBm)를 내보낸다."""

from __future__ import annotations

import hashlib
import math
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from tools.sionna_smoke_test.coverage_test import run_coverage_solver
from tools.sionna_smoke_test.environment import diagnose_environment
from tools.sionna_smoke_test.io_utils import SmokeTestIOError, write_csv, write_json
from tools.sionna_smoke_test.main import configure_sionna_scene
from tools.sionna_smoke_test.metric_scene_loader import load_metric_scene
from tools.sionna_smoke_test.path_test import arrays_from_paths
from tools.sionna_smoke_test.placement import RoomContainment
from tools.sionna_smoke_test.scene_exporter import export_scene

from .contracts import (
    load_json,
    resolve_path,
    validate_marker_document,
    validate_scene_document,
)


class SionnaRssiError(RuntimeError):
    """Sionna RSSI 입력·계산·출력이 실험 계약을 만족하지 않을 때 발생한다."""


def path_gain_to_rssi_dbm(path_gain_linear: Any, tx_power_dbm: float) -> np.ndarray:
    """무차원 선형 path gain을 송신 출력 기준 RSSI dBm으로 변환한다."""

    gain = np.asarray(path_gain_linear, dtype=float)
    power = float(tx_power_dbm)
    if not math.isfinite(power):
        raise SionnaRssiError("TX 출력은 유한한 dBm 값이어야 합니다.")
    if not np.all(np.isfinite(gain)) or np.any(gain <= 0.0):
        raise SionnaRssiError("RSSI로 변환할 path gain은 유한한 양수여야 합니다.")
    return power + 10.0 * np.log10(gain)


def aggregate_path_gain(
    valid: Any, amplitude_real: Any, amplitude_imag: Any
) -> Tuple[np.ndarray, np.ndarray]:
    """RadioMap path_gain과 같은 기준으로 유효 경로의 |a|²를 합산한다."""

    mask = np.asarray(valid, dtype=bool)
    real = np.asarray(amplitude_real, dtype=float)
    imag = np.asarray(amplitude_imag, dtype=float)
    if mask.ndim != 3 or real.shape != mask.shape or imag.shape != mask.shape:
        raise SionnaRssiError(
            "Path 배열은 [receiver, transmitter, path]의 같은 모양이어야 합니다."
        )
    if not np.all(np.isfinite(real[mask])) or not np.all(np.isfinite(imag[mask])):
        raise SionnaRssiError("유효 경로 진폭에 NaN 또는 Inf가 있습니다.")
    squared = np.where(mask, np.square(real) + np.square(imag), 0.0)
    return np.sum(squared, axis=-1), np.count_nonzero(mask, axis=-1)


def _finite(value: Any, field: str, positive: bool = False, allow_zero: bool = False) -> float:
    if isinstance(value, bool):
        raise SionnaRssiError("{}는 숫자여야 합니다.".format(field))
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SionnaRssiError("{}는 숫자여야 합니다.".format(field)) from exc
    if not math.isfinite(number):
        raise SionnaRssiError("{}는 유한한 숫자여야 합니다.".format(field))
    if positive and number < (0.0 if allow_zero else np.nextafter(0.0, 1.0)):
        relation = "0 이상" if allow_zero else "0보다 큰"
        raise SionnaRssiError("{}는 {} 값이어야 합니다.".format(field, relation))
    return number


def _integer(value: Any, field: str, minimum: int = 0) -> int:
    number = _finite(value, field)
    integer = int(number)
    if float(integer) != number or integer < minimum:
        raise SionnaRssiError("{}는 {} 이상의 정수여야 합니다.".format(field, minimum))
    return integer


def validate_solver_document(document: Mapping[str, Any]) -> Dict[str, Any]:
    if document.get("schema_version") != "1.0":
        raise SionnaRssiError("Sionna solver schema_version은 1.0이어야 합니다.")
    config = document.get("sionna_rssi")
    if not isinstance(config, Mapping):
        raise SionnaRssiError("sionna_rssi 설정이 필요합니다.")
    if config.get("status") != "provisional":
        raise SionnaRssiError("실측 검증 전 Sionna 상태는 provisional이어야 합니다.")
    config_id = str(config.get("id", "")).strip()
    if not config_id:
        raise SionnaRssiError("sionna_rssi.id가 비어 있습니다.")
    scene_source = config.get("scene_source")
    if (
        not isinstance(scene_source, Mapping)
        or scene_source.get("default_mode") != "metric_proxy_export"
    ):
        raise SionnaRssiError(
            "scene_source.default_mode는 metric_proxy_export여야 합니다."
        )
    runtime = config.get("runtime")
    if not isinstance(runtime, Mapping):
        raise SionnaRssiError("runtime 버전 설정이 필요합니다.")
    for field in (
        "required_sionna_rt_version",
        "required_mitsuba_version",
        "required_drjit_version",
    ):
        if not str(runtime.get(field, "")).strip():
            raise SionnaRssiError("runtime.{}이 비어 있습니다.".format(field))
    materials = config.get("materials")
    if not isinstance(materials, Mapping):
        raise SionnaRssiError("Sionna materials 설정이 필요합니다.")
    for semantic in ("floor", "ceiling", "walls"):
        value = materials.get(semantic)
        if not isinstance(value, Mapping) or not str(value.get("preset", "")).strip():
            raise SionnaRssiError("materials.{}.preset이 비어 있습니다.".format(semantic))
        # scattering_coefficient가 0이면 enable_scattering을 켜도 확산 경로가 생기지 않는다.
        for key in ("scattering_coefficient", "xpd_coefficient"):
            if key in value and not 0.0 <= float(value[key]) <= 1.0:
                raise SionnaRssiError(
                    "materials.{}.{}는 0과 1 사이여야 합니다.".format(semantic, key))
    antenna = config.get("antenna")
    if not isinstance(antenna, Mapping):
        raise SionnaRssiError("antenna 설정이 필요합니다.")
    for field in ("pattern", "polarization"):
        if not str(antenna.get(field, "")).strip():
            raise SionnaRssiError("antenna.{}가 비어 있습니다.".format(field))
    booleans = (
        "enable_los",
        "enable_reflection",
        "enable_refraction",
        "enable_diffraction",
        "enable_scattering",
    )
    path = config.get("path_solver")
    radio = config.get("radio_map")
    if not isinstance(path, Mapping) or not isinstance(radio, Mapping):
        raise SionnaRssiError("path_solver와 radio_map 설정이 필요합니다.")
    _integer(path.get("max_depth"), "path_solver.max_depth", 0)
    _integer(path.get("samples_per_src"), "path_solver.samples_per_src", 1)
    _integer(path.get("seed"), "path_solver.seed", 0)
    if not isinstance(path.get("synthetic_array"), bool):
        raise SionnaRssiError("path_solver.synthetic_array는 true/false여야 합니다.")
    for field in booleans:
        if not isinstance(path.get(field), bool) or not isinstance(radio.get(field), bool):
            raise SionnaRssiError("{}는 path_solver와 radio_map에서 true/false여야 합니다.".format(field))
    _finite(radio.get("z_height_m"), "radio_map.z_height_m")
    _finite(radio.get("margin_m"), "radio_map.margin_m", positive=True, allow_zero=True)
    _finite(radio.get("cell_size_m"), "radio_map.cell_size_m", positive=True)
    _integer(radio.get("max_cells"), "radio_map.max_cells", 1)
    _integer(radio.get("samples_per_tx"), "radio_map.samples_per_tx", 1)
    _integer(radio.get("seed"), "radio_map.seed", 0)
    _integer(radio.get("max_depth"), "radio_map.max_depth", 0)
    validation = config.get("validation")
    if not isinstance(validation, Mapping):
        raise SionnaRssiError("validation 설정이 필요합니다.")
    _finite(
        validation.get("device_clearance_m"),
        "validation.device_clearance_m",
        positive=True,
        allow_zero=True,
    )
    ratio = _finite(
        validation.get("minimum_valid_grid_ratio"),
        "validation.minimum_valid_grid_ratio",
        positive=True,
    )
    if ratio > 1.0:
        raise SionnaRssiError("minimum_valid_grid_ratio는 1 이하여야 합니다.")
    _integer(
        validation.get("minimum_valid_grid_points"),
        "validation.minimum_valid_grid_points",
        3,
    )
    _finite(
        validation.get("rss_consistency_tolerance_db"),
        "validation.rss_consistency_tolerance_db",
        positive=True,
        allow_zero=True,
    )
    return {
        "success": True,
        "config_id": config_id,
        "status": config["status"],
        "required_runtime": dict(runtime),
    }


def _sha256(path: Path) -> str:
    # hashlib.file_digest는 Python 3.11+이고 sionna 환경은 3.10이라 직접 읽는다.
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_csv(path: Path, fields: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
    try:
        write_csv(path, fields, rows)
    except SmokeTestIOError as exc:
        raise SionnaRssiError("Sionna CSV를 저장할 수 없습니다: {}".format(exc)) from exc


def _safe_name(value: str, used: set) -> str:
    normalized = "".join(character if character.isalnum() else "_" for character in value)
    normalized = normalized.strip("_") or "device"
    if normalized[0].isdigit():
        normalized = "device_" + normalized
    candidate = normalized
    index = 2
    while candidate in used:
        candidate = "{}_{}".format(normalized, index)
        index += 1
    used.add(candidate)
    return candidate


def _metric_settings(
    scene_document: Mapping[str, Any],
    solver_document: Mapping[str, Any],
    transmitter: Mapping[str, Any],
) -> Dict[str, Any]:
    scene = scene_document["scene"]
    proxy = scene["proxy_scene"]
    config = solver_document["sionna_rssi"]
    metric_obj = resolve_path(proxy["metric_obj"])
    return {
        "status": "provisional",
        "confidence": "low",
        "physically_validated": False,
        "input": {
            "metric_obj": str(metric_obj),
            "metric_mtl": str(metric_obj.with_suffix(".mtl")),
            "metric_json": str(resolve_path(proxy["metric_json"])),
            "calibration_json": str(resolve_path(proxy["calibration_json"])),
        },
        "scene": {
            "name": scene["id"],
            "carrier_frequency_hz": float(transmitter["frequency_hz"]),
            "coordinate_system": {"up_axis": "+Z", "units": "meters"},
        },
        "materials": config["materials"],
        "transmitter": {
            "name": "placeholder_replaced_by_marker",
            "position_m": transmitter["position_m"],
            "power_dbm": float(transmitter["power_dbm"]),
        },
        "antenna": config["antenna"],
        "path_test": {
            **config["path_solver"],
            "max_depth": int(config["path_solver"]["max_depth"]),
            "samples_per_src": int(config["path_solver"]["samples_per_src"]),
            "seed": int(config["path_solver"]["seed"]),
        },
        "coverage": {
            "enabled": True,
            **config["radio_map"],
        },
        "validation": {
            "require_finite_coverage_values": True,
            "minimum_valid_coverage_ratio": float(
                config["validation"]["minimum_valid_grid_ratio"]
            ),
        },
    }


def _device_positions(
    marker_document: Mapping[str, Any], room: RoomContainment, clearance_m: float
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    transmitters = marker_document["tx"]
    receivers = marker_document["rx"]
    if len(transmitters) != 1:
        raise SionnaRssiError("현재 논문 실험 Sionna 실행은 TX 정확히 1개를 요구합니다.")
    if not receivers:
        raise SionnaRssiError("Sionna 지점 예측에는 RX가 하나 이상 필요합니다.")
    used = set()
    positions = []
    point_metadata = []
    tx = transmitters[0]
    tx_name = _safe_name(str(tx["id"]), used)
    position = np.asarray(tx["position_m"], dtype=float)
    inspection = room.inspect_point(position, clearance_m)
    if not inspection["safe_with_clearance"]:
        raise SionnaRssiError("TX '{}'가 Room 안전 범위 안에 있지 않습니다.".format(tx["id"]))
    positions.append(
        {
            "kind": "transmitter",
            "name": tx_name,
            "requested_position_m": position.tolist(),
            "resolved_position_m": position.tolist(),
            "used_fallback": False,
            "validation": inspection,
        }
    )
    for receiver in receivers:
        rx_name = _safe_name(str(receiver["id"]), used)
        position = np.asarray(receiver["position_m"], dtype=float)
        inspection = room.inspect_point(position, clearance_m)
        if not inspection["safe_with_clearance"]:
            raise SionnaRssiError(
                "RX '{}'가 Room 안전 범위 안에 있지 않습니다.".format(receiver["id"])
            )
        positions.append(
            {
                "kind": "receiver",
                "name": rx_name,
                "requested_position_m": position.tolist(),
                "resolved_position_m": position.tolist(),
                "used_fallback": False,
                "validation": inspection,
            }
        )
        point_metadata.append(
            {
                "sionna_name": rx_name,
                "marker_id": receiver["id"],
                "point_id": receiver["point_id"],
                "point_role": receiver["role"],
                "position_m": position.tolist(),
            }
        )
    return positions, point_metadata


def _solve_points(
    scene: Any,
    settings: Mapping[str, Any],
    point_metadata: Sequence[Mapping[str, Any]],
    tx_power_dbm: float,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    from sionna.rt import PathSolver

    options = settings["path_test"]
    started = time.perf_counter()
    paths = PathSolver()(
        scene=scene,
        max_depth=int(options["max_depth"]),
        samples_per_src=int(options["samples_per_src"]),
        # 후보 경로가 이 한도를 넘으면 잘려나가고, 약한 RX의 경로가 통째로 사라진다.
        # samples_per_src를 올릴 때 함께 올려야 한다.
        max_num_paths_per_src=int(options.get("max_num_paths_per_src", 1000000)),
        synthetic_array=bool(options["synthetic_array"]),
        los=bool(options["enable_los"]),
        specular_reflection=bool(options["enable_reflection"]),
        diffuse_reflection=bool(options["enable_scattering"]),
        refraction=bool(options["enable_refraction"]),
        diffraction=bool(options["enable_diffraction"]),
        edge_diffraction=False,
        seed=int(options["seed"]),
    )
    elapsed = time.perf_counter() - started
    arrays = arrays_from_paths(paths)
    gains, counts = aggregate_path_gain(
        arrays["valid"], arrays["a_real"], arrays["a_imag"]
    )
    if gains.shape != (len(point_metadata), 1):
        raise SionnaRssiError(
            "지점 path gain 배열 모양이 예상과 다릅니다: {}".format(gains.shape)
        )
    values = gains[:, 0]
    if np.any(values <= 0.0) or not np.all(np.isfinite(values)):
        invalid = [
            point_metadata[index]["point_id"]
            for index, value in enumerate(values)
            if not math.isfinite(float(value)) or value <= 0.0
        ]
        raise SionnaRssiError("유효 경로 이득이 없는 RX가 있습니다: {}".format(invalid))
    rssi = path_gain_to_rssi_dbm(values, tx_power_dbm)
    rows = []
    for index, metadata in enumerate(point_metadata):
        x, y, z = metadata["position_m"]
        rows.append(
            {
                "point_id": metadata["point_id"],
                "x": x,
                "y": y,
                "z": z,
                "sionna_rssi_dbm": float(rssi[index]),
                "point_role": metadata["point_role"],
                "marker_id": metadata["marker_id"],
                "path_gain_linear": float(values[index]),
                "valid_path_count": int(counts[index, 0]),
            }
        )
    return rows, {
        "solve_time_seconds": elapsed,
        "receiver_count": len(rows),
        "aggregation": "sum_abs_squared_complex_path_amplitudes",
        "gain_unit": "unitless_linear",
        "minimum_valid_path_count": int(np.min(counts[:, 0])),
        "maximum_valid_path_count": int(np.max(counts[:, 0])),
    }


def _radio_map_rows(
    coverage: Mapping[str, Any], tx_power_dbm: float, tolerance_db: float
) -> Tuple[List[Dict[str, Any]], np.ndarray, Dict[str, Any]]:
    values = np.asarray(coverage["values"], dtype=float)
    centers = np.asarray(coverage["centers"], dtype=float)
    valid = np.asarray(coverage["valid_mask"], dtype=bool)
    if int(np.count_nonzero(valid)) == 0:
        raise SionnaRssiError("Radio Map에 유효한 Grid 점이 없습니다.")
    rssi = np.full(values.shape, np.nan, dtype=float)
    rssi[valid] = path_gain_to_rssi_dbm(values[valid], tx_power_dbm)
    radio_map = coverage["radio_map"]
    consistency = {
        "radio_map_rss_property_available": hasattr(radio_map, "rss"),
        "formula": "tx_power_dbm + 10*log10(path_gain_linear)",
        "rss_property_unit": "W",
        "maximum_absolute_difference_db": None,
        "tolerance_db": tolerance_db,
        "success": False,
    }
    if not consistency["radio_map_rss_property_available"]:
        raise SionnaRssiError("설치된 Sionna RadioMap에 rss 속성이 없습니다.")
    try:
        rss_w = np.asarray(radio_map.rss.numpy(), dtype=float)
    except AttributeError:
        rss_w = np.asarray(radio_map.rss, dtype=float)
    if rss_w.ndim != 3 or rss_w.shape[0] != 1 or rss_w.shape[1:] != values.shape:
        raise SionnaRssiError("RadioMap rss 배열 모양이 예상과 다릅니다: {}".format(rss_w.shape))
    rss_property_dbm = np.full(values.shape, np.nan, dtype=float)
    property_valid = valid & np.isfinite(rss_w[0]) & (rss_w[0] > 0.0)
    if not np.any(property_valid):
        raise SionnaRssiError("RadioMap rss 속성에 비교 가능한 양수 값이 없습니다.")
    rss_property_dbm[property_valid] = 10.0 * np.log10(rss_w[0][property_valid] * 1000.0)
    difference = float(np.max(np.abs(rssi[property_valid] - rss_property_dbm[property_valid])))
    consistency["maximum_absolute_difference_db"] = difference
    consistency["success"] = difference <= tolerance_db
    if not consistency["success"]:
        raise SionnaRssiError(
            "path gain 변환과 RadioMap.rss가 {:.6g}dB 다릅니다.".format(difference)
        )
    rows = []
    for row, column in np.argwhere(valid):
        x, y, z = centers[row, column]
        rows.append(
            {
                "grid_id": "grid-r{:03d}-c{:03d}".format(row, column),
                "row": int(row),
                "column": int(column),
                "x": float(x),
                "y": float(y),
                "z": float(z),
                "sionna_rssi_dbm": float(rssi[row, column]),
                "path_gain_linear": float(values[row, column]),
            }
        )
    return rows, rssi, consistency


def _plot_radio_map(path: Path, centers: np.ndarray, rssi: np.ndarray, positions) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(11, 8))
    image = axis.pcolormesh(
        centers[:, :, 0],
        centers[:, :, 1],
        rssi,
        shading="nearest",
        cmap="viridis",
    )
    figure.colorbar(image, ax=axis, label="RSSI (dBm)")
    for value in positions:
        x, y, _z = value["resolved_position_m"]
        is_tx = value["kind"] == "transmitter"
        axis.scatter(
            [x],
            [y],
            marker="*" if is_tx else "x",
            color="red" if is_tx else "white",
            edgecolor="black" if is_tx else None,
            s=160 if is_tx else 60,
            label="TX" if is_tx else None,
        )
    axis.set_aspect("equal")
    axis.set_xlabel("X (m)")
    axis.set_ylabel("Y (m)")
    axis.set_title("Raw Sionna RT RSSI radio map")
    figure.tight_layout()
    figure.savefig(path, dpi=170)
    plt.close(figure)


def run_sionna_rssi(
    scene_path: Any,
    marker_path: Any,
    solver_path: Any,
    output_directory: Any,
    *,
    allow_draft: bool = False,
    scene_xml_override: Optional[Any] = None,
) -> Dict[str, Any]:
    scene_source = resolve_path(scene_path)
    marker_source = resolve_path(marker_path)
    solver_source = resolve_path(solver_path)
    scene_document = load_json(scene_source)
    marker_document = load_json(marker_source)
    solver_document = load_json(solver_source)
    scene_report = validate_scene_document(scene_document)
    marker_report = validate_marker_document(marker_document, scene_report)
    solver_report = validate_solver_document(solver_document)
    ready = scene_report["status"] == "ready" and marker_report["status"] == "ready"
    if not ready and not allow_draft:
        raise SionnaRssiError(
            "논문용 Sionna 실행은 ready Scene/Marker가 필요합니다. Dry Run은 --allow-draft를 명시하세요."
        )
    transmitter = marker_document["tx"][0] if marker_document["tx"] else None
    if transmitter is None:
        raise SionnaRssiError("Sionna 실행에 TX가 하나 필요합니다.")
    settings = _metric_settings(scene_document, solver_document, transmitter)
    metric_scene = load_metric_scene(settings)
    room = RoomContainment.from_metadata(metric_scene.metric_metadata)
    validation = solver_document["sionna_rssi"]["validation"]
    positions, point_metadata = _device_positions(
        marker_document, room, float(validation["device_clearance_m"])
    )
    output = resolve_path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    environment = diagnose_environment()
    write_json(output / "environment.json", environment)
    if environment["status"] != "available":
        raise SionnaRssiError(
            "Sionna RT를 실행할 수 없습니다: {}".format(environment.get("reason"))
        )
    runtime = solver_document["sionna_rssi"]["runtime"]
    packages = environment.get("packages", {})
    actual_versions = {
        "required_sionna_rt_version": packages.get("sionna_rt_distribution"),
        "required_mitsuba_version": packages.get("mitsuba"),
        "required_drjit_version": packages.get("drjit"),
    }
    mismatches = {
        field: {"required": runtime[field], "actual": actual_versions[field]}
        for field in actual_versions
        if str(actual_versions[field]) != str(runtime[field])
    }
    if mismatches:
        raise SionnaRssiError(
            "동결된 Sionna 실행 환경과 버전이 다릅니다: {}".format(mismatches)
        )
    if scene_xml_override is None:
        manifest = export_scene(metric_scene, settings, output)
        scene_xml = Path(manifest["scene_xml"])
        scene_mode = "metric_proxy_export"
    else:
        scene_xml = resolve_path(scene_xml_override)
        if not scene_xml.is_file():
            raise SionnaRssiError("Sionna scene XML을 찾을 수 없습니다: {}".format(scene_xml))
        manifest = None
        scene_mode = "prebuilt_scene_xml_override"
    scene, scene_load_seconds = configure_sionna_scene(
        str(scene_xml), settings, positions
    )
    point_rows, point_report = _solve_points(
        scene, settings, point_metadata, float(transmitter["power_dbm"])
    )
    coverage = run_coverage_solver(scene, settings, room, positions)
    grid_rows, grid_rssi, consistency = _radio_map_rows(
        coverage,
        float(transmitter["power_dbm"]),
        float(validation["rss_consistency_tolerance_db"]),
    )
    minimum_grid_points = int(validation["minimum_valid_grid_points"])
    if len(grid_rows) < minimum_grid_points:
        raise SionnaRssiError(
            "유효 Grid 점 {}개가 최소 {}개보다 적습니다.".format(
                len(grid_rows), minimum_grid_points
            )
        )
    processed = output / "processed"
    figures = output / "figures"
    processed.mkdir(parents=True, exist_ok=True)
    figures.mkdir(parents=True, exist_ok=True)
    point_path = processed / "sionna_points.csv"
    grid_path = processed / "sionna_grid.csv"
    _write_csv(point_path, tuple(point_rows[0].keys()), point_rows)
    _write_csv(grid_path, tuple(grid_rows[0].keys()), grid_rows)
    np.save(processed / "sionna_grid_path_gain_linear.npy", coverage["values"])
    np.save(processed / "sionna_grid_valid_mask.npy", coverage["valid_mask"])
    np.save(processed / "sionna_grid_rssi_dbm.npy", grid_rssi)
    preview_path = figures / "raw_sionna_rssi_map.png"
    _plot_radio_map(preview_path, coverage["centers"], grid_rssi, positions)
    warnings = list(scene_report["warnings"]) + list(marker_report["warnings"])
    if not ready:
        warnings.insert(0, "DRY RUN ONLY — draft Scene/Marker 결과는 논문 수치로 사용하지 않습니다.")
    report_path = output / "sionna_rssi_report.json"
    report = {
        "schema_version": "1.0",
        "success": True,
        "ready_input": ready,
        "draft_execution_allowed": bool(allow_draft),
        "paper_evidence_eligible": ready and not allow_draft,
        "scene_id": scene_report["scene_id"],
        "coordinate_system_id": scene_report["coordinate_system_id"],
        "scene_mode": scene_mode,
        "scene_xml": str(scene_xml.resolve()),
        "solver": solver_report,
        "environment": {
            "python_version": environment.get("python_version"),
            "packages": environment.get("packages"),
            "mitsuba_variant": environment.get("mitsuba_variant"),
            "gpu_backend_active": environment.get("gpu_backend_active"),
        },
        "transmitter": {
            "marker_id": transmitter["id"],
            "frequency_hz": float(transmitter["frequency_hz"]),
            "power_dbm": float(transmitter["power_dbm"]),
        },
        "point_prediction": point_report,
        "radio_map": {
            **coverage["metadata"],
            "exported_valid_grid_point_count": len(grid_rows),
            "rssi_conversion_validation": consistency,
        },
        "performance": {
            "scene_load_seconds": scene_load_seconds,
            "point_solve_seconds": point_report["solve_time_seconds"],
            "radio_map_solve_seconds": coverage["metadata"]["solve_time_seconds"],
        },
        "input_sha256": {
            "scene_json": _sha256(scene_source),
            "markers_json": _sha256(marker_source),
            "solver_json": _sha256(solver_source),
            "scene_xml": _sha256(scene_xml),
        },
        "warnings": warnings,
        "files": {
            "sionna_points_csv": str(point_path.resolve()),
            "sionna_grid_csv": str(grid_path.resolve()),
            "grid_path_gain_npy": str(
                (processed / "sionna_grid_path_gain_linear.npy").resolve()
            ),
            "grid_valid_mask_npy": str(
                (processed / "sionna_grid_valid_mask.npy").resolve()
            ),
            "grid_rssi_dbm_npy": str(
                (processed / "sionna_grid_rssi_dbm.npy").resolve()
            ),
            "radio_map_png": str(preview_path.resolve()),
            "environment_json": str((output / "environment.json").resolve()),
            "report_json": str(report_path.resolve()),
        },
    }
    if manifest is not None:
        report["files"]["scene_manifest_json"] = str(
            (output / "scene_manifest.json").resolve()
        )
    write_json(report_path, report)
    return report
