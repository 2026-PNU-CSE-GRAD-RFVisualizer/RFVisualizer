from copy import deepcopy

import pytest

from tools.proxy_placement_editor.editor_state import EditorState, EditorStateError


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
    value = state.ui_document()
    assert value["camera"]["eye"] == [1, 2, 3]
    assert "camera" not in state.document["scenario"]


def test_restore_document_preserves_valid_selection_only():
    state = EditorState(document())
    state.select("one")
    changed = deepcopy(state.document)
    changed["scenario"]["obstacles"] = []
    state.restore_document(changed)
    assert state.selected_object_id is None
