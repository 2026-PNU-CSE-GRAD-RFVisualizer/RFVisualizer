#!/usr/bin/env python3
"""PGSR Mesh에서 구멍·곁가지가 있는 복잡한 실내 Proxy Mesh를 직접 만든다.

TUTORIAL.md 5절의 build-envelope/pick-envelope는 "바닥1 + 천장1 + 벽을 순서대로
이은 닫힌 다각형 1개"만 지원하므로, ㅁ자 링 복도(중정 구멍)나 곁가지가 붙은
평면에는 쓸 수 없다. 이 스크립트는 그런 씬을 위해 5.2~5.7을 건너뛰고
room_envelope_metric.obj/json + calibration.json을 바로 만든다.

방식:
    1. 바닥 높이대의 점을 위에서 내려다본 점유 격자로 만든다(= 통행 가능 공간).
    2. 격자 경계를 따라 닫힌 윤곽선(바깥 1개 + 구멍 N개)을 추출한다.
    3. 축 정렬 직사각 윤곽으로 단순화한다.
    4. 윤곽선 좌표로 만든 격자에서 안쪽 칸만 바닥/천장으로, 바깥과 맞닿은
       칸 경계만 벽으로 만든다. 이렇게 하면 구멍이 있어도 T-junction 없이
       닫힌 manifold가 된다.

미터 배율은 실측이 없으므로 --ceiling-height-m 가정값으로 정한다. 실측하면
그 값만 바꿔 다시 실행한다. 결과는 항상 status=provisional이다.

사용법:
    conda run -n pgsr python scripts/build_complex_proxy.py <scene_id> \\
        --mesh PGSR/output/<name>/mesh/tsdf_fusion_post.ply \\
        --up-vector X Y Z [--ceiling-height-m 2.7]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import ndimage

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------- 1. 점유 격자 ----------

AXIS_ROTATIONS = None


def axis_aligned_rotations():
    """축에 정렬된 24개 회전행렬(순열 x 부호, det=+1)."""
    global AXIS_ROTATIONS
    if AXIS_ROTATIONS is None:
        import itertools

        found = []
        for order in itertools.permutations(range(3)):
            for signs in itertools.product((1, -1), repeat=3):
                matrix = np.zeros((3, 3))
                for row, column in enumerate(order):
                    matrix[row, column] = signs[row]
                if abs(np.linalg.det(matrix) - 1.0) < 1e-9:
                    found.append(matrix)
        AXIS_ROTATIONS = found
    return AXIS_ROTATIONS


def finite_points(points):
    """NaN/Inf 점을 버린다. PGSR Gaussian Point Cloud에는 NaN이 섞여 있다."""
    values = np.asarray(points, dtype=float)
    return values[np.all(np.isfinite(values), axis=1)]


def align_axes_to(source, target):
    """source를 target과 같은 축 배치로 돌리는 회전을 고른다.

    MeshLab/Poisson 등을 거치면 축이 뒤바뀐 파일이 나온다(이 씬은 blend가
    원본 대비 X축 -90도). 하드코딩하지 않고 24개 축 정렬 회전 중 가장 잘 맞는
    것을 고른다. 축 배치만 맞추므로 임의 각도는 다루지 않는다.

    경계상자 대신 1~99 백분위를 쓴다. Gaussian splat은 멀리 튄 점이 있어
    min/max로 비교하면 엉뚱한 회전이 뽑힌다.
    """
    source = finite_points(source)
    target = finite_points(target)
    if len(source) == 0 or len(target) == 0:
        raise SystemExit("오류: 축 정렬에 쓸 유한한 점이 없습니다.")
    target_low = np.percentile(target, 1, axis=0)
    target_high = np.percentile(target, 99, axis=0)
    best, best_error = np.eye(3), None
    for rotation in axis_aligned_rotations():
        turned = source @ rotation.T
        error = float(
            np.abs(np.percentile(turned, 1, axis=0) - target_low).sum()
            + np.abs(np.percentile(turned, 99, axis=0) - target_high).sum()
        )
        if best_error is None or error < best_error:
            best, best_error = rotation, error
    return best, best_error


def detect_up_vector(mesh):
    """메시에서 위쪽 방향을 부호까지 정해서 찾는다.

    바닥과 천장이 가장 넓은 수평면이므로, 면적으로 가중한 법선 텐서의 최대
    고유벡터가 위쪽 축이 된다. 고유벡터는 부호가 정해지지 않으므로 "걸어서
    촬영한 장면은 바닥이 천장보다 촘촘하게 복원된다"는 성질로 부호를 고른다.
    up 부호가 틀리면 Proxy와 PGSR이 둘 다 위아래 뒤집혀 보인다.
    """
    mesh.compute_triangle_normals()
    mesh.compute_vertex_normals()
    vertices = np.asarray(mesh.vertices)
    triangles = np.asarray(mesh.triangles)
    normals = np.asarray(mesh.triangle_normals)
    corners = vertices[triangles]
    areas = 0.5 * np.linalg.norm(
        np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]), axis=1
    )
    tensor = np.einsum("ti,tj,t->ij", normals, normals, areas)
    axis = np.linalg.eigh(tensor)[1][:, -1]
    axis = axis / np.linalg.norm(axis)

    vertex_normals = np.asarray(mesh.vertex_normals)
    best, best_score = axis, -1.0
    for candidate in (axis, -axis):
        height = vertices @ candidate
        floor_h, ceil_h = _floor_ceiling_levels(height)
        horizontal = np.abs(vertex_normals @ candidate) > 0.85
        floor_hits = int((horizontal & (np.abs(height - floor_h) < 0.08)).sum())
        ceiling_hits = int((horizontal & (np.abs(height - ceil_h) < 0.08)).sum())
        score = floor_hits - ceiling_hits
        if score > best_score:
            best, best_score = candidate, score
    return best


def occupancy_grid(mesh_path, up, res, band_lo, band_hi, min_hits, wall_carve, closing_cells):
    import open3d as o3d

    mesh = o3d.io.read_triangle_mesh(str(mesh_path))
    mesh.compute_vertex_normals()
    pts = np.asarray(mesh.vertices)
    nor = np.asarray(mesh.vertex_normals)

    if up is None:
        up = detect_up_vector(mesh)
        print("[0] up 자동 검출: [%.4f, %.4f, %.4f]" % tuple(up))
    up = np.asarray(up, dtype=float)
    up /= np.linalg.norm(up)
    seed = np.array([1.0, 0.0, 0.0]) if abs(up[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    au = np.cross(up, seed)
    au /= np.linalg.norm(au)
    av = np.cross(up, au)
    av /= np.linalg.norm(av)

    height = pts @ up
    floor_h, ceil_h = _floor_ceiling_levels(height)

    span = ceil_h - floor_h
    lo = floor_h + span * band_lo
    hi = floor_h + span * band_hi
    up_dot = np.abs(nor @ up)
    band = (up_dot > 0.80) & (height > lo) & (height < hi)

    u = pts[band] @ au
    v = pts[band] @ av
    ub = np.arange(u.min() - res, u.max() + 2 * res, res)
    vb = np.arange(v.min() - res, v.max() + 2 * res, res)
    counts, _, _ = np.histogram2d(u, v, bins=[ub, vb])

    occ = counts >= min_hits
    # 촬영이 비어 바닥이 끊긴 자리를 메운다. 너무 작으면 복도가 끊겨 구멍(코어)이
    # 바깥으로 새고, 너무 크면 실제 문·좁은 벽까지 메운다. 실제 벽은 뒤의
    # wall_carve 단계에서 다시 깎아내므로 어느 정도 크게 잡아도 된다.
    occ = ndimage.binary_closing(occ, np.ones((closing_cells, closing_cells)))
    occ = ndimage.binary_opening(occ, np.ones((3, 3)))

    # 바닥/천장 면만 보면 얇은 벽이 사라져 막힌 통로가 뚫린 것처럼 보인다.
    # 허리 높이의 수직면(벽) 점이 몰린 칸을 격자에서 깎아내 실제 벽을 되살린다.
    wall_counts = None
    if wall_carve > 0:
        waist = (up_dot < 0.30) & (height > floor_h + span * 0.20) & (height < floor_h + span * 0.80)
        wall_counts, _, _ = np.histogram2d(pts[waist] @ au, pts[waist] @ av, bins=[ub, vb])
        occ = occ & (wall_counts < wall_carve)

    labels, count = ndimage.label(occ)
    if count == 0:
        raise SystemExit("오류: 점유 격자가 비었습니다. --band 또는 --min-hits를 조정한다.")
    sizes = ndimage.sum(occ, labels, range(1, count + 1))
    occ = labels == (int(np.argmax(sizes)) + 1)
    return occ, ub, vb, (au, av, up), float(floor_h), float(ceil_h), wall_counts


def _floor_ceiling_levels(height):
    hist, edges = np.histogram(height, bins=80)
    centers = (edges[:-1] + edges[1:]) / 2.0
    mid = len(hist) // 2
    floor_h = centers[int(np.argmax(hist[:mid]))]
    ceil_h = centers[mid + int(np.argmax(hist[mid:]))]
    if ceil_h <= floor_h:
        raise SystemExit("오류: 천장이 바닥보다 높지 않습니다. --up-vector를 확인한다.")
    return float(floor_h), float(ceil_h)


# ---------- 2. 윤곽선 추출 ----------

def trace_loops(occ):
    """점유 격자의 경계를 격자 좌표(정수) 닫힌 루프들로 추출한다."""
    edges = []
    rows, cols = occ.shape
    padded = np.zeros((rows + 2, cols + 2), dtype=bool)
    padded[1:-1, 1:-1] = occ
    for i in range(rows):
        for j in range(cols):
            if not occ[i, j]:
                continue
            # 안쪽이 진행 방향 왼쪽에 오도록 방향을 준다(바깥은 반시계).
            if not padded[i, j + 1]:      # -u쪽이 바깥
                edges.append(((i, j + 1), (i, j)))
            if not padded[i + 2, j + 1]:  # +u쪽이 바깥
                edges.append(((i + 1, j), (i + 1, j + 1)))
            if not padded[i + 1, j]:      # -v쪽이 바깥
                edges.append(((i, j), (i + 1, j)))
            if not padded[i + 1, j + 2]:  # +v쪽이 바깥
                edges.append(((i + 1, j + 1), (i, j + 1)))

    outgoing = defaultdict(list)
    for a, b in edges:
        outgoing[a].append(b)

    loops = []
    used = set()
    for start, _ in edges:
        for first in outgoing[start]:
            if (start, first) in used:
                continue
            loop = [start]
            current, nxt = start, first
            while True:
                used.add((current, nxt))
                loop.append(nxt)
                if nxt == start:
                    break
                options = [c for c in outgoing[nxt] if (nxt, c) not in used]
                if not options:
                    break
                direction = (nxt[0] - current[0], nxt[1] - current[1])
                straight = (nxt[0] + direction[0], nxt[1] + direction[1])
                current, nxt = nxt, (straight if straight in options else options[0])
            if len(loop) > 4 and loop[0] == loop[-1]:
                loops.append(loop[:-1])
    return loops


def merge_collinear(loop):
    # 길이 0인 변(같은 점 반복)을 먼저 없앤다. 요철을 펴는 과정에서 생긴다.
    deduped = [p for i, p in enumerate(loop) if p != loop[(i - 1) % len(loop)]]
    if len(deduped) < 3:
        return deduped
    out = []
    n = len(deduped)
    for i in range(n):
        prev, cur, nxt = deduped[(i - 1) % n], deduped[i], deduped[(i + 1) % n]
        d1 = (cur[0] - prev[0], cur[1] - prev[1])
        d2 = (nxt[0] - cur[0], nxt[1] - cur[1])
        if d1 != d2:
            out.append(cur)
    return out


def drop_small_jogs(loop, min_cells):
    """좌표를 굵은 격자에 맞춰 계단 모양을 편다.

    x와 y를 따로 반올림하므로 가로 변은 가로로, 세로 변은 세로로 남는다.
    min_cells보다 작은 요철은 길이 0이 되어 merge_collinear에서 사라진다.
    """
    step = max(1, int(min_cells))
    snapped = [(int(round(p[0] / step)) * step, int(round(p[1] / step)) * step) for p in loop]
    return merge_collinear(snapped)


def snap_to_wall_lines(loops, tolerance_cells):
    """가까운 벽선끼리 한 줄로 모아 긴 벽의 계단 모양을 없앤다.

    세로 변의 x끼리, 가로 변의 y끼리 따로 모으므로 축 정렬이 유지된다.
    각 묶음의 대표값은 변 길이로 가중한 평균이라 긴 벽이 짧은 요철에 끌려가지 않는다.
    """
    x_weight, y_weight = defaultdict(float), defaultdict(float)
    for loop in loops:
        for i in range(len(loop)):
            a, b = loop[i], loop[(i + 1) % len(loop)]
            if a[0] == b[0]:
                x_weight[a[0]] += abs(b[1] - a[1])
            elif a[1] == b[1]:
                y_weight[a[1]] += abs(b[0] - a[0])

    def centers(weights):
        """긴 벽부터 기준선으로 삼고 그 주변 좌표만 흡수한다.

        정렬 순서로 이웃끼리 이어 붙이면 일정 간격으로 놓인 좌표가 연쇄로 다
        합쳐져 도형이 뭉개진다. 그래서 가중치가 큰 좌표를 기준으로 고정하고
        아직 배정되지 않은 좌표만 tolerance 안에서 끌어온다.
        """
        table = {}
        for anchor in sorted(weights, key=lambda c: (-weights[c], c)):
            if anchor in table:
                continue
            group = [c for c in weights if c not in table and abs(c - anchor) <= tolerance_cells]
            for coord in group:
                table[coord] = anchor
        return table

    x_table, y_table = centers(x_weight), centers(y_weight)
    snapped = []
    for loop in loops:
        moved = [(x_table.get(p[0], p[0]), y_table.get(p[1], p[1])) for p in loop]
        merged = merge_collinear(moved)
        if len(merged) >= 4:
            snapped.append(merged)
    return snapped


def signed_area(loop):
    pts = np.asarray(loop, dtype=float)
    x, y = pts[:, 0], pts[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


# ---------- 3. 메시 생성 ----------

def point_in_loops(point, outer, holes):
    if not _inside(point, outer):
        return False
    return not any(_inside(point, hole) for hole in holes)


def _inside(point, loop):
    x, y = point
    pts = np.asarray(loop, dtype=float)
    x1, y1 = pts[:, 0], pts[:, 1]
    x2, y2 = np.roll(x1, -1), np.roll(y1, -1)
    crosses = ((y1 > y) != (y2 > y)) & (
        x < (x2 - x1) * (y - y1) / np.where(y2 == y1, 1e-30, y2 - y1) + x1
    )
    return bool(np.count_nonzero(crosses) % 2)


def build_mesh(outer, holes, floor_z, ceil_z):
    xs = sorted({p[0] for p in outer} | {p[0] for h in holes for p in h})
    ys = sorted({p[1] for p in outer} | {p[1] for h in holes for p in h})

    inside = np.zeros((len(xs) - 1, len(ys) - 1), dtype=bool)
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            center = ((xs[i] + xs[i + 1]) / 2.0, (ys[j] + ys[j + 1]) / 2.0)
            inside[i, j] = point_in_loops(center, outer, holes)

    # 대각선으로만 맞닿은 칸은 모서리 한 점에서 벽이 4장 만나 non-manifold가 된다.
    # 빈 칸 하나를 채워 두 칸을 실제로 잇는다.
    while True:
        a = inside[:-1, :-1] & inside[1:, 1:] & ~inside[1:, :-1] & ~inside[:-1, 1:]
        b = inside[1:, :-1] & inside[:-1, 1:] & ~inside[:-1, :-1] & ~inside[1:, 1:]
        if not a.any() and not b.any():
            break
        for i, j in np.argwhere(a):
            inside[i + 1, j] = True
        for i, j in np.argwhere(b):
            inside[i, j] = True

    index = {}
    vertices = []

    def vertex(xi, yi, top):
        key = (xi, yi, top)
        if key not in index:
            index[key] = len(vertices)
            vertices.append([xs[xi], ys[yi], ceil_z if top else floor_z])
        return index[key]

    faces = []
    for i in range(inside.shape[0]):
        for j in range(inside.shape[1]):
            if not inside[i, j]:
                continue
            b00, b10 = vertex(i, j, False), vertex(i + 1, j, False)
            b11, b01 = vertex(i + 1, j + 1, False), vertex(i, j + 1, False)
            t00, t10 = vertex(i, j, True), vertex(i + 1, j, True)
            t11, t01 = vertex(i + 1, j + 1, True), vertex(i, j + 1, True)
            # 바닥은 아래를 향하고 천장은 위를 향하도록(법선이 바깥쪽)
            faces += [[b00, b11, b10], [b00, b01, b11]]
            faces += [[t00, t10, t11], [t00, t11, t01]]
            if i == 0 or not inside[i - 1, j]:
                faces += [[b00, t00, t01], [b00, t01, b01]]
            if i == inside.shape[0] - 1 or not inside[i + 1, j]:
                faces += [[b10, b11, t11], [b10, t11, t10]]
            if j == 0 or not inside[i, j - 1]:
                faces += [[b00, b10, t10], [b00, t10, t00]]
            if j == inside.shape[1] - 1 or not inside[i, j + 1]:
                faces += [[b01, t01, t11], [b01, t11, b11]]

    return np.asarray(vertices, dtype=float), np.asarray(faces, dtype=int), inside, xs, ys


def topology(vertices, faces, tolerance=1e-9):
    tri = vertices[faces]
    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    areas = 0.5 * np.linalg.norm(normals, axis=1)
    centroids = tri.mean(axis=1)
    volume = float(np.sum(np.einsum("ij,ij->i", centroids, normals / 2.0)) / 3.0)

    edges = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    edges = np.sort(edges, axis=1)
    counts = Counter(map(tuple, edges))
    boundary = [list(e) for e, c in counts.items() if c == 1]
    non_manifold = [{"edge": list(e), "triangle_count": c} for e, c in counts.items() if c > 2]

    rounded = np.round(vertices / max(tolerance, 1e-12)).astype(np.int64)
    _, first, inverse = np.unique(rounded, axis=0, return_index=True, return_inverse=True)
    duplicate_vertex_count = int(len(vertices) - len(first))

    canonical = Counter(map(tuple, np.sort(faces, axis=1)))
    return {
        "vertex_count": int(len(vertices)),
        "triangle_count": int(len(faces)),
        "edge_count": int(len(counts)),
        "degenerate_triangle_count": int(np.count_nonzero(areas <= tolerance)),
        "degenerate_triangle_indices": np.flatnonzero(areas <= tolerance).tolist(),
        "duplicate_face_count": int(sum(c - 1 for c in canonical.values() if c > 1)),
        "duplicate_vertex_count": duplicate_vertex_count,
        "duplicate_vertex_pairs": [],
        "boundary_edge_count": len(boundary),
        "boundary_edges": boundary[:50],
        "non_manifold_edge_count": len(non_manifold),
        "non_manifold_edges": non_manifold[:50],
        "connected_component_count": 1,
        "signed_volume": volume,
        "closed_manifold_success": bool(not boundary and not non_manifold),
        "surface_area": float(np.sum(areas)),
    }


# ---------- 4. 출력 ----------

def keyhole_polygon(outer, holes):
    """구멍을 바깥 윤곽에 이어 붙여 point-in-polygon이 맞는 단일 다각형을 만든다."""
    polygon = list(outer)
    for hole in holes:
        hi = int(np.argmax([p[0] for p in hole]))
        oi = int(np.argmin([abs(p[0] - hole[hi][0]) + abs(p[1] - hole[hi][1]) for p in polygon]))
        rotated = hole[hi:] + hole[:hi]
        polygon = polygon[: oi + 1] + rotated + [rotated[0]] + polygon[oi:]
    return polygon


def write_obj(path, vertices, faces, inside_counts):
    lines = ["# RFVisualizer complex proxy room envelope", "mtllib room_envelope_metric.mtl"]
    for v in vertices:
        lines.append("v {:.6f} {:.6f} {:.6f}".format(*v))
    lines.append("o room_envelope")
    lines.append("usemtl wall")
    for f in faces:
        lines.append("f {} {} {}".format(f[0] + 1, f[1] + 1, f[2] + 1))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (path.parent / "room_envelope_metric.mtl").write_text(
        "newmtl wall\nKa 0.2 0.2 0.2\nKd 0.72 0.74 0.78\nKs 0.0 0.0 0.0\nd 1.0\nillum 1\n",
        encoding="utf-8",
    )


def metric_transform(axes, grid_origin_uv, origin_cell, resolution, floor_h, scale):
    """PGSR 장면 좌표 -> 미터 좌표의 4x4 affine과 그 역행렬.

    build_mesh가 정점을 만드는 식에서 그대로 유도한다.
        u = p·au,  cell_x = (u - ub0)/res,  metric_x = (cell_x - origin_x)*res*scale
        => metric_x = scale*(p·au) - scale*(ub0 + origin_x*res)
    z도 같은 꼴이며 기준이 floor_h라 바닥이 0, 천장이 scale*(ceil-floor)가 된다.
    배율만 넣으면 회전·평행이동이 빠져 PGSR Mesh와 겹치지 않는다.
    """
    axis_u, axis_v, axis_up = axes
    rotation = np.vstack([axis_u, axis_v, axis_up])
    offset = np.array([
        grid_origin_uv[0] + origin_cell[0] * resolution,
        grid_origin_uv[1] + origin_cell[1] * resolution,
        floor_h,
    ])
    forward = np.eye(4)
    forward[:3, :3] = scale * rotation
    forward[:3, 3] = -scale * offset
    # m = scale*R@p - scale*offset  =>  p = R.T @ (m/scale + offset)
    inverse = np.eye(4)
    inverse[:3, :3] = rotation.T / scale
    inverse[:3, 3] = rotation.T @ offset
    return forward, inverse


def plane_from_points(a, b, c):
    normal = np.cross(np.asarray(b) - np.asarray(a), np.asarray(c) - np.asarray(a))
    length = np.linalg.norm(normal)
    normal = normal / length
    return [*normal.tolist(), float(-np.dot(normal, a))]


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scene_id")
    parser.add_argument("--mesh", required=True, type=Path)
    parser.add_argument("--up-vector", nargs=3, type=float, metavar=("X", "Y", "Z"),
                        help="생략하면 메시에서 자동 검출한다(부호까지). Mesh를 바꾸면 축이 달라질 수 있으니 권장")
    parser.add_argument("--ceiling-height-m", type=float, default=2.7,
                        help="실측이 없을 때 쓰는 층고 가정값(기본 2.7m). 미터 배율을 정한다.")
    parser.add_argument("--resolution", type=float, default=0.04, help="점유 격자 칸 크기(장면 단위)")
    parser.add_argument("--band", nargs=2, type=float, default=(-0.15, 0.25),
                        metavar=("LO", "HI"),
                        help="실내 공간으로 볼 높이 구간. 바닥=0, 천장=1인 비율이며 "
                             "걸어서 촬영한 장면은 바닥이 가장 잘 복원되므로 기본값이 바닥 근처다")
    parser.add_argument("--min-hits", type=int, default=2, help="칸을 점유로 볼 최소 점 개수")
    parser.add_argument("--closing-cells", type=int, default=5,
                        help="바닥 복원이 끊긴 자리를 메울 커널 크기(칸). Poisson/blend 메시처럼 "
                             "바닥에 틈이 있으면 9 정도로 올린다")
    parser.add_argument("--wall-carve", type=int, default=40,
                        help="이 개수 이상 벽 점이 있는 칸은 벽으로 보고 실내에서 제외한다(0=끔)")
    parser.add_argument("--min-feature-m", type=float, default=0.5, help="정점을 맞출 격자 크기. 이보다 작은 요철은 사라진다")
    parser.add_argument("--wall-align-m", type=float, default=0.5,
                        help="이 거리 안의 벽선을 긴 벽쪽으로 모아 계단을 없앤다(0=끔). 너무 크면 좁은 통로가 사라진다")
    parser.add_argument("--min-hole-area-m2", type=float, default=4.0, help="이보다 작은 구멍은 무시한다")
    parser.add_argument("--output", type=Path, help="기본값: scenes/<scene_id>/proxy_mesh/complex_envelope")
    parser.add_argument("--point-cloud", type=Path,
                        help="함께 미터 좌표로 내보낼 PGSR Point Cloud. Mesh와 축이 달라도 자동 정렬한다")
    parser.add_argument("--export-aligned-pgsr", action="store_true",
                        help="PGSR Mesh를 미터 좌표로 변환한 사본도 저장한다. "
                             "Blender/MeshLab에 둘을 그냥 올려도 겹쳐 보인다.")
    args = parser.parse_args(argv)

    mesh_path = (REPO_ROOT / args.mesh).resolve()
    if not mesh_path.is_file():
        raise SystemExit(f"오류: {mesh_path}가 없습니다.")
    output = (REPO_ROOT / args.output).resolve() if args.output else (
        REPO_ROOT / "scenes" / args.scene_id / "proxy_mesh" / "complex_envelope"
    )
    output.mkdir(parents=True, exist_ok=True)

    occ, ub, vb, axes, floor_h, ceil_h, wall_counts = occupancy_grid(
        mesh_path, args.up_vector, args.resolution, args.band[0], args.band[1],
        args.min_hits, args.wall_carve, args.closing_cells,
    )
    scale = args.ceiling_height_m / (ceil_h - floor_h)
    print(f"[1] 점유 칸 {occ.sum()}개, 바닥 h={floor_h:+.3f} 천장 h={ceil_h:+.3f} "
          f"(장면단위 {ceil_h - floor_h:.3f}) -> {scale:.4f} m/장면단위")

    loops = trace_loops(occ)
    loops = [merge_collinear(loop) for loop in loops]
    cell_m2 = (args.resolution * scale) ** 2
    min_cells = max(1, int(round(args.min_feature_m / (args.resolution * scale))))
    loops = [drop_small_jogs(loop, min_cells) for loop in loops]
    loops = [loop for loop in loops if len(loop) >= 4]
    # 굵은 격자 스냅만으로는 긴 벽이 1칸씩 오르내리는 계단이 남는다.
    # 가까운 벽선을 긴 벽 쪽으로 모아 평평하게 만든다.
    if args.wall_align_m > 0:
        align_cells = max(1, int(round(args.wall_align_m / (args.resolution * scale))))
        loops = snap_to_wall_lines(loops, align_cells)

    areas = [signed_area(loop) for loop in loops]
    outer_index = int(np.argmax(np.abs(areas)))
    outer = loops[outer_index]
    if areas[outer_index] < 0:
        outer = outer[::-1]
    holes = []
    for i, loop in enumerate(loops):
        if i == outer_index:
            continue
        if abs(areas[i]) * cell_m2 < args.min_hole_area_m2:
            continue
        holes.append(loop if signed_area(loop) > 0 else loop[::-1])
    print(f"[2] 윤곽선: 바깥 정점 {len(outer)}개, 구멍 {len(holes)}개 "
          f"(정점 {[len(h) for h in holes]})")

    floor_z, ceil_z = 0.0, args.ceiling_height_m
    verts_cell, faces, inside, xs, ys = build_mesh(outer, holes, floor_z, ceil_z)
    print(f"[3] 격자 {len(xs)-1}x{len(ys)-1}, 내부 칸 {int(inside.sum())}개")

    # 격자 칸 번호 -> 미터. 원점은 사용된 격자의 최소 모서리로 옮겨 좌표를 양수로 둔다.
    cell_m = args.resolution * scale
    origin_cell = np.array([verts_cell[:, 0].min(), verts_cell[:, 1].min()])

    def cell_to_metric_xy(cx, cy):
        return (float((cx - origin_cell[0]) * cell_m), float((cy - origin_cell[1]) * cell_m))

    vertices = verts_cell.copy()
    vertices[:, 0] = (verts_cell[:, 0] - origin_cell[0]) * cell_m
    vertices[:, 1] = (verts_cell[:, 1] - origin_cell[1]) * cell_m

    report = topology(vertices, faces)
    print(f"[4] 정점 {report['vertex_count']} 삼각형 {report['triangle_count']} "
          f"닫힌manifold={report['closed_manifold_success']} "
          f"boundary={report['boundary_edge_count']} nonmanifold={report['non_manifold_edge_count']} "
          f"부피={report['signed_volume']:.1f}m^3")
    if not report["closed_manifold_success"]:
        raise SystemExit("오류: 닫힌 manifold가 아닙니다.")
    if report["signed_volume"] <= 0:
        faces = faces[:, ::-1]
        report = topology(vertices, faces)
        print(f"    법선을 뒤집어 부피={report['signed_volume']:.1f}m^3")

    def to_metric(loop, z):
        return [[*cell_to_metric_xy(p[0], p[1]), z] for p in loop]

    footprint = keyhole_polygon(outer, holes)
    bottom_corners = to_metric(footprint, floor_z)
    top_corners = to_metric(footprint, ceil_z)

    interior = None
    for i, j in np.argwhere(inside):
        cx, cy = cell_to_metric_xy((xs[i] + xs[i + 1]) / 2.0, (ys[j] + ys[j + 1]) / 2.0)
        interior = [cx, cy, (floor_z + ceil_z) / 2.0]
        break
    if interior is None:
        raise SystemExit("오류: 내부 칸이 없습니다.")

    wall_planes, wall_centroids = [], []
    for loop in [outer] + holes:
        metric_loop = to_metric(loop, floor_z)
        for i, start in enumerate(metric_loop):
            end = metric_loop[(i + 1) % len(metric_loop)]
            top = [end[0], end[1], ceil_z]
            plane = plane_from_points(start, end, top)
            if np.dot(plane[:3], np.asarray(interior) - np.asarray(start)) < 0:
                plane = [-value for value in plane]
            wall_planes.append(plane)
            wall_centroids.append([(start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0, (floor_z + ceil_z) / 2.0])

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    banner = "PROVISIONAL GEOMETRY - DERIVED FROM PGSR MESH, NOT ON-SITE MEASUREMENT"

    scale_matrix, inverse_matrix = metric_transform(
        axes, (ub[0], vb[0]), origin_cell, args.resolution, floor_h, scale
    )
    round_trip = float(np.max(np.abs(scale_matrix @ inverse_matrix - np.eye(4))))
    if round_trip > 1e-8:
        raise SystemExit(f"오류: calibration 행렬이 서로 역행렬이 아닙니다(오차 {round_trip}).")

    obj_path = output / "room_envelope_metric.obj"
    write_obj(obj_path, vertices, faces, int(inside.sum()))

    metadata = {
        "schema_version": "1.0",
        "algorithm": {"name": "rfvisualizer_complex_proxy_envelope", "version": "0.1.0"},
        "created_at": now,
        "status": "provisional",
        "confidence": "low",
        "is_provisional": True,
        "warning_banner": banner,
        "source": {
            "mesh": str(mesh_path),
            "up_vector": [float(v) for v in axes[2]],
            "ceiling_height_assumption_m": args.ceiling_height_m,
            "settings": {
                "resolution": args.resolution,
                "band": list(args.band),
                "min_hits": args.min_hits,
                "closing_cells": args.closing_cells,
                "wall_carve": args.wall_carve,
                "min_feature_m": args.min_feature_m,
                "wall_align_m": args.wall_align_m,
                "min_hole_area_m2": args.min_hole_area_m2,
            },
        },
        "coordinate_system": {
            "unit": "meter", "origin": "occupancy grid minimum corner",
            "up_axis": "+Z", "handedness": "right",
            "T_metric_from_scene": scale_matrix.tolist(),
            "T_scene_from_metric": inverse_matrix.tolist(),
        },
        "bottom_corners": bottom_corners,
        "top_corners": top_corners,
        "interior_point": interior,
        "plane_centroids": {
            "floor": [interior[0], interior[1], floor_z],
            "ceiling": [interior[0], interior[1], ceil_z],
            "walls": wall_centroids,
        },
        "normalized_plane_equations": {
            "floor": [0.0, 0.0, 1.0, -floor_z],
            "ceiling": [0.0, 0.0, -1.0, ceil_z],
            "walls": wall_planes,
        },
        "bounds": {
            "min": vertices.min(axis=0).tolist(),
            "max": vertices.max(axis=0).tolist(),
            "extent": (vertices.max(axis=0) - vertices.min(axis=0)).tolist(),
            "diagonal": float(np.linalg.norm(vertices.max(axis=0) - vertices.min(axis=0))),
        },
        "surface_area_square_meters": report["surface_area"],
        "signed_volume_cubic_meters": report["signed_volume"],
        "absolute_volume_cubic_meters": abs(report["signed_volume"]),
        "floor_ceiling_height": args.ceiling_height_m,
        "polygon": {
            "bottom_xy_coordinates_meters": [[p[0], p[1]] for p in bottom_corners],
            "winding": "counter_clockwise_from_positive_z",
            "hole_count": len(holes),
            "note": "구멍이 있는 평면이라 bottom_corners는 구멍을 이어 붙인 keyhole 다각형이다.",
        },
        "mesh_summary": {"vertex_count": report["vertex_count"], "triangle_count": report["triangle_count"]},
        "topology_summary": report,
        "output_files": {"metric_obj": obj_path.name},
    }
    (output / "room_envelope_metric.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    calibration = {
        "schema_version": "1.0",
        "algorithm": {"name": "rfvisualizer_complex_proxy_calibration", "version": "0.1.0"},
        "created_at": now,
        "status": "provisional",
        "confidence": "low",
        "is_provisional": True,
        "warning_banner": banner,
        "scale": {
            "method": "assumed_ceiling_height",
            "uniform_scale_only": True,
            "resolved_meters_per_scene_unit": scale,
            "references": [{
                "name": "assumed_ceiling_height",
                "scene_distance": ceil_h - floor_h,
                "real_distance_m": args.ceiling_height_m,
                "source": "assumption_not_measured",
                "confidence": "low",
            }],
        },
        "transform": {
            "resolved_meters_per_scene_unit": scale,
            "T_metric_from_scene": scale_matrix.tolist(),
            "T_scene_from_metric": inverse_matrix.tolist(),
        },
        "source_up_vector": [float(v) for v in axes[2]],
        "target_up_vector": [0.0, 0.0, 1.0],
    }
    (output / "calibration.json").write_text(
        json.dumps(calibration, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.export_aligned_pgsr or args.point_cloud:
        import open3d as o3d

        source = o3d.io.read_triangle_mesh(str(mesh_path))
        mesh_points = np.asarray(source.vertices).copy()
        source.transform(scale_matrix)
        aligned = output / "pgsr_mesh_metric.ply"
        o3d.io.write_triangle_mesh(str(aligned), source)
        print(f"[5] PGSR Mesh 미터 좌표 사본: {aligned}")

        if args.point_cloud:
            cloud_path = (REPO_ROOT / args.point_cloud).resolve()
            cloud = o3d.io.read_point_cloud(str(cloud_path))
            raw = np.asarray(cloud.points)
            points = finite_points(raw)
            if len(points) < len(raw):
                print(f"    Point Cloud의 비유한 점 {len(raw) - len(points)}개를 제외합니다.")
            rotation, error = align_axes_to(points, mesh_points)
            if not np.allclose(rotation, np.eye(3)):
                print("    Point Cloud 축이 Mesh와 달라 자동 정렬합니다 "
                      f"(백분위 오차 {error:.3f})")
            keep = np.all(np.isfinite(raw), axis=1)
            cloud = cloud.select_by_index(np.flatnonzero(keep))
            cloud.points = o3d.utility.Vector3dVector(np.asarray(cloud.points) @ rotation.T)
            cloud.transform(scale_matrix)
            cloud_out = output / "pgsr_point_cloud_metric.ply"
            o3d.io.write_point_cloud(str(cloud_out), cloud)
            print(f"    Point Cloud 미터 좌표 사본: {cloud_out}")

    print(f"[6] 저장 완료: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
