import numpy as np

from tools.proxy_placement_editor.coordinate_bridge import PlacementCoordinateBridge
from tools.proxy_placement_editor.reference_loader import load_reference_geometry


def test_metric_point_cloud_ply_load(tmp_path, placement_scene):
    path = tmp_path / "points.ply"
    path.write_text(
        "ply\nformat ascii 1.0\nelement vertex 2\nproperty float x\nproperty float y\nproperty float z\n"
        "element face 0\nproperty list uchar int vertex_indices\nend_header\n0 0 0\n1 2 3\n",
        encoding="utf-8",
    )
    bridge = PlacementCoordinateBridge.from_calibration(placement_scene.calibration)
    result = load_reference_geometry(path, "metric", bridge)
    assert result.kind == "point_cloud"
    assert np.allclose(result.vertices_metric[1], [1, 2, 3])


def test_large_triangle_ply_uses_bounded_point_preview(tmp_path, placement_scene):
    path = tmp_path / "mesh.ply"
    path.write_text(
        "ply\nformat ascii 1.0\nelement vertex 4\nproperty float x\nproperty float y\n"
        "property float z\nelement face 2\nproperty list uchar int vertex_indices\n"
        "end_header\n0 0 0\n1 0 0\n1 1 0\n0 1 0\n3 0 1 2\n3 0 2 3\n",
        encoding="utf-8",
    )
    bridge = PlacementCoordinateBridge.from_calibration(placement_scene.calibration)
    result = load_reference_geometry(
        path, "metric", bridge, maximum_triangles=1, maximum_points=3
    )
    assert result.kind == "point_cloud"
    assert result.display_decimated is True
    assert result.faces.shape == (0, 3)
    assert len(result.vertices_metric) == 3
