from types import SimpleNamespace

from tools.proxy_placement_editor.app import ProxyPlacementApp
from tools.proxy_placement_editor.gui.validation_panel import (
    LOG_WRAP_COLUMNS,
    MAX_LOG_LINES,
    ValidationPanel,
    wrap_log_lines,
)


def test_long_save_path_is_wrapped_to_sidebar_safe_lines():
    line = "저장됨: /data/RFVisualizer/outputs/proxy_editor/very_long_scenario.yaml"

    wrapped = wrap_log_lines(line)

    assert "".join(wrapped) == line
    assert all(len(value) <= LOG_WRAP_COLUMNS for value in wrapped)
    assert len(wrapped) > 1


def test_validation_log_uses_bounded_list_and_reveals_latest_line():
    panel = ValidationPanel.__new__(ValidationPanel)
    panel._log_lines = []
    panel.log = SimpleNamespace(
        items=[],
        selected_index=-1,
        set_items=lambda items: setattr(panel.log, "items", list(items)),
    )

    for index in range(MAX_LOG_LINES + 3):
        panel.append_log("결과 {}".format(index))

    assert len(panel.log.items) == MAX_LOG_LINES
    assert panel.log.items[-1] == "결과 {}".format(MAX_LOG_LINES + 2)
    assert panel.log.selected_index == len(panel.log.items) - 1


def test_append_validation_log_requests_layout_and_redraw():
    calls = []
    app = ProxyPlacementApp.__new__(ProxyPlacementApp)
    app.validation_panel = SimpleNamespace(
        append_log=lambda line: calls.append(("append", line))
    )
    app.window = SimpleNamespace(
        set_needs_layout=lambda: calls.append(("layout",)),
        post_redraw=lambda: calls.append(("redraw",)),
    )

    app._append_validation_log("저장됨")

    assert calls == [("append", "저장됨"), ("layout",), ("redraw",)]
