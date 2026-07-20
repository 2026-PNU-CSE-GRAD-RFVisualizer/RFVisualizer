"""Configure Open3D's default font with Korean glyph coverage."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional


KOREAN_FONT_CANDIDATES = (
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc"),
    Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
)


def find_korean_font(
    candidates: Iterable[Path] = KOREAN_FONT_CANDIDATES,
) -> Optional[Path]:
    for value in candidates:
        path = Path(value)
        if path.is_file():
            return path
    return None


def configure_korean_font(gui, application) -> Optional[Path]:
    """Add Korean glyphs before the first Open3D window is created."""

    path = find_korean_font()
    if path is None:
        return None
    font = gui.FontDescription()
    font.add_typeface_for_language(str(path), "ko")
    application.set_font(application.DEFAULT_FONT_ID, font)
    return path


def configure_heading_font(gui, application, path: Optional[Path]) -> int:
    """Create a larger heading font before the first window is created."""

    typeface = str(path) if path is not None else gui.FontDescription.SANS_SERIF
    font = gui.FontDescription(typeface, point_size=18)
    if path is not None:
        font.add_typeface_for_language(str(path), "ko")
    return int(application.add_font(font))
