"""Shared pixel metrics for configurable Open3D UI scaling."""

from __future__ import annotations

import math


MIN_UI_SCALE = 0.75
MAX_UI_SCALE = 3.0


def validate_ui_scale(value) -> float:
    """Return one finite UI scale in the supported desktop range."""

    try:
        scale = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("UI 배율은 숫자여야 합니다.") from exc
    if not math.isfinite(scale) or not MIN_UI_SCALE <= scale <= MAX_UI_SCALE:
        raise ValueError(
            "UI 배율은 {:.2f}~{:.2f} 범위의 유한한 값이어야 합니다.".format(
                MIN_UI_SCALE, MAX_UI_SCALE
            )
        )
    return scale


def scaled(value: float, ui_scale: float) -> int:
    """Scale a pixel metric while keeping non-zero values visible."""

    number = float(value)
    result = int(round(number * validate_ui_scale(ui_scale)))
    return max(1, result) if number > 0.0 else 0


def scaled_margins(gui, left, top, right, bottom, ui_scale: float):
    return gui.Margins(
        scaled(left, ui_scale),
        scaled(top, ui_scale),
        scaled(right, ui_scale),
        scaled(bottom, ui_scale),
    )
