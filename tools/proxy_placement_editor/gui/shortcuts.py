"""Single source of truth for UI shortcut labels."""

SHORTCUTS = [
    ("Left click", "Select nearest obstacle; empty space clears selection"),
    ("RMB drag + WASD", "FPS look and horizontal movement; Shift sprints"),
    ("Alt+Left / Middle", "Orbit / pan with Open3D camera controls"),
    ("Wheel", "Zoom"),
    ("G / R / S", "Translate / rotate / scale mode"),
    ("X / Y / Z", "Constrain active transform axis"),
    ("Shift / Ctrl", "Fine movement / snap during drag"),
    ("F / Home", "Frame selection / whole room"),
    ("Delete / Ctrl+D", "Delete / duplicate selection"),
    ("Ctrl+Z / Ctrl+Y", "Undo / redo"),
    ("Ctrl+S", "Validate and save scenario"),
    ("V / H", "Toggle reference / selected object visibility"),
    ("1 / 3 / 7", "Front / side / top view"),
    ("Esc", "Return to select mode"),
]


def shortcut_text() -> str:
    return "\n".join(
        "{}: {}".format(key, description) for key, description in SHORTCUTS
    )
