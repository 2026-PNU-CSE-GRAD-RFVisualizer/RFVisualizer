import yaml
import pytest

from tools.proxy_placement_editor.candidate_library import (
    CandidateLibraryError,
    instantiate_candidate,
    load_candidate_library,
)


def test_required_templates_exist(project_root):
    values = load_candidate_library(
        project_root / "configs/proxy_editor/pnu_classroom_candidates.yaml"
    )
    assert [value.label for value in values] == [
        "Desk Cluster",
        "Blackboard Panel",
        "Door Panel",
        "Stair Step",
        "AP / TX",
        "Large Metal Object",
        "Custom Box",
        "Custom Thin Panel",
    ]


def test_candidate_add_is_disabled_and_unconfirmed(project_root, placement_scene):
    template = load_candidate_library(
        project_root / "configs/proxy_editor/pnu_classroom_candidates.yaml"
    )[0]
    value = instantiate_candidate(
        template, "desk_cluster_000", placement_scene.containment
    )
    assert value["enabled"] is False
    assert value["placement_status"] == "provisional_unconfirmed"
    assert (
        value["geometry"]["anchor"]["floor_contact_policy"]["type"]
        == "minimum_bottom_vertex_clearance"
    )


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value["candidates"][0]["geometry"].update(default_size_m=None),
        lambda value: value["candidates"][0]["material"].update(category="unknown"),
    ],
)
def test_bad_candidate_schema_is_rejected(tmp_path, project_root, change):
    source = yaml.safe_load(
        (
            project_root / "configs/proxy_editor/pnu_classroom_candidates.yaml"
        ).read_text()
    )
    change(source)
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(source), encoding="utf-8")
    with pytest.raises(CandidateLibraryError):
        load_candidate_library(path)
