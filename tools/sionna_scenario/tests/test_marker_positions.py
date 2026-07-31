import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import tools.sionna_scenario.scenario_builder as scenario_builder


def _room_metadata():
    return {
        "coordinate_system": {"id": "pnu_classroom_field_v1"},
        "normalized_plane_equations": {
            "floor": [0.0, 0.0, 1.0, 0.0],
            "ceiling": [0.0, 0.0, 1.0, -3.0],
            "walls": [
                [1.0, 0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0, -10.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, -10.0],
            ],
        },
        "interior_point": [5.0, 5.0, 1.5],
        "bounds": {"min": [0.0, 0.0, 0.0], "max": [10.0, 10.0, 3.0]},
    }


def _settings():
    return {
        "scene": {"carrier_frequency_hz": 5.0e9},
        "transmitter": {
            "name": "stale_tx",
            "position_mode": "explicit",
            "position_m": [5.0, 5.0, 1.0],
            "power_dbm": 1.0,
        },
        "receivers": [{"name": "stale_rx", "position_m": [6.0, 5.0, 1.0]}],
        "placement": {
            "mode": "resolved",
            "clearance_m": 0.1,
            "minimum_device_separation_m": 0.2,
        },
    }


def _markers():
    return {
        "schema_version": "1.0",
        "scene_id": "classroom_20260723",
        "coordinate_system_id": "pnu_classroom_field_v1",
        "status": "ready",
        "requirements": {
            "transmitter_count": 1,
            "calibration_receiver_count": 1,
            "test_receiver_count": 1,
        },
        "tx": [
            {
                "id": "ap_tx_000",
                "name": "Field AP",
                "position_m": [2.0, 2.0, 1.0],
                "frequency_hz": 2.4e9,
                "power_dbm": 20.0,
            }
        ],
        "rx": [
            {
                "id": "cal_rx_000",
                "point_id": "cal-01",
                "name": "Calibration 1",
                "role": "calibration",
                "position_m": [4.0, 2.0, 1.0],
            },
            {
                "id": "test_rx_000",
                "point_id": "test-00",
                "name": "Test 0",
                "role": "test",
                "position_m": [6.0, 2.0, 1.0],
            },
        ],
    }


def test_prepare_scenario_uses_marker_contract_as_position_source(
    monkeypatch, tmp_path: Path
):
    marker_path = tmp_path / "tx_rx.json"
    marker_path.write_text(json.dumps(_markers()), encoding="utf-8")
    identity = np.eye(4).tolist()
    metric_scene = SimpleNamespace(
        metric_metadata=_room_metadata(),
        calibration={
            "coordinate_system_id": "pnu_classroom_field_v1",
            "transform": {
                "T_metric_from_scene": identity,
                "T_scene_from_metric": identity,
            },
        },
    )
    monkeypatch.setattr(
        scenario_builder,
        "load_phase2a_config",
        lambda path: {"sionna_smoke_test": _settings()},
    )
    monkeypatch.setattr(
        scenario_builder, "load_metric_scene", lambda settings: metric_scene
    )
    monkeypatch.setattr(
        scenario_builder, "obstacles_from_document", lambda document, source_path: []
    )
    monkeypatch.setattr(
        scenario_builder,
        "resolve_obstacle_materials",
        lambda sources: {"materials": []},
    )
    document = {
        "_source_path": str(tmp_path / "scenario.yaml"),
        "scenario": {
            "_phase2a_config_path": str(tmp_path / "phase2a.yaml"),
            "obstacles": [],
        },
    }

    prepared = scenario_builder.prepare_scenario(document, marker_path)

    assert prepared.position_source == "tx_rx_marker_contract"
    assert prepared.marker_source_path == marker_path.resolve()
    assert prepared.settings["scene"]["carrier_frequency_hz"] == 2.4e9
    assert prepared.settings["transmitter"]["name"] == "ap_tx_000"
    assert prepared.settings["transmitter"]["power_dbm"] == 20.0
    assert [value["name"] for value in prepared.positions] == [
        "ap_tx_000",
        "cal-01",
        "test-00",
    ]
    assert [value.get("role") for value in prepared.positions[1:]] == [
        "calibration",
        "test",
    ]
    assert all(not value["used_fallback"] for value in prepared.positions)

