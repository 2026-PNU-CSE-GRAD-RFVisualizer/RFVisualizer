import pytest

from tools.proxy_placement_editor.editor_config import load_editor_config


def write_config(tmp_path, text):
    path = tmp_path / "editor.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_partial_fps_config_preserves_defaults(tmp_path):
    config = load_editor_config(
        write_config(
            tmp_path,
            """
navigation:
  fps:
    movement_speed_mps: 2.25
""",
        )
    )
    fps = config["navigation"]["fps"]
    assert fps["movement_speed_mps"] == 2.25
    assert fps["sprint_multiplier"] == 3.0
    assert fps["horizontal_only"] is True


@pytest.mark.parametrize(
    "key,value",
    [
        ("movement_speed_mps", 0),
        ("movement_speed_mps", ".nan"),
        ("sprint_multiplier", -1),
        ("max_frame_delta_seconds", 0),
    ],
)
def test_fps_numeric_settings_must_be_positive_finite(tmp_path, key, value):
    path = write_config(
        tmp_path,
        "navigation:\n  fps:\n    {}: {}\n".format(key, value),
    )
    with pytest.raises(ValueError, match="finite 양수"):
        load_editor_config(path)


def test_fps_flags_must_be_boolean(tmp_path):
    path = write_config(
        tmp_path,
        "navigation:\n  fps:\n    enabled: yes-please\n",
    )
    with pytest.raises(ValueError, match="enabled는 bool"):
        load_editor_config(path)
