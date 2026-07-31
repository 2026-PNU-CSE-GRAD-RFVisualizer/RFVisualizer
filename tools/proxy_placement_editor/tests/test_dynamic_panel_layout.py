from types import SimpleNamespace

from tools.proxy_placement_editor.app import ProxyPlacementApp


def test_refresh_requests_layout_before_redraw_for_dynamic_property_rows():
    app = ProxyPlacementApp.__new__(ProxyPlacementApp)
    calls = []
    report = {"success": True}
    app.core = SimpleNamespace(
        state=SimpleNamespace(selected_object_id="cal_rx_000"),
        validate=lambda: report,
    )
    app.viewport = SimpleNamespace(refresh=lambda value: calls.append(("viewport", value)))
    app.toolbar = SimpleNamespace(refresh=lambda: calls.append(("toolbar",)))
    app.object_panel = SimpleNamespace(
        refresh=lambda state, value: calls.append(("objects", state, value))
    )
    app.properties_panel = SimpleNamespace(
        refresh=lambda selected, value: calls.append(
            ("properties", selected, value)
        )
    )
    app.radio_properties_panel = SimpleNamespace(
        refresh=lambda selected: calls.append(("radio", selected))
    )
    app.validation_panel = SimpleNamespace(
        refresh=lambda value, selected: calls.append(
            ("validation", value, selected)
        )
    )
    app.window = SimpleNamespace(
        set_needs_layout=lambda: calls.append(("layout",)),
        post_redraw=lambda: calls.append(("redraw",)),
    )

    app.refresh()

    assert calls[-2:] == [("layout",), ("redraw",)]
    assert ("radio", "cal_rx_000") in calls
