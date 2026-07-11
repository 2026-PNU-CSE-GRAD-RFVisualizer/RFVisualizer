from pathlib import Path

import numpy as np

from tools.proxy_mesh_editor.calibration.metric_exporter import write_metric_obj_and_mtl
from tools.proxy_mesh_editor.calibration.metric_transform import build_metric_transform, transform_points
from tools.proxy_mesh_editor.calibration.preview_exporter import load_obj_geometry


VALIDATION = {
    "maximum_rotation_determinant_error": 1e-8,
    "maximum_orthogonality_error": 1e-8,
    "maximum_axis_alignment_error": 1e-8,
    "maximum_round_trip_error": 1e-8,
}


def test_metric_obj_preserves_groups_materials_faces_and_copies_mtl(tmp_path: Path):
    source_obj = tmp_path / "source.obj"
    source_mtl = tmp_path / "source.mtl"
    source_mtl.write_text("newmtl floor\nKd 1 0 0\n", encoding="utf-8")
    source_obj.write_text(
        "mtllib source.mtl\n"
        "v 0 0 0\nv 1 0 0\nv 0 1 0\n"
        "o floor_000\ng floor\nusemtl floor\n"
        "vn 0 0 1\nf 1//1 2//1 3//1\n",
        encoding="utf-8",
    )
    geometry = load_obj_geometry(source_obj)
    envelope = {
        "up_vector": [0, 0, 1],
        "bottom_corners": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
    }
    transform = build_metric_transform(
        envelope,
        {"origin": {"corner_index": 0}, "x_axis": {"start_corner": 0, "end_corner": 1}},
        2.0,
        VALIDATION,
    )
    output = tmp_path / "output"
    obj, mtl, preservation = write_metric_obj_and_mtl(
        source_obj,
        geometry,
        transform_points(geometry.vertices, transform),
        transform,
        output,
        "provisional",
    )
    text = obj.read_text(encoding="utf-8")
    assert text.startswith("# PROVISIONAL METRIC CALIBRATION")
    assert "mtllib room_envelope_metric.mtl" in text
    assert "o floor_000\ng floor\nusemtl floor" in text
    assert "f 1//1 2//1 3//1" in text
    assert mtl.read_text(encoding="utf-8") == source_mtl.read_text(encoding="utf-8")
    assert preservation["obj_structure_preserved"]
