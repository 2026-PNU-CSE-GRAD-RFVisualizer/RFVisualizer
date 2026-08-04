from copy import deepcopy

from tools.proxy_placement_editor.scenario_io import load_editor_scenario
from tools.proxy_placement_editor.validation_bridge import validate_document


def test_draft_incomplete_disabled_objects_do_not_fail(project_root, placement_scene):
    document = load_editor_scenario(
        project_root / "scenes/pnu_classroom/configs/sionna/proxy_draft.yaml"
    )
    report = validate_document(document, placement_scene)
    assert report["success"]
    assert report["renderable_obstacle_count"] == 0
    assert all(value["status"] == "DISABLED_INCOMPLETE" for value in report["objects"])


def test_synthetic_result_matches_phase2b_checks(project_root, placement_scene):
    document = load_editor_scenario(
        project_root / "scenes/pnu_classroom/configs/sionna/synthetic_blocker.yaml"
    )
    record = validate_document(document, placement_scene)["objects"][0]
    assert record["status"] == "VALID"
    assert all(record["phase2b_validation"]["checks"].values())
    assert record["material"]["category"] == "wood"


def test_collision_is_warning_not_error(draft_core):
    first = draft_core.add_candidate("desk_cluster")
    second = draft_core.add_candidate("desk_cluster")
    draft_core.set_enabled(first["id"], True)
    draft_core.set_enabled(second["id"], True)
    report = draft_core.validate()
    assert report["success"]
    records = [value for value in report["objects"] if value["enabled"]]
    assert all(value["collision_warnings"] for value in records)
    assert all(value["status"] == "WARNING" for value in records)


def test_outside_enabled_object_fails(draft_core):
    value = draft_core.add_candidate("custom_box")
    updated = deepcopy(value)
    updated["geometry"]["position_m"] = {"x": 100.0, "y": 100.0}
    draft_core.replace_object(value["id"], updated)
    draft_core.set_enabled(value["id"], True)
    report = draft_core.validate()
    assert not report["success"]
    assert report["objects"][-1]["status"] == "INVALID"
