"""Single source of truth for UI shortcut labels."""

SHORTCUTS = [
    ("왼쪽 클릭", "장애물 선택, 빈 공간 드래그는 카메라 회전"),
    ("우클릭 드래그 + WASD", "시선 방향 전후좌우 이동, Shift는 빠른 이동"),
    ("Ctrl+왼쪽 / 가운데", "Open3D 카메라 평행 이동"),
    ("Alt+왼쪽", "Open3D 카메라 궤도 회전"),
    ("휠", "확대/축소"),
    ("G / R / S", "이동 축 / 회전 링 / 로컬 크기 축 표시"),
    ("축·회전 링 드래그", "선택한 X/Y/Z 방향으로만 객체 변형"),
    ("Shift / drag 도중 Ctrl", "미세 이동 / 스냅(Snap)"),
    ("F / Home", "선택 객체 / 방 전체 화면 맞춤"),
    ("Delete / Ctrl+D", "선택 객체 삭제 / 복제"),
    ("Ctrl+Z / Ctrl+Y", "실행 취소 / 다시 실행"),
    ("Ctrl+S", "시나리오 검증 후 저장"),
    ("V / H", "배경 표시 모드 순환 / 선택 객체 표시 전환"),
    ("1 / 3 / 7", "정면 / 측면 / 위 보기"),
    ("Esc", "선택 모드로 돌아가기"),
]


def shortcut_text() -> str:
    return "\n".join(
        "{}: {}".format(key, description) for key, description in SHORTCUTS
    )
