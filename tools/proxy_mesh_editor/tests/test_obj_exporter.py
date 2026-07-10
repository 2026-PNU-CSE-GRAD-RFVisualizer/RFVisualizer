from pathlib import Path

import numpy as np

from tools.proxy_mesh_editor.export.obj_exporter import export_obj_bundle
from tools.proxy_mesh_editor.models import PlaneCandidate, PlaneRectangle


def _candidate():
    corners = np.asarray(
        [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [2.0, 1.0, 0.0], [0.0, 1.0, 0.0]]
    )
    rectangle = PlaneRectangle(
        origin=np.asarray([1.0, 0.5, 0.0]),
        basis_u=np.asarray([1.0, 0.0, 0.0]),
        basis_v=np.asarray([0.0, 1.0, 0.0]),
        bounds_2d={"u_min": -1.0, "u_max": 1.0, "v_min": -0.5, "v_max": 0.5},
        corners=corners,
        width=2.0,
        height=1.0,
        area=2.0,
    )
    return PlaneCandidate(
        candidate_id="plane_000",
        plane_equation=np.asarray([0.0, 0.0, 1.0, 0.0]),
        normal=np.asarray([0.0, 0.0, 1.0]),
        centroid=rectangle.origin,
        inlier_count=100,
        raw_ransac_inlier_count=100,
        inlier_ratio=0.5,
        remaining_inlier_ratio=0.5,
        fitting_rmse=0.0,
        mean_absolute_distance=0.0,
        rectangle=rectangle,
        orientation="horizontal",
        suggested_semantic="floor",
        semantic_confidence=1.0,
        semantic_reason="test",
        color=np.asarray([1.0, 0.0, 0.0]),
    )


def _vertices(path: Path):
    return [line for line in path.read_text().splitlines() if line.startswith("v ")]


def test_combined_and_individual_obj_use_identical_coordinates(tmp_path):
    exported = export_obj_bundle(
        [_candidate()],
        [{"candidate_id": "plane_000", "semantic": "floor"}],
        tmp_path,
    )

    combined = tmp_path / "proxy_scene.obj"
    individual = tmp_path / "objects" / "floor_000.obj"
    assert _vertices(combined) == _vertices(individual)
    text = combined.read_text()
    assert "o floor_000" in text
    assert "g floor" in text
    assert "usemtl floor" in text
    assert "f 1//1 2//1 3//1" in text
    assert exported[0]["obj_object_name"] == "floor_000"
