from pathlib import Path

import numpy as np

from tools.proxy_placement_editor.scene_loader import load_placement_scene
from tools.rf_experiment.contracts import load_json
from tools.rf_experiment.proxy_scene import build_proxy_envelope, export_proxy_envelope
from tools.sionna_smoke_test.metric_scene_loader import load_metric_scene


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCENE_PATH = (
    PROJECT_ROOT
    / "tools"
    / "rf_experiment"
    / "tests"
    / "fixtures"
    / "configs"
    / "scene.json"
)
LEGACY_DIRECTORY = PROJECT_ROOT / "tools" / "rf_experiment" / "tests" / "fixtures" / "room"


def _envelope():
    return build_proxy_envelope(
        load_json(SCENE_PATH),
        load_json(LEGACY_DIRECTORY / "room_envelope_metric.json"),
        load_json(LEGACY_DIRECTORY / "calibration.json"),
    )


def test_measured_base_envelope_uses_positive_exact_xy_bounds():
    envelope = _envelope()

    assert np.allclose(
        envelope.bottom,
        [[0.0, 0.0, 0.0], [15.4, 0.0, 0.0], [15.4, 10.8, 0.75], [0.0, 10.8, 0.75]],
    )
    assert envelope.topology["closed_manifold_success"] is True
    assert envelope.topology["signed_volume"] > 0.0
    assert envelope.assumptions["floor_model_ready_for_final_experiment"] is False


def test_reference_alignment_is_invertible_and_explicitly_approximate():
    envelope = _envelope()
    transform = envelope.calibration["transform"]
    forward = np.asarray(transform["T_metric_from_scene"])
    inverse = np.asarray(transform["T_scene_from_metric"])

    assert np.max(np.abs(forward @ inverse - np.eye(4))) < 1.0e-8
    assert transform["reference_corner_fit"]["maximum_corner_fit_error_m"] > 0.0
    assert transform["legacy_bottom_corner_order_for_field"] == [2, 3, 0, 1]
    assert transform["origin_legacy_bottom_corner_index"] == 2
    assert transform["origin_field_corner_index"] == 0
    assert transform["reference_corner_fit"]["anchor_error_m"] < 1.0e-9
    assert envelope.calibration["status"] == "provisional"


def test_reference_alignment_anchors_door_corner_at_exact_origin():
    envelope = _envelope()
    legacy = load_json(LEGACY_DIRECTORY / "room_envelope_metric.json")
    transform = np.asarray(
        envelope.calibration["transform"]["T_field_from_legacy_metric"]
    )
    door_corner = np.asarray([*legacy["bottom_corners"][2], 1.0])

    assert np.allclose((transform @ door_corner)[:3], [0.0, 0.0, 0.0], atol=1.0e-9)
    assert envelope.assumptions["resolved_front_clearance_m"] == np.mean(
        [
            legacy["top_corners"][index][2]
            - legacy["bottom_corners"][index][2]
            for index in (2, 3)
        ]
    )


def test_exported_envelope_loads_in_existing_editor_and_sionna_pipeline(tmp_path):
    report = export_proxy_envelope(
        SCENE_PATH,
        LEGACY_DIRECTORY / "room_envelope_metric.json",
        LEGACY_DIRECTORY / "calibration.json",
        tmp_path,
    )
    files = report["files"]

    placement = load_placement_scene(
        Path(files["metric_envelope_json"]),
        Path(files["calibration_json"]),
        Path(files["metric_obj"]),
    )
    metric_scene = load_metric_scene(
        {
            "input": {
                "metric_obj": files["metric_obj"],
                "metric_mtl": files["metric_mtl"],
                "metric_json": files["metric_envelope_json"],
                "calibration_json": files["calibration_json"],
            }
        }
    )
    floor_z, ceiling_z = placement.containment.floor_ceiling_z(7.7, 5.4)
    point = np.asarray([7.7, 5.4, (floor_z + ceiling_z) / 2.0])

    assert placement.containment.inspect_point(point, 0.0)["inside_room"] is True
    assert len(metric_scene.objects) == 6
    assert Path(files["preview_top"]).is_file()
    assert Path(files["preview_perspective"]).is_file()
