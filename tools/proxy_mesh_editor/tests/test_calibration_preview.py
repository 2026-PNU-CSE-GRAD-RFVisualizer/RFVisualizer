import numpy as np
import pytest

from tools.proxy_mesh_editor.calibration.orientation_analysis import proper_rotation_between
from tools.proxy_mesh_editor.calibration.preview_exporter import (
    topology_preservation_report,
)


def test_proper_rotation_preserves_topology_and_signed_volume():
    vertices = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ]
    )
    faces = np.asarray([[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]])
    rotation, _ = proper_rotation_between(
        np.asarray([0.1, -0.99, -0.08]), np.asarray([0.0, 0.0, 1.0])
    )
    transformed = vertices @ rotation.T
    report = topology_preservation_report(vertices, transformed, faces, 1e-10)
    assert report["topology_preserved"]
    assert report["before_rotation"]["boundary_edge_count"] == 0
    assert report["after_rotation"]["non_manifold_edge_count"] == 0
    assert report["after_rotation"]["absolute_volume"] == pytest.approx(
        report["before_rotation"]["absolute_volume"]
    )
    assert report["after_rotation"]["signed_volume"] == pytest.approx(
        report["before_rotation"]["signed_volume"]
    )
