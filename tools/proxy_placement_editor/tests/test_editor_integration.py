from pathlib import Path

from tools.proxy_placement_editor.scenario_io import load_editor_scenario


def test_headless_add_transform_validate_save_reload_preview(draft_core, tmp_path):
    value = draft_core.add_candidate("desk_cluster")
    draft_core.translate(value["id"], [0.2, -0.1, 0.0], snap=False)
    draft_core.rotate(value["id"], 10.0, snap=False)
    draft_core.resize(value["id"], 0.9, snap=False)
    draft_core.set_enabled(value["id"], True)
    assert draft_core.validate()["success"]
    scenario = tmp_path / "provisional.yaml"
    result = draft_core.save(scenario)
    assert Path(result["files"]["obstacles_metric"]).is_file()
    loaded = load_editor_scenario(scenario)
    assert any(
        item["id"] == value["id"] and item["enabled"]
        for item in loaded["scenario"]["obstacles"]
    )
    files = draft_core.export_preview(tmp_path / "preview")
    assert all(Path(path).is_file() for path in files.values())


def test_autosave_does_not_overwrite_source(draft_core):
    before = draft_core.state.source_path.read_bytes()
    paths = draft_core.autosave()
    assert Path(paths["scenario"]).is_file()
    assert draft_core.state.source_path.read_bytes() == before


def test_core_rename_reorder_and_visibility_state(draft_core):
    first = draft_core.add_candidate("custom_box")
    second = draft_core.add_candidate("custom_box")
    draft_core.rename(second["id"], "renamed_box")
    draft_core.reorder("renamed_box", -1)
    ids = [value["id"] for value in draft_core.state.obstacles]
    assert ids.index("renamed_box") < ids.index(first["id"])
    assert (
        draft_core.state.get_object("renamed_box")["export"]["object_name"]
        == "renamed_box"
    )
    draft_core.state.object_visibility["renamed_box"] = False
    assert draft_core.state.ui_document()["object_visibility"]["renamed_box"] is False
