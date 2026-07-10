import numpy as np

from tools.proxy_mesh_editor.envelope.builder import build_room_envelope
from tools.proxy_mesh_editor.envelope.exporter import export_envelope_geometry
from tools.proxy_mesh_editor.envelope.validator import analyze_topology

from tools.proxy_mesh_editor.tests._envelope_test_utils import (
    make_envelope_candidates,
    make_envelope_config,
)


def test_topology_report_detects_boundary_and_duplicate_vertex():
    candidates = make_envelope_candidates(
        [[-2.0, -4.0], [2.0, -4.0], [2.0, 4.0], [-2.0, 4.0]]
    )
    config = make_envelope_config(candidates)
    mesh = build_room_envelope(candidates, config)
    mesh.faces = mesh.faces[:-1]
    report = analyze_topology(mesh, tolerance=1e-6)
    assert report["boundary_edge_count"] > 0
    assert not report["closed_manifold_success"]

    mesh = build_room_envelope(candidates, config)
    mesh.vertices[1] = mesh.vertices[0]
    report = analyze_topology(mesh, tolerance=1e-6)
    assert report["duplicate_vertex_count"] > 0
    assert report["degenerate_triangle_count"] > 0


def test_combined_obj_uses_shared_global_vertices(tmp_path):
    candidates = make_envelope_candidates(
        [[-2.0, -4.0], [2.0, -4.0], [2.0, 4.0], [-2.0, 4.0]]
    )
    config = make_envelope_config(candidates)
    mesh = build_room_envelope(candidates, config)
    files = export_envelope_geometry(
        mesh, tmp_path, config["room_envelope"]["output"]
    )
    lines = (tmp_path / "room_envelope.obj").read_text().splitlines()
    assert sum(line.startswith("v ") for line in lines) == 8
    assert sum(line.startswith("f ") for line in lines) == 12
    assert "o floor_000" in lines
    assert "o ceiling_000" in lines
    assert "o wall_003" in lines
    assert len(files["individual_objects"]) == 6
