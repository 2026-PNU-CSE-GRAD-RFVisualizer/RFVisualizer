from pathlib import Path


def test_shortcuts_are_bound_to_viewport_not_window(project_root: Path):
    source = (project_root / "tools/proxy_placement_editor/app.py").read_text(
        encoding="utf-8"
    )
    assert "self.viewport.widget.set_on_key(self._on_viewport_key)" in source
    assert "self.window.set_on_key(self._on_key)" not in source
    assert "self.window.set_on_key(self._on_window_key)" in source
