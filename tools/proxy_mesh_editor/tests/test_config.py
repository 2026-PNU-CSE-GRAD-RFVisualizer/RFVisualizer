import pytest

from tools.proxy_mesh_editor.config import ConfigError, normalize_vector


def test_zero_up_vector_is_rejected():
    with pytest.raises(ConfigError, match="영벡터"):
        normalize_vector([0.0, 0.0, 0.0], "scene.up_vector")


def test_up_vector_is_normalized():
    result = normalize_vector([0.0, -2.0, 0.0], "scene.up_vector")
    assert result.tolist() == [0.0, -1.0, 0.0]

