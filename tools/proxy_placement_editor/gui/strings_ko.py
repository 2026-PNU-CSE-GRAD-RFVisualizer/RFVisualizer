"""Korean-only display strings for the Proxy Placement Editor.

The values in this module are presentation-only. Scenario keys, enum values,
object IDs, and material identifiers remain unchanged for Phase 2-B
compatibility.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Sequence, Tuple


TEXT: Dict[str, str] = {
    "window_title": "RFVisualizer Phase 2-C 장애물 배치 편집기",
    "provisional_warning": (
        "임시 형상(PROVISIONAL GEOMETRY)\n"
        "현재 실제 크기와 장애물 배치는 현장 실측으로 검증되지 않았습니다.\n"
        "이 장면의 Sionna 결과를 실제 RSSI 정확도로 해석하지 마세요."
    ),
    "candidate_library": "후보 라이브러리",
    "candidate_placeholder": "임시 크기",
    "add_candidate": "비활성 임시 객체 추가",
    "objects": "객체 목록",
    "duplicate": "복제",
    "delete": "삭제",
    "move_up": "위로",
    "move_down": "아래로",
    "show_hide": "표시/숨기기",
    "enabled_in_sionna": "Sionna 시나리오에서 활성화",
    "properties": "속성",
    "validation": "검증",
    "not_validated": "검증하지 않음",
    "validation_pass": "통과",
    "validation_error": "오류",
    "shortcuts": "단축키",
    "scenario_actions": "시나리오 및 Sionna",
    "validate": "검증",
    "save": "저장",
    "save_as": "다른 이름으로 저장",
    "export_preview": "미리보기 내보내기",
    "build_sionna": "Sionna 장면 생성",
    "run_ab": "A/B 실행",
    "open_output": "출력 폴더 열기",
    "select": "선택",
    "move": "이동",
    "rotate": "회전",
    "scale": "크기 조절",
    "axis_free": "자유/XY",
    "coordinate_space": "좌표계",
    "space_world": "World",
    "space_local": "Local",
    "display_mode": "배경",
    "display_both": "둘 다",
    "display_point_cloud": "Point Cloud만",
    "display_proxy_mesh": "Proxy Mesh만",
    "point_size": "점 크기",
    "snap": "스냅(Snap)",
    "move_unit": "이동 m",
    "rotation_unit": "회전 °",
    "size_unit": "크기 m",
    "fps_idle": "우클릭+WASD: 1인칭 이동",
    "fps_active": "1인칭 이동 중 · WASD/Shift",
    "object_id": "객체 ID",
    "display_name": "표시 이름",
    "semantic_class": "의미 분류",
    "purpose": "용도",
    "measurement_source": "측정 출처",
    "notes": "메모",
    "confidence": "확신도",
    "physical_object": "실제 물체",
    "geometry_type": "형상 종류",
    "anchor_mode": "기준점 방식(Anchor)",
    "floor_policy": "바닥 접촉 방식",
    "floor_clearance": "바닥 여유 거리 m",
    "position": "위치 m",
    "size": "크기 m",
    "rotation": "롤/피치/요 (Roll/Pitch/Yaw)",
    "material_category": "재질 분류",
    "material_thickness": "재질 두께 m",
    "scattering": "산란 계수",
    "fallback_policy": "대체 재질 없음: Phase 2-B에서 엄격하게 확인",
    "select_renderable": "표시 가능한 객체를 선택하면 좌표 변환을 보여줍니다.",
    "incomplete_geometry": "객체 형상 정보가 완전하지 않습니다.",
    "metric_transform": "미터 좌표 변환",
    "scene_transform": "PGSR 장면 좌표 변환",
    "round_trip": "좌표 왕복 오차",
    "floor": "바닥",
    "ceiling": "천장",
    "wall": "벽",
    "cannot_enable": "객체를 활성화할 수 없음",
    "scenario_validation": "시나리오 검증",
    "enabled_object_errors": "활성 객체 오류",
    "saved": "저장됨",
    "save_blocked": "저장할 수 없음",
    "save_dialog": "임시 시나리오 저장",
    "yaml_scenario": "YAML 시나리오",
    "save_as_blocked": "다른 이름으로 저장할 수 없음",
    "preview_created": "미리보기 생성",
    "preview_failed": "미리보기 생성 실패",
    "external_command": "외부 명령",
    "exit_code": "종료 코드",
    "build_blocked": "Sionna 장면을 생성할 수 없음",
    "experiment_required": "--experiment 경로를 지정해야 합니다.",
    "open_output_failed": "출력 폴더를 열 수 없음",
}


OPTIONS: Dict[str, Sequence[Tuple[str, str]]] = {
    "confidence": (
        ("unset", "미설정"),
        ("estimated_from_reference", "참조 형상에서 추정"),
        ("measured", "현장 측정"),
        ("synthetic", "합성 검증용"),
    ),
    "geometry_type": (
        ("box", "상자(Box)"),
        ("thin_panel", "얇은 판(Thin panel)"),
        ("mesh", "삼각형 메시(Mesh)"),
    ),
    "anchor_mode": (
        ("center", "중심"),
        ("bottom_center", "아래쪽 중심"),
        ("floor_at_xy", "XY 위치의 바닥"),
        ("explicit_transform", "변환 행렬 직접 지정"),
    ),
    "floor_policy": (
        ("anchor_point", "기준점 접촉"),
        ("minimum_bottom_vertex_clearance", "최저 꼭짓점 여유 거리"),
    ),
    "material": (
        ("concrete", "콘크리트"),
        ("wood", "목재"),
        ("metal", "금속"),
        ("glass", "유리"),
    ),
}


CANDIDATE_LABELS = {
    "desk_cluster": "책상 묶음",
    "blackboard_panel": "칠판 판",
    "door_panel": "문 판",
    "large_metal_object": "대형 금속 물체",
    "custom_box": "사용자 정의 상자",
    "custom_thin_panel": "사용자 정의 얇은 판",
}


STATUS_LABELS = {
    "VALID": "유효",
    "WARNING": "경고",
    "INVALID": "유효하지 않음",
    "INCOMPLETE": "정보 미완성",
    "DISABLED": "비활성",
    "DISABLED_INVALID": "비활성·유효하지 않음",
    "DISABLED_INCOMPLETE": "비활성·정보 미완성",
}


SEMANTIC_LABELS = {
    "desk_cluster": "책상 묶음",
    "blackboard": "칠판",
    "door": "문",
    "large_equipment": "대형 장비",
    "custom_box": "사용자 정의 상자",
    "custom_panel": "사용자 정의 판",
}


def tr(key: str, **values: Any) -> str:
    """Return a Korean UI string and interpolate named values."""

    value = TEXT[key]
    return value.format(**values) if values else value


def option_values(group: str) -> List[str]:
    return [value for value, _ in OPTIONS[group]]


def option_labels(group: str) -> List[str]:
    return [label for _, label in OPTIONS[group]]


def option_index(group: str, value: str, default: int = 0) -> int:
    values = option_values(group)
    return values.index(value) if value in values else default


def option_value(group: str, index: int) -> str:
    values = option_values(group)
    if index < 0 or index >= len(values):
        raise IndexError("UI option index is out of range")
    return values[index]


def candidate_label(candidate_id: str, fallback: str) -> str:
    return CANDIDATE_LABELS.get(candidate_id, fallback)


def status_label(value: Any) -> str:
    source = str(value)
    return STATUS_LABELS.get(source, source)


def material_label(value: Any) -> str:
    source = str(value)
    index = option_index("material", source, default=-1)
    return option_labels("material")[index] if index >= 0 else source


def confidence_label(value: Any) -> str:
    source = str(value)
    index = option_index("confidence", source, default=-1)
    return option_labels("confidence")[index] if index >= 0 else source


def semantic_label(value: Any) -> str:
    source = str(value)
    return SEMANTIC_LABELS.get(source, source)


def localize_message(message: Any) -> str:
    """Translate common validation fragments without changing stored reports."""

    value = str(message)
    replacements: Iterable[Tuple[str, str]] = (
        ("AABB overlap:", "축 정렬 경계 상자(AABB) 겹침:"),
        ("Obstacle", "장애물"),
        ("object", "객체"),
        ("must be", "이어야 합니다:"),
        ("is required", "항목이 필요합니다"),
    )
    for source, target in replacements:
        value = value.replace(source, target)
    return value


def format_enabled_errors(errors: Sequence[Dict[str, Any]]) -> str:
    lines = [tr("enabled_object_errors") + ":"]
    for record in errors:
        object_id = str(record.get("id", "?"))
        messages = record.get("errors") or [tr("validation_error")]
        lines.append("- {}: {}".format(object_id, localize_message(messages[0])))
        lines.extend("  · " + localize_message(value) for value in messages[1:])
    return "\n".join(lines)
