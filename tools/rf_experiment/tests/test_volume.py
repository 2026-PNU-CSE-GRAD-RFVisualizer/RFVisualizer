import json
from pathlib import Path

import numpy as np
import pytest

from tools.rf_experiment.volume import (
    CHANNELS,
    VolumeError,
    build_volume,
    dbm_range,
    pack_rgba,
    stack_layers,
    voxel_positions,
    volume_heights,
    write_bundle,
)


HEIGHTS = [0.25, 0.75, 1.25, 1.75, 2.25, 2.75]
IDW = {"power": 2.0, "epsilon_distance_power": 1.0e-12, "exact_match_tolerance_m": 1.0e-9}


def _solver(heights=HEIGHTS):
    return {"sionna_rssi": {"radio_map": {"z_height_m": 0.45, "volume_z_heights_m": list(heights)}}}


def _centers(z, nx=3, ny=2, x0=1.0, y0=2.0, step=0.75):
    x = x0 + step * np.arange(nx)
    y = y0 + step * np.arange(ny)
    grid = np.zeros((ny, nx, 3), dtype=float)
    grid[..., 0] = x[None, :]
    grid[..., 1] = y[:, None]
    grid[..., 2] = z
    return grid


def _layers(heights=HEIGHTS, invalid_corner=True):
    layers = []
    for index, z in enumerate(heights):
        mask = np.ones((2, 3), dtype=bool)
        if invalid_corner:
            mask[0, 0] = False
        values = np.where(mask, -60.0 - index, np.nan)
        layers.append({"z_height_m": z, "centers": _centers(z), "rssi_dbm": values, "valid_mask": mask})
    return layers


def test_volume_heights_reads_six_uniform_heights():
    assert volume_heights(_solver()) == HEIGHTS


def test_volume_heights_rejects_duplicate_and_uneven_spacing():
    with pytest.raises(VolumeError, match="오름차순"):
        volume_heights(_solver([0.25, 0.25, 0.75]))
    with pytest.raises(VolumeError, match="간격"):
        volume_heights(_solver([0.25, 0.75, 2.75]))


def test_volume_heights_requires_the_setting():
    with pytest.raises(VolumeError, match="volume_z_heights_m"):
        volume_heights({"sionna_rssi": {"radio_map": {"z_height_m": 0.45}}})


def test_stack_layers_reports_grid_geometry():
    stack = stack_layers(_layers())

    assert stack["shape_zyx"] == [6, 2, 3]
    assert stack["origin_m"] == pytest.approx([1.0, 2.0, 0.25])
    assert stack["spacing_m"] == pytest.approx([0.75, 0.75, 0.5])
    assert stack["rssi_dbm"].shape == (6, 2, 3)


def test_stack_layers_rejects_shifted_xy_grid():
    layers = _layers()
    layers[2]["centers"] = _centers(HEIGHTS[2], x0=1.5)

    with pytest.raises(VolumeError, match="XY 셀 중심"):
        stack_layers(layers)


def test_stack_layers_rejects_center_z_not_matching_height():
    layers = _layers()
    layers[1]["centers"] = _centers(HEIGHTS[1] + 0.3)

    with pytest.raises(VolumeError, match="셀 중심 z"):
        stack_layers(layers)


def test_voxel_positions_follow_zyx_order():
    stack = stack_layers(_layers())
    positions = voxel_positions(stack)

    assert positions.shape == (36, 3)
    assert positions[0] == pytest.approx([1.0, 2.0, 0.25])
    assert positions[1] == pytest.approx([1.75, 2.0, 0.25])
    assert positions[3] == pytest.approx([1.0, 2.75, 0.25])
    assert positions[6] == pytest.approx([1.0, 2.0, 0.75])


def test_build_volume_matches_hand_computed_xyz_idw():
    # 한 층·두 셀만 두고 손으로 계산한 IDW 결과와 맞춘다.
    layer = {
        "z_height_m": 1.0,
        "centers": np.asarray([[[0.0, 0.0, 1.0], [2.0, 0.0, 1.0]]], dtype=float),
        "rssi_dbm": np.asarray([[-70.0, -80.0]], dtype=float),
        "valid_mask": np.asarray([[True, True]], dtype=bool),
    }
    stack = stack_layers([layer])
    positions = np.asarray([[-1.0, 0.0, 1.0], [3.0, 0.0, 1.0]], dtype=float)
    actual = np.asarray([-60.0, -90.0], dtype=float)
    sionna = np.asarray([-65.0, -85.0], dtype=float)

    volume = build_volume(stack, positions, actual, sionna, IDW)

    # 첫 셀: 거리 1과 3 -> 가중치 1과 1/9.
    plain_first = (-60.0 * 1.0 + -90.0 / 9.0) / (1.0 + 1.0 / 9.0)
    residual_first = -70.0 + (5.0 * 1.0 + -5.0 / 9.0) / (1.0 + 1.0 / 9.0)
    assert volume["plain_idw"][0, 0, 0] == pytest.approx(plain_first)
    assert volume["residual_idw"][0, 0, 0] == pytest.approx(residual_first)
    assert volume["raw_sionna"][0, 0, 1] == pytest.approx(-80.0)


def test_build_volume_keeps_invalid_voxels_out_of_every_method():
    stack = stack_layers(_layers())
    positions = np.asarray([[1.0, 2.0, 0.45], [3.0, 3.0, 0.45]], dtype=float)
    volume = build_volume(
        stack, positions, np.asarray([-60.0, -70.0]), np.asarray([-62.0, -75.0]), IDW
    )

    valid = volume["valid_mask"]
    assert valid.shape == (6, 2, 3)
    assert not valid[:, 0, 0].any()
    for name in CHANNELS[:3]:
        assert volume[name].shape == valid.shape
        assert np.all(np.isfinite(volume[name][valid]))
        assert np.all(np.isnan(volume[name][~valid]))


def test_pack_rgba_is_zyx_rgba_float32_without_nan():
    stack = stack_layers(_layers())
    positions = np.asarray([[1.0, 2.0, 0.45], [3.0, 3.0, 0.45]], dtype=float)
    volume = build_volume(
        stack, positions, np.asarray([-60.0, -70.0]), np.asarray([-62.0, -75.0]), IDW
    )
    packed = pack_rgba(volume)

    assert packed.shape == (6, 2, 3, 4)
    assert packed.dtype == np.dtype("<f4")
    assert np.all(np.isfinite(packed))
    # invalid voxel은 네 채널 모두 0, valid voxel은 dBm 값 그대로다.
    assert packed[0, 0, 0].tolist() == [0.0, 0.0, 0.0, 0.0]
    assert packed[0, 1, 2, 3] == 1.0
    assert packed[0, 1, 2, 0] == pytest.approx(volume["raw_sionna"][0, 1, 2], rel=1e-6)
    assert dbm_range(volume)[0] < 0.0


def _bundle_inputs(tmp_path):
    stack = stack_layers(_layers())
    positions = np.asarray([[1.0, 2.0, 0.45], [3.0, 3.0, 0.45]], dtype=float)
    volume = build_volume(
        stack, positions, np.asarray([-60.0, -70.0]), np.asarray([-62.0, -75.0]), IDW
    )
    mesh = tmp_path / "room.obj"
    mesh.write_text("o room\nv 0 0 0\n")
    transform = np.eye(4)
    transform[:3, :3] = np.asarray([[0.0, -0.23, 0.0], [0.0, 0.0, -0.23], [0.23, 0.0, 0.0]])
    return stack, volume, mesh, transform


def test_write_bundle_writes_manifest_and_exact_byte_count(tmp_path):
    stack, volume, mesh, transform = _bundle_inputs(tmp_path)

    manifest = write_bundle(
        tmp_path / "viewer_volume",
        stack,
        volume,
        transform,
        "pnu_3f_corridor_metric_v1",
        {"solver": "sha"},
        occlusion_meshes=[mesh],
    )

    written = json.loads((tmp_path / "viewer_volume" / "manifest.json").read_text())
    assert written == manifest
    assert manifest["paper_evidence_eligible"] is False
    assert manifest["vertical_residual_policy"] == "xyz_idw_from_z_0.45m"
    assert manifest["channels"] == list(CHANNELS)
    assert manifest["grid"]["storage_order"] == "zyx"
    assert manifest["data"]["byte_count"] == 3 * 2 * 6 * 4 * 4
    binary = tmp_path / "viewer_volume" / "volume_rgba_f32.bin"
    assert binary.stat().st_size == manifest["data"]["byte_count"]
    assert manifest["occlusion_meshes"][0]["file"] == "occlusion_meshes/room.obj"


def test_write_bundle_requires_an_occlusion_mesh(tmp_path):
    stack, volume, _mesh, transform = _bundle_inputs(tmp_path)

    with pytest.raises(VolumeError, match="가림용 Proxy Mesh"):
        write_bundle(
            tmp_path / "viewer_volume", stack, volume, transform, "frame", {}, []
        )


def test_write_bundle_rejects_singular_transform(tmp_path):
    stack, volume, mesh, _transform = _bundle_inputs(tmp_path)

    with pytest.raises((VolumeError, np.linalg.LinAlgError)):
        write_bundle(
            tmp_path / "viewer_volume",
            stack,
            volume,
            np.zeros((4, 4)),
            "frame",
            {},
            [mesh],
        )


def test_checked_in_transform_round_trips_within_a_micrometre():
    calibration = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "scenes"
            / "pnu_3f_corridor"
            / "proxy_mesh"
            / "complex_envelope"
            / "calibration.json"
        ).read_text()
    )
    forward = np.asarray(calibration["transform"]["T_scene_from_metric"], dtype=float)
    backward = np.asarray(calibration["transform"]["T_metric_from_scene"], dtype=float)

    point = np.asarray([21.37, 17.83, 0.8, 1.0])
    error = float(np.max(np.abs(backward @ (forward @ point) - point)))

    assert error <= 1.0e-5
