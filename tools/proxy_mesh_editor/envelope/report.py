"""Room Envelope 결과 문서 조립과 저장. CLI와 인터랙티브 도구가 함께 쓴다."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .. import __version__
from ..io.metadata_io import write_json
from .builder import EnvelopeMesh
from .candidate_loader import EnvelopeCandidates
from .exporter import export_envelope_geometry


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_envelope_outputs(
    selected: EnvelopeCandidates,
    envelope_config: Dict[str, Any],
    envelope_config_path: Path,
    mesh: EnvelopeMesh,
    topology: Dict[str, Any],
    geometry: Dict[str, Any],
    warnings: List[str],
    output: Path,
) -> Dict[str, Any]:
    """room_envelope.json/obj/ply와 topology_report.json을 저장하고 envelope 문서를 돌려준다."""

    created_at = _utc_now()
    output = Path(output).expanduser().resolve()
    files = export_envelope_geometry(
        mesh, output, envelope_config["room_envelope"]["output"]
    )
    envelope_path = output / "room_envelope.json"
    topology_path = output / "topology_report.json"
    files["envelope_metadata"] = str(envelope_path.resolve())
    files["topology_report"] = str(topology_path.resolve())

    topology_document: Dict[str, Any] = {
        "schema_version": "1.0",
        "algorithm": {
            "name": "rfvisualizer_room_envelope_validation",
            "version": __version__,
        },
        "created_at": created_at,
        "topology": topology,
        "geometry": geometry,
        "validation_warnings": warnings,
        "success": bool(
            topology["closed_manifold_success"] and geometry["geometry_success"]
        ),
    }
    write_json(topology_path, topology_document)

    wall_objects = []
    for index, (candidate, equation, rectangle_diagnostic) in enumerate(
        zip(
            mesh.wall_candidates,
            mesh.normalized_wall_equations,
            mesh.candidate_rectangle_diagnostics,
        )
    ):
        wall_objects.append(
            {
                "object_name": "wall_{:03d}".format(index),
                "candidate_id": candidate.candidate_id,
                "normalized_plane_equation": equation.tolist(),
                "candidate_rectangle_comparison": rectangle_diagnostic,
            }
        )
    document: Dict[str, Any] = {
        "schema_version": "1.0",
        "algorithm": {
            "name": "rfvisualizer_room_envelope_builder",
            "version": __version__,
        },
        "created_at": created_at,
        "source_candidate_documents": {
            "plane_candidates": str(selected.plane_document_path),
            "wall_candidates": str(selected.wall_document_path),
        },
        "envelope_config_path": str(Path(envelope_config_path).expanduser().resolve()),
        "envelope_config": envelope_config,
        "up_vector": selected.up_vector.tolist(),
        "selected_candidates": {
            "floor": mesh.floor_candidate.candidate_id,
            "ceiling": mesh.ceiling_candidate.candidate_id,
            "input_ordered_walls": mesh.input_wall_ids,
            "normalized_ordered_walls": mesh.normalized_wall_ids,
        },
        "normalized_plane_equations": {
            "floor": mesh.normalized_floor_equation.tolist(),
            "ceiling": mesh.normalized_ceiling_equation.tolist(),
            "walls": [value.tolist() for value in mesh.normalized_wall_equations],
        },
        "interior_point": mesh.interior_point.tolist(),
        "bottom_corners": mesh.bottom_corners.tolist(),
        "top_corners": mesh.top_corners.tolist(),
        "polygon": {
            "coordinates_2d": mesh.polygon_2d.tolist(),
            "ceiling_coordinates_2d": mesh.top_polygon_2d.tolist(),
            "winding": mesh.polygon_winding,
            "signed_area": mesh.polygon_signed_area,
            "edge_lengths": mesh.polygon_edge_lengths.tolist(),
        },
        "floor_ceiling_height": mesh.height_statistics,
        "wall_intersection_diagnostics": mesh.intersection_diagnostics,
        "wall_objects": wall_objects,
        "mesh_summary": {
            "vertex_count": int(len(mesh.vertices)),
            "triangle_count": int(len(mesh.faces)),
            "orientation_flip_count": int(mesh.orientation_flip_count),
        },
        "topology_summary": topology,
        "geometry_validation": geometry,
        "validation_warnings": warnings,
        "output_files": files,
    }
    write_json(envelope_path, document)
    return document
