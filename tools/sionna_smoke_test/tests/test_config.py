import copy

import pytest
import yaml

from tools.sionna_smoke_test.config import SmokeTestConfigError, validate_config


def _config():
    with open("configs/sionna/pnu_classroom_smoke_test.yaml", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_project_smoke_config_is_valid():
    config = validate_config(_config())
    assert config["sionna_smoke_test"]["scene"]["carrier_frequency_hz"] == 2.4e9


@pytest.mark.parametrize(
    "path,value",
    [
        (("scene", "carrier_frequency_hz"), 0.0),
        (("coverage", "cell_size_m"), -1.0),
        (("path_test", "max_depth"), -1),
        (("coverage", "max_depth"), -1),
    ],
)
def test_invalid_positive_and_depth_values_are_rejected(path, value):
    config = _config()
    config["sionna_smoke_test"][path[0]][path[1]] = value
    with pytest.raises(SmokeTestConfigError):
        validate_config(config)


@pytest.mark.parametrize("position", [[1, 2], [1, 2, float("nan")], [1, 2, float("inf")]])
def test_invalid_device_coordinates_are_rejected(position):
    config = _config()
    config["sionna_smoke_test"]["transmitter"]["position_m"] = position
    with pytest.raises(SmokeTestConfigError, match="숫자 3개"):
        validate_config(config)


def test_missing_input_path_value_is_rejected():
    config = _config()
    config["sionna_smoke_test"]["input"]["metric_obj"] = ""
    with pytest.raises(SmokeTestConfigError, match="경로"):
        validate_config(config)
