import copy

import pytest

from tools.proxy_mesh_editor.calibration.metric_calibration import resolve_scale_analysis
from tools.proxy_mesh_editor.calibration.metric_config import (
    DEFAULT_METRIC_CONFIG,
    MetricCalibrationConfigError,
    validate_metric_config,
)
from tools.proxy_mesh_editor.calibration.metric_validator import MetricValidationError


def _config():
    config = copy.deepcopy(DEFAULT_METRIC_CONFIG)
    config["metric_calibration"]["scale"]["references"] = [
        {
            "name": "width",
            "scene_distance": 1.351458,
            "real_distance_m": 2.0,
            "weight": 1.0,
        },
        {
            "name": "height",
            "scene_distance": 1.370173,
            "real_distance_m": 2.2,
            "weight": 1.0,
        },
    ]
    return config


def test_current_references_resolve_expected_scale_and_warning():
    settings = validate_metric_config(_config())["metric_calibration"]
    analysis = resolve_scale_analysis(settings)
    assert analysis["recommended_meters_per_scene_unit"] == pytest.approx(1.5436246231)
    assert analysis["relative_spread"] == pytest.approx(0.0815120033)
    assert analysis["spread_status"] == "warning"


def test_non_uniform_scale_and_same_axis_corners_are_rejected():
    config = _config()
    config["metric_calibration"]["scale"]["uniform_scale_only"] = False
    with pytest.raises(MetricCalibrationConfigError, match="축마다"):
        validate_metric_config(config)
    config = _config()
    config["metric_calibration"]["coordinate_frame"]["x_axis"].update(
        {"start_corner": 2, "end_corner": 2}
    )
    with pytest.raises(MetricCalibrationConfigError, match="달라야"):
        validate_metric_config(config)


@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_reference_values_are_rejected(value):
    config = _config()
    config["metric_calibration"]["scale"]["references"][0]["real_distance_m"] = value
    with pytest.raises(MetricCalibrationConfigError):
        validate_metric_config(config)


def test_failure_reference_spread_stops_calibration():
    config = _config()
    references = config["metric_calibration"]["scale"]["references"]
    references[0]["real_distance_m"] = 1.0
    references[1]["real_distance_m"] = 4.0
    settings = validate_metric_config(config)["metric_calibration"]
    with pytest.raises(MetricValidationError, match="중단"):
        resolve_scale_analysis(settings)
