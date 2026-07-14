from tools.proxy_placement_editor.command_stack import (
    CommandStack,
    TransformObjectCommand,
)
from tools.proxy_placement_editor.editor_state import EditorState


def test_one_drag_commits_one_command_and_undo_redo_syncs_document():
    state = EditorState(
        {"scenario": {"obstacles": [{"id": "one", "enabled": False, "x": 0}]}}
    )
    stack = CommandStack()
    before = state.snapshot_document()
    for value in range(20):
        state.get_object("one")["x"] = value
    stack.commit(state, before, TransformObjectCommand, "one")
    assert stack.undo_count == 1
    assert stack.undo() and state.get_object("one")["x"] == 0
    assert stack.redo() and state.get_object("one")["x"] == 19
