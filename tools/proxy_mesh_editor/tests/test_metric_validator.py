import numpy as np
import pytest

from tools.proxy_mesh_editor.calibration.metric_validator import (
    MetricValidationError,
    validate_rotation_matrix,
)


SETTINGS = {
    "maximum_rotation_determinant_error": 1e-8,
    "maximum_orthogonality_error": 1e-8,
}


def test_reflection_rotation_is_rejected():
    reflection = np.diag([1.0, -1.0, 1.0])
    with pytest.raises(MetricValidationError, match="reflection"):
        validate_rotation_matrix(reflection, SETTINGS)


def test_proper_rotation_is_accepted():
    rotation = np.asarray([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    report = validate_rotation_matrix(rotation, SETTINGS)
    assert report["determinant"] == pytest.approx(1.0)
    assert report["orthogonality_error"] == 0.0
