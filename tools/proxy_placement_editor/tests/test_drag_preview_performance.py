from types import SimpleNamespace

from tools.proxy_placement_editor.app import ProxyPlacementApp


def test_drag_preview_updates_one_object_without_validate():
    value = ProxyPlacementApp.__new__(ProxyPlacementApp)
    mesh = object()
    calls = []
    value.core = SimpleNamespace(
        preview_mesh=lambda object_id: calls.append(("build", object_id)) or mesh,
        validate=lambda: (_ for _ in ()).throw(AssertionError("full validate called")),
    )
    value.viewport = SimpleNamespace(
        update_object_preview=lambda object_id, result: calls.append(
            ("viewport", object_id, result)
        )
    )
    value.window = SimpleNamespace(post_redraw=lambda: calls.append(("redraw",)))

    value._refresh_drag_preview("desk_block_example")

    assert calls == [
        ("build", "desk_block_example"),
        ("viewport", "desk_block_example", mesh),
        ("redraw",),
    ]
