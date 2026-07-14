from tools.proxy_placement_editor.scenario_io import (
    load_editor_scenario,
    save_editor_scenario,
)


def test_synthetic_blocker_round_trip_preserves_geometry_material_and_unknown_metadata(
    tmp_path, project_root
):
    source = (
        project_root / "configs/sionna/scenarios/pnu_classroom_synthetic_blocker.yaml"
    )
    original = load_editor_scenario(source)
    original["scenario"]["custom_unknown"] = {"keep": True}
    destination = tmp_path / "roundtrip.yaml"
    save_editor_scenario(original, destination)
    loaded = load_editor_scenario(destination)
    first = original["scenario"]["obstacles"][0]
    second = loaded["scenario"]["obstacles"][0]
    assert second["geometry"] == first["geometry"]
    assert second["material"] == first["material"]
    assert loaded["scenario"]["custom_unknown"] == {"keep": True}
    assert (
        loaded["scenario"]["provenance"]["authoring_method"]
        == "interactive_proxy_placement"
    )


def test_draft_null_geometry_round_trip(tmp_path, project_root):
    source = project_root / "configs/sionna/scenarios/pnu_classroom_proxy_draft.yaml"
    original = load_editor_scenario(source)
    destination = tmp_path / "draft.yaml"
    save_editor_scenario(original, destination)
    loaded = load_editor_scenario(destination)
    assert loaded["scenario"]["obstacles"][0]["geometry"]["size_m"] is None
    assert loaded["scenario"]["obstacles"][0]["enabled"] is False
