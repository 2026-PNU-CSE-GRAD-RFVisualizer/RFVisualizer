import numpy as np
import pytest

from tools.proxy_mesh_editor.envelope.polygon import (
    PolygonError,
    ear_clip_triangulation,
    find_self_intersections,
    signed_area,
)


def _triangle_area(points):
    return 0.5 * abs(np.cross(points[1] - points[0], points[2] - points[0]))


def test_concave_polygon_ear_clipping_is_complete_and_deterministic():
    polygon = np.asarray(
        [[0.0, 0.0], [3.0, 0.0], [3.0, 1.0], [1.0, 1.0], [1.0, 3.0], [0.0, 3.0]]
    )
    first = ear_clip_triangulation(polygon)
    second = ear_clip_triangulation(polygon)
    assert first.tolist() == second.tolist()
    assert len(first) == len(polygon) - 2
    area = sum(_triangle_area(polygon[triangle]) for triangle in first)
    assert area == pytest.approx(signed_area(polygon))


def test_self_intersecting_polygon_is_detected_and_rejected():
    bow_tie = np.asarray([[0.0, 0.0], [2.0, 2.0], [0.0, 2.0], [2.0, 0.0]])
    assert find_self_intersections(bow_tie)
    with pytest.raises(PolygonError):
        ear_clip_triangulation(bow_tie)
