"""논문 실험 입력 파일의 공통 계약과 교차 검증.

이 모듈은 Sionna, GUI, Backend 중 어느 한 구현에도 종속되지 않는다.
세 파트가 같은 scene ID, 좌표계 ID, point role을 쓰는지 먼저 확인하는
것이 목적이다.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple


class ContractError(ValueError):
    """실험 파일이 동결된 계약을 만족하지 않을 때 발생한다."""


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUPPORTED_STATUSES = {"draft", "ready"}
SUPPORTED_POINT_ROLES = {"offset", "calibration", "test", "dry_run"}

RAW_REQUIRED_COLUMNS: Tuple[str, ...] = (
    "experiment_id",
    "session_id",
    "point_id",
    "point_role",
    "node_id",
    "timestamp",
    "seq",
    "rssi_raw_dbm",
    "rssi_filtered_dbm",
    "sample_count",
    "error_flags",
    "device_offset_db",
    "pos_x",
    "pos_y",
    "pos_z",
    "ap_bssid",
    "ap_channel",
    "valid",
)

SUMMARY_REQUIRED_COLUMNS: Tuple[str, ...] = (
    "point_id",
    "point_role",
    "node_id",
    "x",
    "y",
    "z",
    "sample_count",
    "median_raw",
    "median_filtered",
    "mean_filtered",
    "std_filtered",
    "device_offset_db",
    "corrected_rssi",
)


def resolve_path(value: Any) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ContractError("파일 경로가 비어 있습니다.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def load_json(path: Any) -> Dict[str, Any]:
    source = resolve_path(path)
    if not source.is_file():
        raise ContractError("JSON 파일을 찾을 수 없습니다: {}".format(source))
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError("JSON을 읽을 수 없습니다: {}".format(exc)) from exc
    if not isinstance(document, dict):
        raise ContractError("JSON 최상위 값은 객체여야 합니다: {}".format(source))
    return document


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError("{}는 키와 값의 모음이어야 합니다.".format(field))
    return value


def _list(value: Any, field: str) -> List[Any]:
    if not isinstance(value, list):
        raise ContractError("{}는 목록이어야 합니다.".format(field))
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("{}가 비어 있습니다.".format(field))
    return value.strip()


def _status(value: Any, field: str) -> str:
    status = _text(value, field)
    if status not in SUPPORTED_STATUSES:
        raise ContractError("{}는 draft 또는 ready여야 합니다.".format(field))
    return status


def _finite(value: Any, field: str, minimum: float = None, strict: bool = False) -> float:
    if isinstance(value, bool):
        raise ContractError("{}는 숫자여야 합니다.".format(field))
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContractError("{}는 숫자여야 합니다.".format(field)) from exc
    if not math.isfinite(number):
        raise ContractError("{}는 유한한 숫자여야 합니다.".format(field))
    if minimum is not None:
        invalid = number <= minimum if strict else number < minimum
        if invalid:
            relation = "초과" if strict else "이상"
            raise ContractError(
                "{}는 {} {}이어야 합니다.".format(field, minimum, relation)
            )
    return number


def _integer(value: Any, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool):
        raise ContractError("{}는 정수여야 합니다.".format(field))
    try:
        number = int(value)
        exact = float(value) == float(number)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContractError("{}는 정수여야 합니다.".format(field)) from exc
    if not exact or number < minimum:
        raise ContractError("{}는 {} 이상의 정수여야 합니다.".format(field, minimum))
    return number


def _require_schema_version(document: Mapping[str, Any], field: str) -> None:
    if document.get("schema_version") != "1.0":
        raise ContractError("{} schema_version은 1.0이어야 합니다.".format(field))


def _position(value: Any, field: str) -> Tuple[float, float, float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 3:
        raise ContractError("{}는 [x, y, z] 숫자 3개여야 합니다.".format(field))
    return tuple(_finite(item, "{}[{}]".format(field, index)) for index, item in enumerate(value))


def validate_scene_document(document: Mapping[str, Any]) -> Dict[str, Any]:
    _require_schema_version(document, "Scene")
    scene = _mapping(document.get("scene"), "scene")
    scene_id = _text(scene.get("id"), "scene.id")
    status = _status(scene.get("status"), "scene.status")

    coordinate = _mapping(scene.get("coordinate_system"), "scene.coordinate_system")
    coordinate_id = _text(coordinate.get("id"), "scene.coordinate_system.id")
    if coordinate.get("locked") is not True:
        raise ContractError("실험 좌표계는 locked=true로 동결해야 합니다.")
    if coordinate.get("units") != "meters":
        raise ContractError("실험 좌표 단위는 meters여야 합니다.")
    if coordinate.get("handedness") != "right":
        raise ContractError("실험 좌표계는 오른손 좌표계(right)여야 합니다.")
    if coordinate.get("up_axis") != "+Z":
        raise ContractError("실험 좌표계의 위쪽 축은 +Z여야 합니다.")
    origin = _position(coordinate.get("origin_m"), "scene.coordinate_system.origin_m")
    if any(abs(value) > 1.0e-12 for value in origin):
        raise ContractError("실험 좌표계 원점은 [0, 0, 0]이어야 합니다.")
    _text(coordinate.get("origin_description_ko"), "origin_description_ko")
    axes = _mapping(coordinate.get("axes"), "scene.coordinate_system.axes")
    for axis in ("x", "y", "z"):
        axis_document = _mapping(axes.get(axis), "axes.{}".format(axis))
        if axis_document.get("sign") != "+{}".format(axis.upper()):
            raise ContractError("axes.{}.sign은 +{}여야 합니다.".format(axis, axis.upper()))
        _text(axis_document.get("positive_direction_ko"), "axes.{}.positive_direction_ko".format(axis))

    dimensions = _mapping(scene.get("dimensions_m"), "scene.dimensions_m")
    width = _finite(dimensions.get("width_x"), "dimensions_m.width_x", 0.0, strict=True)
    depth = _finite(dimensions.get("depth_y"), "dimensions_m.depth_y", 0.0, strict=True)
    elevation = _finite(
        dimensions.get("floor_elevation_change"),
        "dimensions_m.floor_elevation_change",
        0.0,
    )
    door = _mapping(dimensions.get("door"), "dimensions_m.door")
    door_width = _finite(door.get("width"), "dimensions_m.door.width", 0.0, strict=True)
    door_height = _finite(door.get("height"), "dimensions_m.door.height", 0.0, strict=True)

    proxy_scene = _mapping(scene.get("proxy_scene"), "scene.proxy_scene")
    proxy_status = _text(proxy_scene.get("status"), "scene.proxy_scene.status")
    if proxy_status not in {
        "pending_metric_update",
        "pending_obstacle_placement",
        "ready",
    }:
        raise ContractError("scene.proxy_scene.status가 지원되지 않습니다.")

    warnings = []
    if proxy_status == "pending_metric_update":
        warnings.append("실측 기준 Metric Proxy Scene 갱신이 아직 끝나지 않았습니다.")
    elif proxy_status == "pending_obstacle_placement":
        warnings.append("기본 Envelope는 완료됐지만 계단·문·책상·AP 배치가 남았습니다.")
    if status == "ready" and proxy_status != "ready":
        raise ContractError("scene.status=ready이면 proxy_scene.status도 ready여야 합니다.")
    return {
        "scene_id": scene_id,
        "coordinate_system_id": coordinate_id,
        "status": status,
        "proxy_scene_status": proxy_status,
        "bounds_m": {"x": [0.0, width], "y": [0.0, depth]},
        "dimensions_m": {
            "width_x": width,
            "depth_y": depth,
            "floor_elevation_change": elevation,
            "door_width": door_width,
            "door_height": door_height,
        },
        "warnings": warnings,
    }


def _validate_marker_position(
    value: Any, field: str, scene_report: Mapping[str, Any]
) -> Tuple[float, float, float]:
    x, y, z = _position(value, field)
    x_range = scene_report["bounds_m"]["x"]
    y_range = scene_report["bounds_m"]["y"]
    tolerance = 1.0e-9
    if x < x_range[0] - tolerance or x > x_range[1] + tolerance:
        raise ContractError("{}의 X 좌표가 강의실 범위를 벗어납니다.".format(field))
    if y < y_range[0] - tolerance or y > y_range[1] + tolerance:
        raise ContractError("{}의 Y 좌표가 강의실 범위를 벗어납니다.".format(field))
    if z < -tolerance:
        raise ContractError("{}의 Z 좌표는 0 이상이어야 합니다.".format(field))
    return x, y, z


def validate_marker_document(
    document: Mapping[str, Any], scene_report: Mapping[str, Any]
) -> Dict[str, Any]:
    _require_schema_version(document, "TX/RX")
    if _text(document.get("scene_id"), "scene_id") != scene_report["scene_id"]:
        raise ContractError("TX/RX scene_id가 Scene 계약과 다릅니다.")
    if (
        _text(document.get("coordinate_system_id"), "coordinate_system_id")
        != scene_report["coordinate_system_id"]
    ):
        raise ContractError("TX/RX coordinate_system_id가 Scene 계약과 다릅니다.")
    status = _status(document.get("status"), "status")
    requirements = _mapping(document.get("requirements"), "requirements")
    expected_tx = _integer(requirements.get("transmitter_count"), "transmitter_count", 1)
    expected_cal = _integer(
        requirements.get("calibration_receiver_count"), "calibration_receiver_count", 0
    )
    expected_test = _integer(requirements.get("test_receiver_count"), "test_receiver_count", 0)
    transmitters = _list(document.get("tx"), "tx")
    receivers = _list(document.get("rx"), "rx")

    marker_ids: List[str] = []
    point_ids: List[str] = []
    for index, raw in enumerate(transmitters):
        tx = _mapping(raw, "tx[{}]".format(index))
        marker_ids.append(_text(tx.get("id"), "tx[{}].id".format(index)))
        _text(tx.get("name"), "tx[{}].name".format(index))
        _validate_marker_position(tx.get("position_m"), "tx[{}].position_m".format(index), scene_report)
        _finite(tx.get("frequency_hz"), "tx[{}].frequency_hz".format(index), 0.0, strict=True)
        _finite(tx.get("power_dbm"), "tx[{}].power_dbm".format(index))

    role_counts = {"calibration": 0, "test": 0}
    for index, raw in enumerate(receivers):
        rx = _mapping(raw, "rx[{}]".format(index))
        marker_ids.append(_text(rx.get("id"), "rx[{}].id".format(index)))
        point_id = _text(rx.get("point_id"), "rx[{}].point_id".format(index))
        point_ids.append(point_id)
        _text(rx.get("name"), "rx[{}].name".format(index))
        role = _text(rx.get("role"), "rx[{}].role".format(index))
        if role not in role_counts:
            raise ContractError("rx[{}].role은 calibration 또는 test여야 합니다.".format(index))
        role_counts[role] += 1
        _validate_marker_position(rx.get("position_m"), "rx[{}].position_m".format(index), scene_report)

    if len(marker_ids) != len(set(marker_ids)):
        raise ContractError("TX/RX Marker id는 서로 달라야 합니다.")
    if len(point_ids) != len(set(point_ids)):
        raise ContractError("RX point_id는 서로 달라야 합니다.")

    actual = {
        "transmitter_count": len(transmitters),
        "calibration_receiver_count": role_counts["calibration"],
        "test_receiver_count": role_counts["test"],
    }
    expected = {
        "transmitter_count": expected_tx,
        "calibration_receiver_count": expected_cal,
        "test_receiver_count": expected_test,
    }
    warnings = []
    if actual != expected:
        message = "Marker 수가 아직 완료 기준과 다릅니다: expected={}, actual={}".format(
            expected, actual
        )
        if status == "ready":
            raise ContractError(message)
        warnings.append(message)
    return {
        "status": status,
        "expected_counts": expected,
        "actual_counts": actual,
        "warnings": warnings,
    }


def validate_method_document(document: Mapping[str, Any]) -> Dict[str, Any]:
    _require_schema_version(document, "Method config")
    config = _mapping(document.get("method_config"), "method_config")
    config_id = _text(config.get("id"), "method_config.id")
    status = _status(config.get("status"), "method_config.status")

    sionna = _mapping(config.get("sionna"), "method_config.sionna")
    if sionna.get("input_metric") != "path_gain_linear":
        raise ContractError("Sionna 입력은 path_gain_linear여야 합니다.")
    if sionna.get("prediction_unit") != "dBm":
        raise ContractError("Sionna 예측 출력 단위는 dBm이어야 합니다.")
    if sionna.get("conversion") != "tx_power_dbm + 10*log10(path_gain_linear)":
        raise ContractError("Sionna RSSI 변환식이 동결된 계약과 다릅니다.")

    idw = _mapping(config.get("idw"), "method_config.idw")
    power = _finite(idw.get("power"), "idw.power", 0.0, strict=True)
    if idw.get("distance_space") != "xyz_meters":
        raise ContractError("IDW 거리는 xyz_meters 3차원 거리여야 합니다.")
    _finite(
        idw.get("epsilon_distance_power"),
        "idw.epsilon_distance_power",
        0.0,
        strict=True,
    )
    _finite(
        idw.get("exact_match_tolerance_m"),
        "idw.exact_match_tolerance_m",
        0.0,
    )

    policy = _mapping(config.get("data_split_policy"), "method_config.data_split_policy")
    if policy.get("fit_role") != "calibration" or policy.get("evaluation_role") != "test":
        raise ContractError("보정점과 Test점 역할 분리가 동결된 계약과 다릅니다.")
    if policy.get("exclude_test_from_fitting") is not True:
        raise ContractError("Test 데이터는 fitting에서 반드시 제외해야 합니다.")

    evaluation = _mapping(config.get("evaluation"), "method_config.evaluation")
    if evaluation.get("target_column") != "corrected_rssi":
        raise ContractError("기본 평가값은 corrected_rssi여야 합니다.")
    if evaluation.get("metrics") != ["mae", "rmse"]:
        raise ContractError("평가 지표는 mae와 rmse 순서여야 합니다.")
    heatmap = _mapping(config.get("heatmap"), "method_config.heatmap")
    if heatmap.get("shared_color_scale") is not True:
        raise ContractError("세 방법의 히트맵은 공통 색상 범위를 사용해야 합니다.")
    return {
        "method_config_id": config_id,
        "status": status,
        "idw_power": power,
        "warnings": [],
    }


def validate_contract_bundle(
    scene_path: Any,
    marker_path: Any,
    method_path: Any,
    require_ready: bool = False,
) -> Dict[str, Any]:
    scene = validate_scene_document(load_json(scene_path))
    markers = validate_marker_document(load_json(marker_path), scene)
    methods = validate_method_document(load_json(method_path))
    if require_ready:
        incomplete = [
            name
            for name, report in (("scene", scene), ("markers", markers), ("methods", methods))
            if report["status"] != "ready"
        ]
        if incomplete:
            raise ContractError("ready 상태가 아닌 계약이 있습니다: {}".format(incomplete))
    warnings = scene["warnings"] + markers["warnings"] + methods["warnings"]
    return {
        "success": True,
        "ready": not warnings
        and all(report["status"] == "ready" for report in (scene, markers, methods)),
        "scene": scene,
        "markers": markers,
        "methods": methods,
        "warnings": warnings,
    }


def _validate_summary_row(row: Mapping[str, str], row_number: int) -> None:
    role = row.get("point_role", "").strip()
    if role not in SUPPORTED_POINT_ROLES:
        raise ContractError(
            "CSV {}행 point_role이 지원되지 않습니다: {}".format(row_number, role)
        )
    for field in (
        "x",
        "y",
        "z",
        "sample_count",
        "median_raw",
        "median_filtered",
        "mean_filtered",
        "std_filtered",
        "device_offset_db",
        "corrected_rssi",
    ):
        _finite(row.get(field), "CSV {}행 {}".format(row_number, field))


def _parse_bool(value: str, field: str) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    raise ContractError("{}는 true/false 또는 1/0이어야 합니다.".format(field))


def _validate_raw_row(row: Mapping[str, str], row_number: int) -> None:
    role = row.get("point_role", "").strip()
    if role not in SUPPORTED_POINT_ROLES:
        raise ContractError(
            "CSV {}행 point_role이 지원되지 않습니다: {}".format(row_number, role)
        )
    for field in ("seq", "sample_count", "device_offset_db", "pos_x", "pos_y", "pos_z", "ap_channel"):
        _finite(row.get(field), "CSV {}행 {}".format(row_number, field))
    is_valid = _parse_bool(row.get("valid", ""), "CSV {}행 valid".format(row_number))
    if is_valid:
        _finite(row.get("rssi_raw_dbm"), "CSV {}행 rssi_raw_dbm".format(row_number))
        _finite(row.get("rssi_filtered_dbm"), "CSV {}행 rssi_filtered_dbm".format(row_number))


def validate_csv_contract(path: Any, kind: str, require_rows: bool = False) -> Dict[str, Any]:
    source = resolve_path(path)
    if not source.is_file():
        raise ContractError("CSV 파일을 찾을 수 없습니다: {}".format(source))
    if kind not in {"raw", "summary"}:
        raise ContractError("CSV kind는 raw 또는 summary여야 합니다.")
    required = RAW_REQUIRED_COLUMNS if kind == "raw" else SUMMARY_REQUIRED_COLUMNS
    try:
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = tuple(reader.fieldnames or ())
            missing = [field for field in required if field not in fieldnames]
            if missing:
                raise ContractError("CSV 필수 열이 없습니다: {}".format(missing))
            row_count = 0
            point_ids = set()
            for row_count, row in enumerate(reader, start=1):
                csv_row = row_count + 1
                if kind == "summary":
                    _validate_summary_row(row, csv_row)
                else:
                    _validate_raw_row(row, csv_row)
                point_id = row.get("point_id", "").strip()
                if not point_id:
                    raise ContractError("CSV {}행 point_id가 비어 있습니다.".format(csv_row))
                point_ids.add(point_id)
    except OSError as exc:
        raise ContractError("CSV를 읽을 수 없습니다: {}".format(exc)) from exc
    if require_rows and row_count == 0:
        raise ContractError("CSV에 데이터 행이 없습니다.")
    warnings = [] if row_count else ["CSV Header만 있고 데이터 행은 아직 없습니다."]
    return {
        "success": True,
        "kind": kind,
        "path": str(source),
        "row_count": row_count,
        "point_count": len(point_ids),
        "required_columns": list(required),
        "warnings": warnings,
    }


def write_json_report(report: Mapping[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False)
