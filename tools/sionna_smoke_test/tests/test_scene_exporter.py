from pathlib import Path

import numpy as np

from tools.sionna_smoke_test.metric_scene_loader import MeshObject, MetricScene
from tools.sionna_smoke_test.scene_exporter import export_scene, read_ascii_ply


def _cube_scene(tmp_path: Path):
    vertices = np.asarray(
        [
            [0, 0, 0],
            [2, 0, 0],
            [2, 2, 0],
            [0, 2, 0],
            [0, 0, 2],
            [2, 0, 2],
            [2, 2, 2],
            [0, 2, 2],
        ],
        dtype=float,
    )
    parts = [
        ("floor_000", "floor", [[0, 2, 1], [0, 3, 2]]),
        ("ceiling_000", "ceiling", [[4, 5, 6], [4, 6, 7]]),
        ("wall_000", "wall", [[0, 1, 5], [0, 5, 4]]),
        ("wall_001", "wall", [[1, 2, 6], [1, 6, 5]]),
        ("wall_002", "wall", [[2, 3, 7], [2, 7, 6]]),
        ("wall_003", "wall", [[3, 0, 4], [3, 4, 7]]),
    ]
    objects = [
        MeshObject(name, semantic, semantic, np.asarray(faces, dtype=int))
        for name, semantic, faces in parts
    ]
    faces = np.vstack([value.faces for value in objects])
    return MetricScene(
        vertices=vertices,
        faces=faces,
        objects=objects,
        metric_metadata={},
        calibration={},
        paths={"metric_obj": tmp_path / "source.obj"},
    )


def test_scene_export_preserves_triangles_bounds_groups_and_materials(tmp_path: Path):
    settings = {
        "status": "provisional",
        "confidence": "low",
        "physically_validated": False,
        "scene": {"name": "box"},
        "materials": {
            "floor": {"preset": "concrete"},
            "ceiling": {"preset": "concrete"},
            "walls": {"preset": "concrete"},
        },
    }
    manifest = export_scene(_cube_scene(tmp_path), settings, tmp_path / "output")
    assert manifest["conversion_validation"]["success"]
    assert manifest["source_statistics"]["triangle_count"] == 12
    assert len(manifest["objects"]) == 6
    assert {value["semantic"] for value in manifest["objects"]} == {"floor", "ceiling", "wall"}
    floor_vertices, floor_faces = read_ascii_ply(
        tmp_path / "output" / "scene" / "meshes" / "floor_000.ply"
    )
    assert len(floor_vertices) == 4
    assert len(floor_faces) == 2
    xml = (tmp_path / "output" / "scene" / "scene.xml").read_text(encoding="utf-8")
    assert "itu-radio-material" in xml
    assert "mesh-wall_003" in xml
