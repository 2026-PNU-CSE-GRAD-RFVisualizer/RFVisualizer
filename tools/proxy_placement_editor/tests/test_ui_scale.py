from pathlib import Path

import pytest
import yaml

from tools.proxy_placement_editor.gui.metrics import scaled, validate_ui_scale
from tools.proxy_placement_editor.gui.properties_panel import transform_grid_layout


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_editor_config_enlarges_all_ui_by_thirty_percent():
    document = yaml.safe_load(
        (PROJECT_ROOT / "configs/proxy_editor/pnu_classroom_editor.yaml").read_text(
            encoding="utf-8"
        )
    )

    assert document["ui"]["scale"] == pytest.approx(1.3)
    assert scaled(410, document["ui"]["scale"]) == 533
    assert scaled(78, document["ui"]["scale"]) == 101
    assert scaled(16, document["ui"]["scale"]) == 21


def test_ui_scale_rejects_invalid_values():
    assert validate_ui_scale(1.3) == pytest.approx(1.3)
    for value in (None, "large", 0.5, 4.0, float("inf")):
        with pytest.raises(ValueError):
            validate_ui_scale(value)


def test_transform_grid_scales_spacing_without_changing_four_column_layout():
    columns, spacing = transform_grid_layout(1.3)

    assert columns == 4
    assert spacing == 4
