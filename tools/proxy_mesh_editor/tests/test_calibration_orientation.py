import numpy as np
import pytest

from tools.proxy_mesh_editor.calibration.orientation_analysis import (
    OrientationAnalysisError,
    analyze_envelope_orientation,
    proper_rotation_between,
    rotation_validation,
)


def _envelope(up):
    up = np.asarray(up, dtype=float)
    up = up / np.linalg.norm(up)
    horizontal_seed = np.asarray([1.0, 0.0, 0.0])
    if abs(np.dot(horizontal_seed, up)) > 0.9:
        horizontal_seed = np.asarray([0.0, 1.0, 0.0])
    u = horizontal_seed - np.dot(horizontal_seed, up) * up
    u = u / np.linalg.norm(u)
    v = np.cross(up, u)
    bottom = np.asarray([-u - v, u - v, u + v, -u + v])
    top = bottom + 3.0 * up
    floor = np.r_[up, -np.dot(up, bottom[0])]
    ceiling = np.r_[up, -np.dot(up, top[0])]
    return {
        "up_vector": up.tolist(),
        "bottom_corners": bottom.tolist(),
        "top_corners": top.tolist(),
        "normalized_plane_equations": {
            "floor": floor.tolist(),
            "ceiling": ceiling.tolist(),
        },
    }


def test_positive_z_room_has_positive_heights_and_identity_rotation():
    envelope = _envelope([0.0, 0.0, 1.0])
    analysis = analyze_envelope_orientation(envelope, 1e-6)
    rotation, diagnostics = proper_rotation_between(
        np.asarray(envelope["up_vector"]), np.asarray([0.0, 0.0, 1.0])
    )
    assert analysis["vertical_center_offset"] == pytest.approx(3.0)
    assert analysis["all_corner_heights_positive"]
    np.testing.assert_allclose(rotation, np.eye(3))
    assert diagnostics["determinant"] == pytest.approx(1.0)


def test_negative_y_up_uses_proper_rotation_not_reflection():
    envelope = _envelope([0.0, -1.0, 0.0])
    analysis = analyze_envelope_orientation(envelope, 1e-6)
    rotation, diagnostics = proper_rotation_between(
        np.asarray([0.0, -1.0, 0.0]), np.asarray([0.0, 0.0, 1.0])
    )
    assert analysis["all_corner_heights_positive"]
    np.testing.assert_allclose(
        rotation @ [0.0, -1.0, 0.0], [0.0, 0.0, 1.0], atol=1e-12
    )
    assert diagnostics["determinant"] == pytest.approx(1.0)


def test_exact_opposite_rotation_is_deterministic_and_proper():
    first, first_diagnostics = proper_rotation_between(
        np.asarray([0.0, 0.0, -1.0]), np.asarray([0.0, 0.0, 1.0])
    )
    second, second_diagnostics = proper_rotation_between(
        np.asarray([0.0, 0.0, -1.0]), np.asarray([0.0, 0.0, 1.0])
    )
    np.testing.assert_allclose(first, second)
    assert first_diagnostics["rotation_axis"] == second_diagnostics["rotation_axis"]
    assert first_diagnostics["rotation_angle_deg"] == pytest.approx(180.0)
    assert np.linalg.det(first) == pytest.approx(1.0)
    np.testing.assert_allclose(first @ [0.0, 0.0, -1.0], [0.0, 0.0, 1.0])


@pytest.mark.parametrize(
    "up",
    [[0.0, 0.0, 0.0], [float("nan"), 0.0, 1.0], [float("inf"), 0.0, 1.0]],
)
def test_invalid_up_vector_is_rejected(up):
    envelope = _envelope([0.0, 0.0, 1.0])
    envelope["up_vector"] = up
    with pytest.raises(OrientationAnalysisError):
        analyze_envelope_orientation(envelope, 1e-6)


def test_negative_and_mixed_corner_heights_fail_orientation_diagnosis():
    envelope = _envelope([0.0, 0.0, 1.0])
    bottom = np.asarray(envelope["bottom_corners"])
    envelope["top_corners"] = (bottom - np.asarray([0.0, 0.0, 1.0])).tolist()
    analysis = analyze_envelope_orientation(envelope, 1e-6)
    assert analysis["orientation_status"] == "failure"
    assert analysis["orientation_diagnosis"] == "scene_up_sign_suspect"
    assert analysis["diagnosis_checks"]["scene_up_sign_suspect"]

    envelope = _envelope([0.0, 0.0, 1.0])
    top = np.asarray(envelope["top_corners"])
    top[0] = np.asarray(envelope["bottom_corners"])[0] - [0.0, 0.0, 1.0]
    envelope["top_corners"] = top.tolist()
    analysis = analyze_envelope_orientation(envelope, 1e-6)
    assert analysis["orientation_status"] == "failure"
    assert analysis["orientation_diagnosis"] == "corner_correspondence_or_geometry_suspect"
    assert analysis["diagnosis_checks"][
        "floor_ceiling_or_corner_correspondence_suspect"
    ]


def test_rotation_validation_reports_small_round_trip_error():
    rotation, diagnostics = proper_rotation_between(
        np.asarray([0.2, -0.9, 0.1]), np.asarray([0.0, 0.0, 1.0])
    )
    result = rotation_validation(
        rotation,
        np.asarray([[1.0, 2.0, 3.0], [-4.0, 0.5, 2.0]]),
        diagnostics,
        {
            "maximum_up_alignment_error": 1e-8,
            "maximum_orthogonality_error": 1e-8,
            "maximum_round_trip_error": 1e-8,
        },
        (0.999999, 1.000001),
    )
    assert result["proper_rotation_success"]
