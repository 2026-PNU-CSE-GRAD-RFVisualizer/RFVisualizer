import json
from copy import deepcopy

import pytest

from tools.proxy_placement_editor.editor_core import EditorCore, EditorCoreError
from tools.proxy_placement_editor.editor_state import EditorState
from tools.proxy_placement_editor.scenario_io import load_editor_scenario
from tools.proxy_placement_editor.scene_loader import load_placement_scene


def _marker_document():
    return {
        "schema_version": "1.0",
        "scene_id": "classroom_20260723",
        "coordinate_system_id": "pnu_classroom_field_v1",
        "status": "draft",
        "requirements": {
            "transmitter_count": 1,
            "calibration_receiver_count": 1,
            "test_receiver_count": 1,
        },
        "tx": [],
        "rx": [],
    }


def _unified_core(draft_core, tmp_path, project_root):
    room = project_root / "tools/proxy_placement_editor/tests/fixtures/room"
    state = EditorState(
        deepcopy(draft_core.state.document),
        source_path=draft_core.state.source_path,
        marker_document=_marker_document(),
        marker_source_path=tmp_path / "tx_rx.json",
    )
    return EditorCore(
        load_placement_scene(
            room / "room_envelope_metric.json",
            room / "calibration.json",
            room / "room_envelope_metric.obj",
        ),
        state,
        draft_core.candidates,
        tmp_path / "outputs",
    )


def test_ap_tx_and_multiple_rx_share_one_editable_state(draft_core, tmp_path, project_root):
    core = _unified_core(draft_core, tmp_path, project_root)

    access_point = core.add_candidate("ap_tx")
    calibration = core.add_receiver("calibration")
    test = core.add_receiver("test")

    assert core.state.object_kind(access_point["id"]) == "ap_tx"
    assert core.state.object_kind(calibration["id"]) == "rx"
    assert core.state.object_kind(test["id"]) == "rx"
    assert len(core.state.all_objects) == len(core.state.obstacles) + 2

    before = calibration["position_m"][:]
    core.translate(calibration["id"], [0.2, -0.1, 0.3], snap=False)
    assert core.state.get_object(calibration["id"])["position_m"] == pytest.approx(
        [before[0] + 0.2, before[1] - 0.1, before[2] + 0.3]
    )

    core.rotate(access_point["id"], 15.0, axis="z", snap=False)
    core.resize(access_point["id"], 1.2, axis="x", snap=False)
    with pytest.raises(EditorCoreError, match="점 객체"):
        core.rotate(calibration["id"], 10.0)

    report = core.validate()
    assert report["rf_marker_count"] == {
        "tx": 1,
        "calibration_rx": 1,
        "test_rx": 1,
    }
    assert {value["object_kind"] for value in report["objects"]} >= {
        "obstacle",
        "ap_tx",
        "rx",
    }


def test_one_save_writes_scenario_and_marker_contract(draft_core, tmp_path, project_root):
    core = _unified_core(draft_core, tmp_path, project_root)
    access_point = core.add_candidate("ap_tx")
    receiver = core.add_receiver("calibration")
    core.add_receiver("test")
    core.state.get_object(access_point["id"])["display_name"] = "강의실 AP"
    core.state.get_object(receiver["id"])["point_id"] = "cal-main"

    result = core.save(tmp_path / "scenario.yaml")

    assert result["scenario"] == str((tmp_path / "scenario.yaml").resolve())
    assert result["markers"] == str((tmp_path / "tx_rx.json").resolve())
    saved_scenario = load_editor_scenario(tmp_path / "scenario.yaml")
    assert not any(
        isinstance(value.get("rf_transmitter"), dict)
        for value in saved_scenario["scenario"]["obstacles"]
    )
    markers = json.loads((tmp_path / "tx_rx.json").read_text(encoding="utf-8"))
    assert markers["tx"] == [
        {
            "id": access_point["id"],
            "name": "강의실 AP",
            "position_m": pytest.approx(
                [
                    core.state.get_object(access_point["id"])["geometry"]["position_m"][axis]
                    for axis in ("x", "y", "z")
                ]
            ),
            "frequency_hz": 2400000000.0,
            "power_dbm": 20.0,
        }
    ]
    assert {value["point_id"] for value in markers["rx"]} == {
        "cal-main",
        "test-01",
    }


def test_ap_and_rx_require_integrated_marker_contract(draft_core):
    with pytest.raises(EditorCoreError, match="--markers"):
        draft_core.add_candidate("ap_tx")
    with pytest.raises(EditorCoreError, match="--markers"):
        draft_core.add_receiver("test")
