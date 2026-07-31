from copy import deepcopy
from itertools import product
from types import SimpleNamespace

import pytest

from tools.proxy_placement_editor.editor_state import EditorState, EditorStateError
from tools.proxy_placement_editor.gui.object_list_panel import ObjectListPanel
from tools.proxy_placement_editor.gui.toolbar import PlacementToolbar
from tools.proxy_placement_editor.gui.viewport import background_layer_visibility


def document():
    return {"scenario": {"obstacles": [{"id": "one", "enabled": False}]}}


def test_add_delete_duplicate_select_and_reorder():
    state = EditorState(document())
    state.select("one")
    state.add_object({"id": "two", "enabled": False})
    duplicate = state.duplicate_object("two")
    assert duplicate["id"] == "two_copy"
    assert duplicate["enabled"] is False
    state.reorder("one", 2)
    assert [value["id"] for value in state.obstacles] == ["two", "two_copy", "one"]
    assert state.delete_object("two")["id"] == "two"


def test_duplicate_id_is_rejected():
    state = EditorState(document())
    with pytest.raises(EditorStateError):
        state.add_object({"id": "one", "enabled": False})


def test_ui_state_is_separate_from_scenario():
    state = EditorState(document())
    state.camera = {"eye": [1, 2, 3]}
    state.point_cloud_visible = False
    state.proxy_mesh_visible = True
    state.pgsr_output_mesh_visible = False
    value = state.ui_document()
    assert value["camera"]["eye"] == [1, 2, 3]
    assert value["layer_visibility"] == {
        "point_cloud": False,
        "proxy_mesh": True,
        "pgsr_output_mesh": False,
    }
    assert "camera" not in state.document["scenario"]


def test_restore_document_preserves_valid_selection_only():
    state = EditorState(document())
    state.select("one")
    changed = deepcopy(state.document)
    changed["scenario"]["obstacles"] = []
    state.restore_document(changed)
    assert state.selected_object_id is None


def test_ctrl_selection_toggles_items_and_keeps_last_clicked_primary():
    state = EditorState(document())
    state.add_object({"id": "two", "enabled": False})
    state.select("one")
    state.select("two", additive=True)

    assert state.selected_object_ids == ["one", "two"]
    assert state.selected_object_id == "two"

    state.select("two", additive=True)
    assert state.selected_object_ids == ["one"]
    assert state.selected_object_id == "one"


def test_object_list_forwards_ctrl_state_to_selection_callback():
    panel = ObjectListPanel.__new__(ObjectListPanel)
    panel.updating = False
    panel.ids = ["one", "two"]
    panel.list = SimpleNamespace(selected_index=1)
    panel.is_ctrl_down = lambda: True
    selections = []
    panel.on_select = lambda object_id, additive: selections.append(
        (object_id, additive)
    )

    panel._selected("two", False)

    assert selections == [("two", True)]


def test_delete_and_restore_filter_multi_selection_without_losing_the_rest():
    state = EditorState(document())
    state.add_object({"id": "two", "enabled": False})
    state.select("one")
    state.select("two", additive=True)

    state.delete_object("two")
    assert state.selected_object_ids == ["one"]
    assert state.selected_object_id == "one"

    state.add_object({"id": "two", "enabled": False})
    state.select("one", additive=True)
    changed = deepcopy(state.document)
    changed["scenario"]["obstacles"] = [
        value
        for value in changed["scenario"]["obstacles"]
        if value["id"] == "one"
    ]
    state.restore_document(changed)
    assert state.selected_object_ids == ["one"]
    assert state.selected_object_id == "one"


def test_all_background_layer_combinations_are_independent():
    state = EditorState(document())
    for point_cloud, proxy_mesh, pgsr_output_mesh in product((False, True), repeat=3):
        state.point_cloud_visible = point_cloud
        state.proxy_mesh_visible = proxy_mesh
        state.pgsr_output_mesh_visible = pgsr_output_mesh
        assert background_layer_visibility(state) == {
            "point_cloud": point_cloud,
            "room": proxy_mesh,
            "pgsr_output_mesh": pgsr_output_mesh,
        }


def test_toolbar_visibility_callbacks_change_only_their_layer():
    state = EditorState(document())
    toolbar = PlacementToolbar.__new__(PlacementToolbar)
    toolbar.state = state
    toolbar.updating = False
    changes = []
    toolbar.on_change = lambda: changes.append(True)

    toolbar._point_cloud_visibility(False)
    visibility = (
        state.point_cloud_visible,
        state.proxy_mesh_visible,
        state.pgsr_output_mesh_visible,
    )
    assert visibility == (
        False,
        True,
        True,
    )
    toolbar._proxy_mesh_visibility(False)
    toolbar._pgsr_output_mesh_visibility(False)
    visibility = (
        state.point_cloud_visible,
        state.proxy_mesh_visible,
        state.pgsr_output_mesh_visible,
    )
    assert visibility == (
        False,
        False,
        False,
    )
    assert len(changes) == 3
