import pytest

from tools.proxy_mesh_editor.calibration.scale_analysis import (
    ScaleAnalysisError,
    analyze_scale_references,
)


REFERENCES = [
    {
        "name": "two_door_total_width",
        "scene_distance": 1.351458,
        "assumed_real_distance_m": 2.0,
        "weight": 1.0,
    },
    {
        "name": "door_height",
        "scene_distance": 1.370173,
        "assumed_real_distance_m": 2.2,
        "weight": 1.0,
    },
]

SETTINGS = {
    "supported_estimators": [
        "arithmetic_mean_of_ratios",
        "weighted_mean_of_ratios",
        "weighted_least_squares",
        "median_of_ratios",
    ],
    "recommended_estimator": "weighted_least_squares",
    "warning_relative_spread": 0.05,
    "failure_relative_spread": 0.20,
}


def test_provided_scale_references_produce_expected_warning_and_wls():
    result = analyze_scale_references(REFERENCES, SETTINGS)
    assert result["references"][0]["individual_meters_per_scene_unit"] == pytest.approx(
        1.4798832076
    )
    assert result["references"][1]["individual_meters_per_scene_unit"] == pytest.approx(
        1.6056366605
    )
    assert result["recommended_meters_per_scene_unit"] == pytest.approx(1.5436246231)
    assert result["relative_spread"] == pytest.approx(0.0815120033)
    assert result["spread_status"] == "warning"
    residuals = result["recommended_reference_residuals"]
    assert residuals[0]["relative_error"] == pytest.approx(0.0430719230)
    assert residuals[1]["relative_error"] == pytest.approx(-0.0386214633)


@pytest.mark.parametrize("field", ["scene_distance", "assumed_real_distance_m"])
@pytest.mark.parametrize("value", [0.0, -1.0])
def test_nonpositive_scale_distance_is_rejected(field, value):
    references = [dict(REFERENCES[0]), dict(REFERENCES[1])]
    references[0][field] = value
    with pytest.raises(ScaleAnalysisError, match="양수"):
        analyze_scale_references(references, SETTINGS)
