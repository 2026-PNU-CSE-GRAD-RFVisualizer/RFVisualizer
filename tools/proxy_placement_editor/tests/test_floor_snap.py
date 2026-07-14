from copy import deepcopy

import numpy as np

from tools.proxy_placement_editor.floor_snap import floor_contact_report
from tools.proxy_placement_editor.scenario_io import load_editor_scenario


def test_legacy_anchor_point_keeps_phase2b_synthetic_result(
    project_root, placement_scene
):
    document = load_editor_scenario(
        project_root / "configs/sionna/scenarios/pnu_classroom_synthetic_blocker.yaml"
    )
    report = floor_contact_report(
        document["scenario"]["obstacles"][0], placement_scene.containment
    )
    assert report["policy"] == "anchor_point"
    assert np.isclose(report["minimum_bottom_vertex_clearance_m"], 0.011491880954898559)


def test_minimum_bottom_vertex_policy_hits_configured_clearance(
    project_root, placement_scene
):
    document = load_editor_scenario(
        project_root / "configs/sionna/scenarios/pnu_classroom_synthetic_blocker.yaml"
    )
    value = deepcopy(document["scenario"]["obstacles"][0])
    value["purpose"] = "classroom_proxy"
    value["physical_object"] = True
    value["confidence"] = "estimated_from_reference"
    value["geometry"].pop("floor_clearance_m", None)
    value["geometry"]["rotation_deg"]["yaw"] = 31.0
    value["geometry"]["anchor"]["floor_contact_policy"] = {
        "type": "minimum_bottom_vertex_clearance",
        "clearance_m": 0.02,
    }
    report = floor_contact_report(value, placement_scene.containment)
    assert report["policy"] == "minimum_bottom_vertex_clearance"
    assert np.isclose(report["minimum_bottom_vertex_clearance_m"], 0.02, atol=1e-9)
