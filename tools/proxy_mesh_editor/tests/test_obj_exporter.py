import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import pytest
import yaml

from tools.proxy_mesh_editor.export.obj_exporter import ObjExportError, export_obj_bundle
from tools.proxy_mesh_editor.io.metadata_io import MetadataError
from tools.proxy_mesh_editor.main import run_export
from tools.proxy_mesh_editor.models import PlaneCandidate, PlaneRectangle


def _candidate(candidate_id="plane_000", source_pass="plane_extraction"):
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
        candidate_id=candidate_id,
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
        source_pass=source_pass,
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


def test_general_and_wall_candidates_export_together_with_valid_face_offsets(tmp_path):
    wall = _candidate("wall_000", "wall_extraction")
    exported = export_obj_bundle(
        [_candidate(), wall],
        [
            {"candidate_id": "plane_000", "semantic": "floor"},
            {"candidate_id": "wall_000", "semantic": "wall"},
        ],
        tmp_path,
    )

    combined = (tmp_path / "proxy_scene.obj").read_text()
    assert "o floor_000" in combined
    assert "o wall_000" in combined
    assert "f 5//2 6//2 7//2" in combined
    assert _vertices(tmp_path / "objects" / "wall_000.obj") == _vertices(
        tmp_path / "proxy_scene.obj"
    )[4:]
    assert exported[1]["source_pass"] == "wall_extraction"


def test_duplicate_selection_is_rejected(tmp_path):
    with pytest.raises(ObjExportError, match="두 번"):
        export_obj_bundle(
            [_candidate()],
            [
                {"candidate_id": "plane_000", "semantic": "floor"},
                {"candidate_id": "plane_000", "semantic": "wall"},
            ],
            tmp_path,
        )


def test_old_candidate_json_defaults_to_general_source_pass():
    data = _candidate().to_dict()
    data.pop("source_pass")
    data.pop("extraction_details")
    restored = PlaneCandidate.from_dict(data)
    assert restored.source_pass == "plane_extraction"
    assert restored.extraction_details == {}


def test_candidate_id_collision_between_documents_is_rejected(tmp_path):
    plane_path = tmp_path / "plane_candidates.json"
    wall_path = tmp_path / "wall_candidates.json"
    config_path = tmp_path / "config.yaml"
    plane_path.write_text(
        json.dumps({"plane_candidates": [_candidate().to_dict()]}), encoding="utf-8"
    )
    wall_path.write_text(
        json.dumps(
            {
                "wall_candidates": [
                    _candidate("plane_000", "wall_extraction").to_dict()
                ]
            }
        ),
        encoding="utf-8",
    )
    config_path.write_text(
        yaml.safe_dump(
            {"selection": [{"candidate_id": "plane_000", "semantic": "floor"}]}
        ),
        encoding="utf-8",
    )

    with pytest.raises(MetadataError, match="충돌"):
        run_export(
            SimpleNamespace(
                candidates=plane_path,
                wall_candidates=wall_path,
                config=config_path,
                output=tmp_path / "output",
            )
        )
