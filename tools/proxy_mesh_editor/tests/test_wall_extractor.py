import copy

import numpy as np

from tools.proxy_mesh_editor.config import DEFAULT_CONFIG
from tools.proxy_mesh_editor.geometry.plane_mesher import build_plane_rectangle
from tools.proxy_mesh_editor.geometry.wall_extractor import select_wall_components


def _grid_on_x(x_value, y_values, z_values):
    y, z = np.meshgrid(y_values, z_values)
    return np.column_stack([np.full(y.size, x_value), y.ravel(), z.ravel()])


def _grid_on_y(y_value, x_values, z_values):
    x, z = np.meshgrid(x_values, z_values)
    return np.column_stack([x.ravel(), np.full(x.size, y_value), z.ravel()])


def test_fragmented_wall_components_are_merged_and_small_noise_is_excluded():
    z_values = np.linspace(0.0, 2.0, 12)
    parts = [
        _grid_on_x(0.0, np.linspace(-4.0, -2.5, 10), z_values),
        _grid_on_x(0.0, np.linspace(-1.0, 1.0, 10), z_values),
        _grid_on_x(0.0, np.linspace(2.5, 4.0, 10), z_values),
        np.asarray(
            [[0.0, 5.0, 0.0], [0.0, 5.1, 0.7], [0.0, 5.0, 1.4], [0.0, 5.1, 2.0]]
        ),
    ]
    points = np.vstack(parts)
    labels = np.concatenate(
        [np.full(len(part), component_id, dtype=int) for component_id, part in enumerate(parts)]
    )

    selected, summary = select_wall_components(
        points,
        labels,
        plane_normal=np.asarray([1.0, 0.0, 0.0]),
        up_vector=np.asarray([0.0, 0.0, 1.0]),
        min_points=10,
        min_vertical_span=1.5,
        merge_valid_components=True,
    )

    assert len(selected) == sum(len(part) for part in parts[:3])
    assert summary["component_count"] == 4
    assert summary["valid_component_count"] == 3
    assert summary["used_component_count"] == 3
    assert summary["merged_component_count"] == 3
    assert summary["excluded_component_count"] == 1
    assert summary["components"][3]["rejection_reasons"] == ["too_few_points"]

    settings = {
        "lower_percentile": 0.0,
        "upper_percentile": 100.0,
        "margin_ratio": 0.0,
        "min_extent": 0.01,
        "min_extent_ratio": 0.0,
        "vertical_alignment_max_dot": 0.3,
    }
    _, _, _, rectangle = build_plane_rectangle(
        points[selected],
        np.asarray([1.0, 0.0, 0.0, 0.0]),
        np.asarray([0.0, 0.0, 1.0]),
        settings,
        scene_extent=10.0,
    )
    assert rectangle.width >= 7.9
    assert rectangle.height >= 1.9


def test_wall_only_synthetic_scene_filters_horizontal_surfaces_and_finds_walls():
    o3d = __import__("pytest").importorskip("open3d")
    xy = np.linspace(-2.0, 2.0, 20)
    z = np.linspace(0.0, 3.0, 16)
    walls = [
        _grid_on_x(-2.0, xy, z),
        _grid_on_x(2.0, xy, z),
        _grid_on_y(-2.0, xy, z),
        _grid_on_y(2.0, xy, z),
    ]
    wall_normals = [
        np.tile([-1.0, 0.0, 0.0], (len(walls[0]), 1)),
        np.tile([1.0, 0.0, 0.0], (len(walls[1]), 1)),
        np.tile([0.0, -1.0, 0.0], (len(walls[2]), 1)),
        np.tile([0.0, 1.0, 0.0], (len(walls[3]), 1)),
    ]
    x, y = np.meshgrid(xy, xy)
    floor = np.column_stack([x.ravel(), y.ravel(), np.zeros(x.size)])
    ceiling = np.column_stack([x.ravel(), y.ravel(), np.full(x.size, 3.0)])
    table = np.column_stack([x.ravel() * 0.5, y.ravel() * 0.5, np.full(x.size, 1.0)])
    horizontal = np.vstack([floor, ceiling, table])
    horizontal_normals = np.tile([0.0, 0.0, 1.0], (len(horizontal), 1))

    points = np.vstack([*walls, horizontal])
    normals = np.vstack([*wall_normals, horizontal_normals])
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(points)
    cloud.normals = o3d.utility.Vector3dVector(normals)

    config = copy.deepcopy(DEFAULT_CONFIG)
    config["scene"]["up_vector"] = [0.0, 0.0, 1.0]
    config["scene"]["random_seed"] = 17
    wall = config["wall_extraction"]
    wall["normal_filter"]["point_normal_max_up_dot"] = 0.1
    wall["ransac"].update(
        {
            "distance_threshold": 0.01,
            "num_iterations": 1000,
            "max_planes": 4,
            "max_attempts": 8,
            "min_inliers": 100,
            "min_inlier_ratio": 0.05,
            "plane_normal_max_up_dot": 0.1,
        }
    )
    wall["components"]["enabled"] = False
    wall["meshing"]["min_area"] = 1.0

    from tools.proxy_mesh_editor.geometry.wall_extractor import (
        extract_wall_planes,
        filter_vertical_points,
    )

    filtered, filter_stats = filter_vertical_points(
        cloud, np.asarray([0.0, 0.0, 1.0]), wall["normal_filter"]
    )
    assert len(filtered.points) == sum(len(part) for part in walls)
    assert filter_stats["normal_filtered_ratio"] < 0.6

    _, candidates, stats, _ = extract_wall_planes(cloud, config, scene_extent=8.0)
    assert len(candidates) == 4
    assert stats["accepted_wall_count"] == 4
    assert all(candidate.orientation == "vertical" for candidate in candidates)
    assert all(candidate.source_pass == "wall_extraction" for candidate in candidates)
    assert all(
        candidate.extraction_details["normal_up_absolute_dot"] <= 0.1
        for candidate in candidates
    )
