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
    assert fps["mouse_sensitivity_deg_per_pixel"] == 0.15
    assert fps["maximum_pitch_deg"] == 85.0
    assert fps["horizontal_only"] is False
    assert config["navigation"]["initial_camera"] == {
        "mode": "origin",
        "eye_offset_m": [3.0, 3.0, 2.2],
        "target_offset_m": [0.5, 0.5, 0.5],
    }


@pytest.mark.parametrize(
    "key,value",
    [
        ("movement_speed_mps", 0),
        ("mouse_sensitivity_deg_per_pixel", 0),
        ("maximum_pitch_deg", 90),
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
    with pytest.raises(ValueError):
        load_editor_config(path)


def test_fps_flags_must_be_boolean(tmp_path):
    path = write_config(
        tmp_path,
        "navigation:\n  fps:\n    enabled: yes-please\n",
    )
    with pytest.raises(ValueError, match="enabled는 bool"):
        load_editor_config(path)


@pytest.mark.parametrize(
    "text",
    (
        "navigation:\n  initial_camera:\n    mode: invalid\n",
        "navigation:\n  initial_camera:\n    eye_offset_m: [1, 2]\n",
        "navigation:\n  initial_camera:\n    target_offset_m: [0, .nan, 0]\n",
        "navigation:\n  initial_camera:\n    eye_offset_m: [1, 1, 1]\n    target_offset_m: [1, 1, 1]\n",
    ),
)
def test_invalid_initial_camera_is_rejected(tmp_path, text):
    with pytest.raises(ValueError):
        load_editor_config(write_config(tmp_path, text))


def test_reference_display_defaults_and_overrides(tmp_path):
    default = load_editor_config()
    assert default["reference"]["point_cloud_visible"] is True
    assert default["reference"]["proxy_mesh_visible"] is True
    assert default["reference"]["pgsr_output_mesh_visible"] is True
    assert default["reference"]["point_size"] == 2.0
    config = load_editor_config(
        write_config(
            tmp_path,
            "reference:\n  proxy_mesh_visible: false\n  point_size: 4.5\n",
        )
    )
    assert config["reference"]["point_cloud_visible"] is True
    assert config["reference"]["proxy_mesh_visible"] is False
    assert config["reference"]["pgsr_output_mesh_visible"] is True
    assert config["reference"]["point_size"] == 4.5


def test_legacy_display_mode_maps_to_independent_visibility(tmp_path):
    config = load_editor_config(
        write_config(
            tmp_path,
            "reference:\n  display_mode: point_cloud\n  visible: false\n",
        )
    )
    assert config["reference"]["point_cloud_visible"] is False
    assert config["reference"]["proxy_mesh_visible"] is False
    assert config["reference"]["pgsr_output_mesh_visible"] is True


@pytest.mark.parametrize(
    "text",
    (
        "reference:\n  point_size: 0\n",
        "reference:\n  display_mode: invalid\n",
        "reference:\n  visible: maybe\n",
        "reference:\n  pgsr_output_mesh_visible: maybe\n",
    ),
)
def test_invalid_reference_display_config_is_rejected(tmp_path, text):
    with pytest.raises(ValueError):
        load_editor_config(write_config(tmp_path, text))
