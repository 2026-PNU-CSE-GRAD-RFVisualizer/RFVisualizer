import numpy as np

from tools.proxy_placement_editor.coordinate_bridge import PlacementCoordinateBridge
from tools.proxy_placement_editor.reference_loader import (
    build_mesh_preview_cache,
    load_pgsr_output_mesh_geometry,
    load_point_cloud_geometry,
    load_reference_geometry,
    mesh_preview_cache_is_current,
)


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


def test_nonfinite_point_cloud_positions_are_excluded(tmp_path, placement_scene):
    path = tmp_path / "points_with_nan.ply"
    path.write_text(
        "ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\n"
        "property float z\nelement face 0\nproperty list uchar int vertex_indices\n"
        "end_header\n0 0 0\nnan 1 2\n1 2 3\n",
        encoding="utf-8",
    )
    bridge = PlacementCoordinateBridge.from_calibration(placement_scene.calibration)
    result = load_point_cloud_geometry(path, "metric", bridge)
    assert len(result.vertices_metric) == 2
    assert result.discarded_nonfinite_points == 1
    assert result.display_decimated is True


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


def test_point_cloud_loader_keeps_mesh_faces_out_of_point_layer(
    tmp_path, placement_scene
):
    path = tmp_path / "source_with_faces.ply"
    path.write_text(
        "ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\n"
        "property float z\nelement face 1\nproperty list uchar int vertex_indices\n"
        "end_header\n0 0 0\n1 0 0\n0 1 0\n3 0 1 2\n",
        encoding="utf-8",
    )
    bridge = PlacementCoordinateBridge.from_calibration(placement_scene.calibration)
    result = load_point_cloud_geometry(path, "metric", bridge)
    assert result.kind == "point_cloud"
    assert result.faces.shape == (0, 3)


def test_pgsr_mesh_uses_current_simplified_triangle_cache(
    tmp_path, placement_scene
):
    source = tmp_path / "pgsr_mesh.ply"
    source.write_text(
        "ply\nformat ascii 1.0\nelement vertex 4\nproperty float x\nproperty float y\n"
        "property float z\nelement face 2\nproperty list uchar int vertex_indices\n"
        "end_header\n0 0 0\n1 0 0\n1 1 0\n0 1 0\n3 0 1 2\n3 0 2 3\n",
        encoding="utf-8",
    )
    preview = tmp_path / "cache" / "pgsr_mesh_preview.ply"
    metadata = build_mesh_preview_cache(source, preview, maximum_triangles=1)
    assert metadata["source_triangles"] == 2
    assert metadata["preview_triangles"] <= 1
    assert mesh_preview_cache_is_current(source, preview, maximum_triangles=1)
    assert not mesh_preview_cache_is_current(source, preview, maximum_triangles=2)

    bridge = PlacementCoordinateBridge.from_calibration(placement_scene.calibration)
    result = load_pgsr_output_mesh_geometry(
        source,
        "metric",
        bridge,
        preview_path=preview,
        maximum_triangles=1,
    )
    assert result.kind == "mesh"
    assert result.preview_path == preview.resolve()
    assert len(result.faces) <= 1


def test_pgsr_mesh_full_resolution_ignores_preview_and_triangle_limit(
    tmp_path, placement_scene
):
    source = tmp_path / "pgsr_mesh.ply"
    source.write_text(
        "ply\nformat ascii 1.0\nelement vertex 4\nproperty float x\nproperty float y\n"
        "property float z\nelement face 2\nproperty list uchar int vertex_indices\n"
        "end_header\n0 0 0\n1 0 0\n1 1 0\n0 1 0\n3 0 1 2\n3 0 2 3\n",
        encoding="utf-8",
    )
    preview = tmp_path / "cache" / "pgsr_mesh_preview.ply"
    build_mesh_preview_cache(source, preview, maximum_triangles=1)
    bridge = PlacementCoordinateBridge.from_calibration(placement_scene.calibration)

    result = load_pgsr_output_mesh_geometry(
        source,
        "metric",
        bridge,
        preview_path=preview,
        maximum_triangles=1,
        full_resolution=True,
    )

    assert result.kind == "mesh"
    assert result.preview_path is None
    assert result.display_decimated is False
    assert len(result.faces) == 2
