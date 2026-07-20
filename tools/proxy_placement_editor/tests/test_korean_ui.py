import re

import pytest

from tools.proxy_placement_editor.gui.korean_font import find_korean_font
from tools.proxy_placement_editor.gui.properties_panel import PropertiesPanel
from tools.proxy_placement_editor.gui.shortcuts import shortcut_text
from tools.proxy_placement_editor.gui.strings_ko import (
    candidate_label,
    confidence_label,
    format_enabled_errors,
    material_label,
    option_index,
    option_labels,
    option_value,
    semantic_label,
    status_label,
    tr,
)


def _has_hangul(value):
    return bool(re.search(r"[가-힣]", value))


def test_primary_editor_strings_are_korean():
    for key in (
        "window_title",
        "candidate_library",
        "objects",
        "properties",
        "validation",
        "shortcuts",
        "scenario_actions",
        "save",
        "export_preview",
    ):
        assert _has_hangul(tr(key)), key
    assert "PROVISIONAL GEOMETRY" in tr("provisional_warning")


@pytest.mark.parametrize(
    "group,internal,label",
    [
        ("confidence", "measured", "현장 측정"),
        ("geometry_type", "thin_panel", "얇은 판(Thin panel)"),
        ("anchor_mode", "floor_at_xy", "XY 위치의 바닥"),
        ("floor_policy", "anchor_point", "기준점 접촉"),
        ("material", "metal", "금속"),
    ],
)
def test_korean_combo_labels_round_trip_to_internal_values(group, internal, label):
    index = option_index(group, internal)
    assert option_labels(group)[index] == label
    assert option_value(group, index) == internal


def test_unknown_or_invalid_option_handling():
    assert option_index("material", "unknown") == 0
    with pytest.raises(IndexError):
        option_value("material", -1)


def test_candidate_and_object_list_values_are_localized_without_id_changes():
    assert candidate_label("desk_cluster", "Desk Cluster") == "책상 묶음"
    assert candidate_label("future_candidate", "Future") == "Future"
    assert status_label("DISABLED_INCOMPLETE") == "비활성·정보 미완성"
    assert material_label("wood") == "목재"
    assert confidence_label("unset") == "미설정"
    assert semantic_label("blackboard") == "칠판"


def test_korean_material_selection_keeps_phase2b_enum(draft_core):
    obstacle = draft_core.add_candidate("custom_box")
    draft_core.state.select(obstacle["id"])
    panel = PropertiesPanel.__new__(PropertiesPanel)
    panel.updating = False
    panel.core = draft_core
    panel.on_change = lambda: None

    panel._material("금속", option_index("material", "metal"))

    saved = draft_core.state.get_object(obstacle["id"])
    assert saved["material"]["category"] == "metal"
    assert saved["material"]["preset"] == "metal"


def test_validation_dialog_formats_errors_in_korean():
    value = format_enabled_errors(
        [
            {
                "id": "desk_001",
                "errors": ["AABB overlap: wall", "Obstacle is required"],
            }
        ]
    )
    assert value.startswith("활성 객체 오류:")
    assert "축 정렬 경계 상자(AABB) 겹침" in value
    assert "장애물" in value
    assert "desk_001" in value


def test_shortcut_help_is_korean():
    value = shortcut_text()
    assert "왼쪽 클릭" in value
    assert "실행 취소 / 다시 실행" in value
    assert "Return to select mode" not in value


def test_korean_font_finder_uses_first_existing_file(tmp_path):
    missing = tmp_path / "missing.ttf"
    existing = tmp_path / "korean.ttf"
    existing.write_bytes(b"font-placeholder")
    assert find_korean_font((missing, existing)) == existing
    assert find_korean_font((missing,)) is None


def test_legacy_english_widget_literals_are_removed(project_root):
    sources = [project_root / "tools/proxy_placement_editor/app.py"]
    sources.extend((project_root / "tools/proxy_placement_editor/gui").glob("*.py"))
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sources
        if path.name != "strings_ko.py"
    )
    for legacy in (
        'gui.Button("Duplicate")',
        'gui.Button("Delete")',
        'gui.Checkbox("Enabled in Sionna scenario")',
        'gui.CollapsableVert("Validation"',
        'gui.CollapsableVert("Properties"',
        'gui.CollapsableVert("Shortcuts"',
        '"RFVisualizer Phase 2-C Proxy Placement"',
    ):
        assert legacy not in text


def test_section_divider_does_not_depend_on_missing_line_glyph(project_root):
    source = (
        project_root / "tools/proxy_placement_editor/gui/section.py"
    ).read_text(encoding="utf-8")
    assert "━" not in source
    assert "background_color" in source
