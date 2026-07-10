import copy

import pytest

from tools.proxy_mesh_editor.config import (
    DEFAULT_CONFIG,
    ConfigError,
    normalize_vector,
    resolve_scene_value,
    validate_config,
)


def test_zero_up_vector_is_rejected():
    with pytest.raises(ConfigError, match="영벡터"):
        normalize_vector([0.0, 0.0, 0.0], "scene.up_vector")


def test_up_vector_is_normalized():
    result = normalize_vector([0.0, -2.0, 0.0], "scene.up_vector")
    assert result.tolist() == [0.0, -1.0, 0.0]


def test_wall_dot_threshold_outside_unit_range_is_rejected():
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["wall_extraction"]["ransac"]["plane_normal_max_up_dot"] = 1.1
    with pytest.raises(ConfigError, match="0과 1"):
        validate_config(config)


def test_duplicate_normal_thresholds_are_rejected():
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["normal_analysis"]["thresholds"] = [0.25, 0.25]
    with pytest.raises(ConfigError, match="중복"):
        validate_config(config)


def test_negative_wall_ratio_is_rejected_even_when_absolute_value_exists():
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["wall_extraction"]["ransac"]["distance_threshold"] = 0.01
    config["wall_extraction"]["ransac"]["distance_threshold_ratio"] = -0.1
    with pytest.raises(ConfigError, match="0 이상"):
        validate_config(config)


def test_absolute_scene_value_has_priority_over_ratio():
    assert resolve_scene_value(
        {"distance_threshold": 0.25, "distance_threshold_ratio": 0.5},
        "distance_threshold",
        "distance_threshold_ratio",
        100.0,
    ) == 0.25
