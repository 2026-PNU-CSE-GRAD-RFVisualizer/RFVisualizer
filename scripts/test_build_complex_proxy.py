import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_complex_proxy import (  # noqa: E402
    build_mesh,
    drop_small_jogs,
    keyhole_polygon,
    merge_collinear,
    metric_transform,
    point_in_loops,
    signed_area,
    snap_to_wall_lines,
    topology,
    trace_loops,
)


def _ring_grid():
    """가운데가 뚫린 ㅁ자 점유 격자."""
    occ = np.zeros((20, 20), dtype=bool)
    occ[2:18, 2:18] = True
    occ[6:14, 6:14] = False
    return occ


def test_trace_finds_outer_and_hole_with_opposite_winding():
    loops = [merge_collinear(loop) for loop in trace_loops(_ring_grid())]
    areas = sorted(signed_area(loop) for loop in loops)
    assert len(loops) == 2
    assert areas[0] < 0 < areas[1], "바깥은 반시계(+), 구멍은 시계(-)여야 한다"
    assert abs(areas[1]) == 16 * 16 and abs(areas[0]) == 8 * 8


def test_snapping_keeps_edges_axis_aligned():
    jagged = [(0, 0), (5, 0), (5, 1), (7, 1), (7, 0), (12, 0), (12, 12), (0, 12)]
    for loop in (jagged, drop_small_jogs(jagged, 4)):
        for i in range(len(loop)):
            a, b = loop[i], loop[(i + 1) % len(loop)]
            assert a[0] == b[0] or a[1] == b[1], f"대각선 변이 생겼다: {a}->{b}"


def test_wall_align_flattens_a_stepped_wall_without_moving_the_long_wall():
    # y=0의 긴 벽에 1칸 튀어나온 계단이 있는 도형
    stepped = [(0, 0), (20, 0), (20, 1), (40, 1), (40, 30), (0, 30)]
    (flattened,) = snap_to_wall_lines([stepped], tolerance_cells=3)

    ys = {p[1] for p in flattened}
    assert 1 not in ys, "1칸 계단은 긴 벽 쪽으로 흡수돼야 한다"
    assert 0 in ys and 30 in ys, "긴 벽 자체는 움직이면 안 된다"
    for i in range(len(flattened)):
        a, b = flattened[i], flattened[(i + 1) % len(flattened)]
        assert a[0] == b[0] or a[1] == b[1]


def test_wall_align_keeps_a_corridor_narrower_than_the_tolerance_apart():
    # 폭 4칸 통로. tolerance 3이면 양쪽 벽이 합쳐져 통로가 사라지면 안 된다.
    corridor = [(0, 0), (40, 0), (40, 4), (0, 4)]
    (kept,) = snap_to_wall_lines([corridor], tolerance_cells=3)
    ys = sorted({p[1] for p in kept})
    assert ys == [0, 4], f"통로 폭이 사라졌다: {ys}"


def test_keyhole_polygon_excludes_the_hole():
    outer = [(0, 0), (16, 0), (16, 16), (0, 16)]
    hole = [(4, 4), (4, 12), (12, 12), (12, 4)]
    polygon = keyhole_polygon(outer, [hole])
    assert point_in_loops((1.0, 1.0), outer, [hole]) is True
    assert point_in_loops((8.0, 8.0), outer, [hole]) is False
    assert len(polygon) > len(outer)


def test_ring_mesh_is_a_closed_manifold_with_positive_volume():
    outer = [(0, 0), (16, 0), (16, 16), (0, 16)]
    hole = [(4, 4), (4, 12), (12, 12), (12, 4)]
    vertices, faces, inside, _, _ = build_mesh(outer, [hole], 0.0, 3.0)
    report = topology(vertices, faces)

    assert report["closed_manifold_success"], report
    assert report["boundary_edge_count"] == 0
    assert report["non_manifold_edge_count"] == 0
    assert report["degenerate_triangle_count"] == 0
    # 바깥 16x16에서 구멍 8x8을 뺀 넓이 × 높이 3
    assert np.isclose(report["signed_volume"], (16 * 16 - 8 * 8) * 3.0)


def _tilted_axes():
    """세계 +Y가 위쪽인, 살짝 기울어진 장면 축. pnu_3f_corridor와 같은 상황."""
    up = np.array([0.037, 0.995, 0.088])
    up = up / np.linalg.norm(up)
    au = np.cross(up, [1.0, 0.0, 0.0])
    au /= np.linalg.norm(au)
    av = np.cross(up, au)
    av /= np.linalg.norm(av)
    return au, av, up


def test_metric_transform_round_trips():
    axes = _tilted_axes()
    forward, inverse = metric_transform(axes, (-5.2, -4.0), (24.0, 0.0), 0.04, -0.303, 3.9803)
    assert np.max(np.abs(forward @ inverse - np.eye(4))) < 1e-9
    assert np.max(np.abs(inverse @ forward - np.eye(4))) < 1e-9


def test_metric_transform_stands_the_scene_up_and_scales_it():
    """배율만 넣고 회전을 빼면 PGSR Mesh와 Proxy가 겹치지 않는다."""
    axes = _tilted_axes()
    au, av, up = axes
    scale, resolution, floor_h = 3.9803, 0.04, -0.303
    grid_origin, origin_cell = (-5.2, -4.0), (24.0, 0.0)
    forward, _ = metric_transform(axes, grid_origin, origin_cell, resolution, floor_h, scale)

    def apply(point):
        return (forward @ np.append(np.asarray(point, dtype=float), 1.0))[:3]

    # 격자 원점이면서 바닥 높이인 장면점은 미터 원점으로 간다.
    origin_scene = (
        au * (grid_origin[0] + origin_cell[0] * resolution)
        + av * (grid_origin[1] + origin_cell[1] * resolution)
        + up * floor_h
    )
    assert np.allclose(apply(origin_scene), [0.0, 0.0, 0.0], atol=1e-9)

    # 장면의 위쪽 방향은 정확히 +Z로 서고, 길이는 배율만큼 늘어난다.
    assert np.allclose(apply(origin_scene + up) - apply(origin_scene), [0.0, 0.0, scale], atol=1e-9)
    # 수평 두 축도 각각 +X, +Y로 간다.
    assert np.allclose(apply(origin_scene + au) - apply(origin_scene), [scale, 0.0, 0.0], atol=1e-9)
    assert np.allclose(apply(origin_scene + av) - apply(origin_scene), [0.0, scale, 0.0], atol=1e-9)


def test_diagonal_touch_is_filled_so_no_pinch_point():
    outer = [(0, 0), (2, 0), (2, 1), (3, 1), (3, 3), (1, 3), (1, 2), (0, 2)]
    vertices, faces, inside, _, _ = build_mesh(outer, [], 0.0, 1.0)
    report = topology(vertices, faces)
    assert report["non_manifold_edge_count"] == 0, "대각선 접점이 꼬집힘을 만들면 안 된다"
    assert report["closed_manifold_success"]
