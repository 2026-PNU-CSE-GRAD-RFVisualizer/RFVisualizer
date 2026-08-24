"""여러 높이 Sionna Radio Map을 Viewer용 RGBA Volume Bundle로 내보낸다.

기존 z=0.45 m 2D 분석 경로는 건드리지 않는다. 여기서 만드는 Volume은 실측이 없는
높이로 XYZ IDW를 외삽한 결과이므로 논문 근거로 승격하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

import numpy as np

from .analysis_compute import idw_predict

SCHEMA_VERSION = "1.0"
CHANNELS = ("raw_sionna", "plain_idw", "residual_idw", "valid_mask")
VERTICAL_RESIDUAL_POLICY = "xyz_idw_from_z_0.45m"
#: 셀 중심 좌표는 solver가 float32로 만들기 때문에 정확히 같을 수 없다.
GRID_TOLERANCE_M = 1.0e-4


class VolumeError(RuntimeError):
    """Volume 입력·배열·Bundle이 계약을 만족하지 않을 때 발생한다."""


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise VolumeError("{}는 숫자여야 합니다.".format(field))
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise VolumeError("{}는 숫자여야 합니다.".format(field)) from exc
    if not math.isfinite(number):
        raise VolumeError("{}는 유한한 숫자여야 합니다.".format(field))
    return number


def volume_heights(solver_document: Mapping[str, Any]) -> List[float]:
    """Solver 설정의 volume_z_heights_m를 검증해 오름차순 높이 목록으로 돌려준다."""

    try:
        radio_map = solver_document["sionna_rssi"]["radio_map"]
    except (KeyError, TypeError) as exc:
        raise VolumeError("solver 문서에 sionna_rssi.radio_map이 없습니다.") from exc
    raw = radio_map.get("volume_z_heights_m")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or not raw:
        raise VolumeError("radio_map.volume_z_heights_m는 비어 있지 않은 목록이어야 합니다.")
    heights = [
        _finite(value, "volume_z_heights_m[{}]".format(index))
        for index, value in enumerate(raw)
    ]
    steps = np.diff(heights)
    if len(heights) > 1:
        if np.any(steps <= 0.0):
            raise VolumeError("volume_z_heights_m는 중복 없이 오름차순이어야 합니다.")
        # Renderer가 world 좌표를 3D Texture 좌표로 한 번의 affine 변환으로 옮기므로
        # 높이 간격이 일정하지 않으면 그릴 수 없다.
        if float(np.max(np.abs(steps - steps[0]))) > GRID_TOLERANCE_M:
            raise VolumeError("volume_z_heights_m 간격이 일정하지 않습니다.")
    return heights


def stack_layers(layers: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """높이별 Radio Map을 하나의 [z][y][x] 격자로 쌓고 XY 격자 동일성을 검증한다."""

    if not layers:
        raise VolumeError("Volume에는 높이 층이 하나 이상 필요합니다.")
    reference = np.asarray(layers[0]["centers"], dtype=float)
    if reference.ndim != 3 or reference.shape[-1] != 3:
        raise VolumeError("cell center 배열은 [row, column, 3]이어야 합니다.")
    heights: List[float] = []
    rssi: List[np.ndarray] = []
    valid: List[np.ndarray] = []
    for index, layer in enumerate(layers):
        centers = np.asarray(layer["centers"], dtype=float)
        values = np.asarray(layer["rssi_dbm"], dtype=float)
        mask = np.asarray(layer["valid_mask"], dtype=bool)
        label = "높이 {}층".format(index)
        if centers.shape != reference.shape:
            raise VolumeError("{}의 Grid 모양이 첫 층과 다릅니다.".format(label))
        if values.shape != reference.shape[:2] or mask.shape != reference.shape[:2]:
            raise VolumeError("{}의 값/Mask 모양이 Grid와 다릅니다.".format(label))
        offset = float(np.max(np.abs(centers[..., :2] - reference[..., :2])))
        if offset > GRID_TOLERANCE_M:
            raise VolumeError(
                "{}의 XY 셀 중심이 첫 층과 {:.6g}m 다릅니다.".format(label, offset)
            )
        z = _finite(layer["z_height_m"], "{} z_height_m".format(label))
        if float(np.max(np.abs(centers[..., 2] - z))) > GRID_TOLERANCE_M:
            raise VolumeError("{}의 셀 중심 z가 z_height_m과 다릅니다.".format(label))
        if not np.all(np.isfinite(values[mask])):
            raise VolumeError("{}의 유효 셀에 유한하지 않은 dBm 값이 있습니다.".format(label))
        heights.append(z)
        rssi.append(values)
        valid.append(mask)
    if len(heights) > 1 and np.any(np.diff(heights) <= 0.0):
        raise VolumeError("Volume 층은 중복 없이 오름차순 높이여야 합니다.")

    spacing_x = _uniform_spacing(reference[0, :, 0], "X")
    spacing_y = _uniform_spacing(reference[:, 0, 1], "Y")
    spacing_z = float(np.diff(heights)[0]) if len(heights) > 1 else 0.0
    return {
        "heights_m": heights,
        "centers_xy": reference[..., :2],
        "rssi_dbm": np.stack(rssi),
        "valid_mask": np.stack(valid),
        "origin_m": [
            float(reference[0, 0, 0]),
            float(reference[0, 0, 1]),
            float(heights[0]),
        ],
        "spacing_m": [spacing_x, spacing_y, spacing_z],
        "shape_zyx": [len(heights), reference.shape[0], reference.shape[1]],
    }


def _uniform_spacing(axis: np.ndarray, label: str) -> float:
    if len(axis) < 2:
        return 0.0
    steps = np.diff(axis)
    if float(np.max(np.abs(steps - steps[0]))) > GRID_TOLERANCE_M:
        raise VolumeError("{}축 셀 간격이 일정하지 않습니다.".format(label))
    return float(steps[0])


def voxel_positions(stack: Mapping[str, Any]) -> np.ndarray:
    """[z][y][x] 순서로 펼친 voxel 중심 좌표 N×3을 만든다."""

    centers_xy = np.asarray(stack["centers_xy"], dtype=float)
    heights = np.asarray(stack["heights_m"], dtype=float)
    tiled = np.repeat(centers_xy[None, ...], len(heights), axis=0)
    z = np.broadcast_to(heights[:, None, None], tiled.shape[:3])
    return np.concatenate([tiled, z[..., None]], axis=-1).reshape(-1, 3)


def build_volume(
    stack: Mapping[str, Any],
    calibration_positions: Any,
    calibration_actual: Any,
    calibration_sionna: Any,
    idw_settings: Mapping[str, float],
) -> Dict[str, np.ndarray]:
    """Raw Sionna, Plain IDW, Residual IDW 세 Volume을 같은 격자 위에 만든다."""

    positions = np.asarray(calibration_positions, dtype=float)
    actual = np.asarray(calibration_actual, dtype=float)
    sionna = np.asarray(calibration_sionna, dtype=float)
    if positions.ndim != 2 or positions.shape[1] != 3:
        raise VolumeError("Calibration 위치는 N×3 [x,y,z]여야 합니다.")
    if actual.shape != (len(positions),) or sionna.shape != (len(positions),):
        raise VolumeError("Calibration 값 개수가 위치 개수와 맞지 않습니다.")

    shape = tuple(stack["shape_zyx"])
    queries = voxel_positions(stack)
    raw = np.asarray(stack["rssi_dbm"], dtype=float)
    valid = np.asarray(stack["valid_mask"], dtype=bool)
    plain = idw_predict(positions, actual, queries, **idw_settings).reshape(shape)
    residual = raw + idw_predict(
        positions, actual - sionna, queries, **idw_settings
    ).reshape(shape)
    volume = {
        "raw_sionna": np.where(valid, raw, np.nan),
        "plain_idw": np.where(valid, plain, np.nan),
        "residual_idw": np.where(valid, residual, np.nan),
        "valid_mask": valid,
    }
    for name in ("raw_sionna", "plain_idw", "residual_idw"):
        if not np.all(np.isfinite(volume[name][valid])):
            raise VolumeError("{} Volume의 유효 voxel에 NaN/Inf가 있습니다.".format(name))
    return volume


def dbm_range(volume: Mapping[str, np.ndarray]) -> List[float]:
    """세 방식이 함께 쓸 공통 dBm 색상 범위를 구한다."""

    valid = np.asarray(volume["valid_mask"], dtype=bool)
    if not np.any(valid):
        raise VolumeError("유효 voxel이 하나도 없습니다.")
    values = np.concatenate(
        [np.asarray(volume[name])[valid] for name in CHANNELS[:3]]
    )
    return [float(np.min(values)), float(np.max(values))]


def pack_rgba(volume: Mapping[str, np.ndarray]) -> np.ndarray:
    """[z][y][x][RGBA] float32 little-endian 배열로 채널을 묶는다.

    dBm 세 채널은 Valid Mask로 **미리 곱해서**(premultiplied) 저장하고 invalid voxel은
    네 채널 모두 0이다. Shader가 GL_LINEAR로 읽은 뒤 Alpha로 나누면 유효 voxel만의
    가중평균이 나오므로, 경계에서 빈 칸 값이 섞여 들어가지 않는다. mask=1인 유효
    voxel에는 dBm 값이 그대로 들어 있다.
    """

    valid = np.asarray(volume["valid_mask"], dtype=bool)
    channels = [
        np.where(valid, np.nan_to_num(volume[name], nan=0.0), 0.0)
        for name in CHANNELS[:3]
    ]
    channels.append(valid.astype(float))
    return np.stack(channels, axis=-1).astype("<f4")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_bundle(
    output: Any,
    stack: Mapping[str, Any],
    volume: Mapping[str, np.ndarray],
    transform_scene_from_metric: Any,
    frame_id: str,
    sources: Mapping[str, Any],
    occlusion_meshes: Sequence[Any] = (),
    metadata: Mapping[str, Any] = None,
) -> Dict[str, Any]:
    """viewer_volume/ Bundle(manifest, RGBA bin, 가림용 Mesh)을 쓴다."""

    bundle = Path(output)
    meshes_dir = bundle / "occlusion_meshes"
    meshes_dir.mkdir(parents=True, exist_ok=True)

    transform = np.asarray(transform_scene_from_metric, dtype=float)
    if transform.shape != (4, 4) or not np.all(np.isfinite(transform)):
        raise VolumeError("T_scene_from_metric은 유한한 4x4 행렬이어야 합니다.")
    roundtrip = float(np.max(np.abs(transform @ np.linalg.inv(transform) - np.eye(4))))
    if roundtrip > 1.0e-5:
        raise VolumeError("T_scene_from_metric 왕복 오차가 큽니다: {:.3g}".format(roundtrip))

    color_range = dbm_range(volume)
    packed = pack_rgba(volume)
    binary_path = bundle / "volume_rgba_f32.bin"
    packed.tofile(binary_path)
    nz, ny, nx = tuple(stack["shape_zyx"])
    expected_bytes = nx * ny * nz * 4 * 4
    if binary_path.stat().st_size != expected_bytes:
        raise VolumeError(
            "Volume binary가 {} byte여야 하는데 {} byte입니다.".format(
                expected_bytes, binary_path.stat().st_size
            )
        )

    mesh_entries = []
    for source in occlusion_meshes:
        source_path = Path(source)
        if not source_path.is_file():
            raise VolumeError("가림용 Mesh를 찾을 수 없습니다: {}".format(source_path))
        target = meshes_dir / source_path.name
        shutil.copyfile(source_path, target)
        mesh_entries.append(
            {"file": "occlusion_meshes/" + target.name, "sha256": _sha256(target)}
        )
    if not mesh_entries:
        raise VolumeError("가림용 Proxy Mesh가 하나도 없습니다.")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "frame_id": frame_id,
        "paper_evidence_eligible": False,
        "status": "provisional",
        "vertical_extrapolation": True,
        "vertical_residual_policy": VERTICAL_RESIDUAL_POLICY,
        "grid": {
            "shape_zyx": [nz, ny, nx],
            "origin_m": list(stack["origin_m"]),
            "spacing_m": list(stack["spacing_m"]),
            "z_heights_m": list(stack["heights_m"]),
            "storage_order": "zyx",
        },
        "T_scene_from_metric": transform.tolist(),
        "dbm_range": color_range,
        "channels": list(CHANNELS),
        "channel_encoding": "dbm_premultiplied_by_valid_mask",
        "data": {
            "file": binary_path.name,
            "dtype": "float32",
            "byte_order": "little_endian",
            "byte_count": expected_bytes,
            "components_per_voxel": 4,
        },
        "occlusion_meshes": mesh_entries,
        "sources": dict(sources),
    }
    if metadata:
        manifest.update(metadata)
    manifest_path = bundle / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def source_entry(path: Any, role: str) -> Dict[str, Any]:
    """Bundle 출처 한 건을 경로·역할·SHA-256으로 기록한다."""

    resolved = Path(path)
    if not resolved.is_file():
        raise VolumeError("출처 파일을 찾을 수 없습니다: {}".format(resolved))
    return {
        "role": role,
        "path": str(resolved.resolve()),
        "sha256": _sha256(resolved),
    }


def _calibration_means(path: Path) -> Dict[str, Dict[str, Any]]:
    """calibration_points.csv를 Calibration 위치별 corrected_rssi 평균으로 모은다."""

    import csv

    grouped: Dict[str, Dict[str, Any]] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"calibration_point_id", "x", "y", "z", "corrected_rssi"}
        if not required.issubset(reader.fieldnames or []):
            raise VolumeError(
                "Calibration CSV에 {} 열이 필요합니다.".format(sorted(required))
            )
        for index, row in enumerate(reader, start=2):
            point_id = str(row["calibration_point_id"]).strip()
            if not point_id:
                raise VolumeError("Calibration CSV {}행의 위치 id가 비어 있습니다.".format(index))
            position = [
                _finite(row[axis], "Calibration {}행 {}".format(index, axis))
                for axis in ("x", "y", "z")
            ]
            value = _finite(row["corrected_rssi"], "Calibration {}행 corrected_rssi".format(index))
            entry = grouped.setdefault(
                point_id, {"position": position, "values": [], "sample_count": 0}
            )
            offset = float(np.max(np.abs(np.asarray(entry["position"]) - position)))
            if offset > GRID_TOLERANCE_M:
                raise VolumeError(
                    "{}의 좌표가 행마다 다릅니다: {:.6g}m".format(point_id, offset)
                )
            entry["values"].append(value)
            entry["sample_count"] += 1
    if not grouped:
        raise VolumeError("Calibration CSV에 행이 없습니다.")
    for entry in grouped.values():
        entry["mean_dbm"] = float(np.mean(entry["values"]))
    return grouped


def export_viewer_volume(
    sionna_output: Any,
    calibration_csv: Any,
    sionna_points_csv: Any,
    method_path: Any,
    transform_path: Any,
    scene_path: Any,
    output: Any,
    occlusion_meshes: Sequence[Any],
) -> Dict[str, Any]:
    """높이별 Sionna 결과와 실측 Calibration으로 Viewer Volume Bundle을 만든다."""

    from .analysis_inputs import _method_settings, load_sionna_points
    from .contracts import load_json, resolve_path

    processed = resolve_path(sionna_output) / "processed"
    rssi_path = processed / "sionna_volume_rssi_dbm.npy"
    if not rssi_path.is_file():
        raise VolumeError(
            "높이별 Sionna 결과가 없습니다. solver 설정에 volume_z_heights_m를 넣고 "
            "run-sionna를 다시 실행하세요: {}".format(rssi_path)
        )
    rssi = np.load(rssi_path)
    valid = np.load(processed / "sionna_volume_valid_mask.npy")
    centers_xy = np.load(processed / "sionna_volume_centers_xy.npy")

    report = load_json(resolve_path(sionna_output) / "sionna_rssi_report.json")
    if not report.get("volume"):
        raise VolumeError("Sionna 보고서에 volume 절이 없습니다.")
    heights = report["volume"]["z_heights_m"]
    if len(heights) != len(rssi):
        raise VolumeError("보고서의 높이 수와 Volume 배열의 층수가 다릅니다.")
    stack = stack_layers(
        [
            {
                "z_height_m": height,
                "centers": np.concatenate(
                    [centers_xy, np.full(centers_xy.shape[:2] + (1,), height)], axis=-1
                ),
                "rssi_dbm": rssi[index],
                "valid_mask": valid[index],
            }
            for index, height in enumerate(heights)
        ]
    )

    calibration = _calibration_means(resolve_path(calibration_csv))
    sionna_points = load_sionna_points(resolve_path(sionna_points_csv))
    missing = sorted(set(calibration) - set(sionna_points))
    if missing:
        raise VolumeError("Sionna 예측이 없는 Calibration 위치가 있습니다: {}".format(missing))
    point_ids = sorted(calibration)
    positions = np.asarray([calibration[pid]["position"] for pid in point_ids], dtype=float)
    actual = np.asarray([calibration[pid]["mean_dbm"] for pid in point_ids], dtype=float)
    predicted = np.asarray(
        [sionna_points[pid]["sionna_rssi_dbm"] for pid in point_ids], dtype=float
    )
    for index, pid in enumerate(point_ids):
        offset = float(np.linalg.norm(positions[index] - sionna_points[pid]["position"]))
        if offset > 1.0e-6:
            raise VolumeError("{}의 실측/Sionna 좌표가 {:.6g}m 다릅니다.".format(pid, offset))

    settings = _method_settings(load_json(resolve_path(method_path)))
    volume = build_volume(stack, positions, actual, predicted, settings)

    calibration_document = load_json(resolve_path(transform_path))
    transform = np.asarray(
        calibration_document["transform"]["T_scene_from_metric"], dtype=float
    )
    # calibration.json 의 "scene" 은 Blender 로 내보낸 mesh 좌표계다.
    # SIBR/PGSR Gaussian 좌표계는 -Y 가 위라서 축 교환을 한 번 더 적용해야 한다.
    swap = np.eye(4)
    swap[:3, :3] = np.asarray([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])
    scene_document = load_json(resolve_path(scene_path))
    return write_bundle(
        output,
        stack,
        volume,
        swap @ transform,
        scene_document["scene"]["coordinate_system"]["id"],
        {
            "sionna_report": source_entry(
                resolve_path(sionna_output) / "sionna_rssi_report.json", "sionna"
            ),
            "calibration_csv": source_entry(resolve_path(calibration_csv), "measurement"),
            "sionna_points_csv": source_entry(resolve_path(sionna_points_csv), "sionna"),
            "method_config": source_entry(resolve_path(method_path), "method"),
            "proxy_calibration": source_entry(resolve_path(transform_path), "transform"),
        },
        occlusion_meshes=[resolve_path(mesh) for mesh in occlusion_meshes],
        metadata={
            "calibration_points": [
                {
                    "point_id": pid,
                    "position_m": calibration[pid]["position"],
                    "mean_corrected_rssi_dbm": calibration[pid]["mean_dbm"],
                    "sample_row_count": calibration[pid]["sample_count"],
                }
                for pid in point_ids
            ],
            "transform_note_ko": (
                "T_scene_from_metric은 SIBR Gaussian 좌표계 기준이다. "
                "calibration.json 원본 행렬에 (x,y,z)->(x,-z,y) 축 교환을 곱한 값이다."
            ),
        },
    )
