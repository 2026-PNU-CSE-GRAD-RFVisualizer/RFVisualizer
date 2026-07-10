import copy
import json

import pytest

from tools.proxy_mesh_editor.envelope.candidate_loader import load_envelope_candidates
from tools.proxy_mesh_editor.io.metadata_io import MetadataError
from tools.proxy_mesh_editor.tests._envelope_test_utils import (
    make_envelope_candidates,
    make_envelope_config,
)


RECTANGLE = [[-2.0, -4.0], [2.0, -4.0], [2.0, 4.0], [-2.0, 4.0]]


def _write_documents(tmp_path, candidates):
    scene = {
        "up_vector": candidates.up_vector.tolist(),
        "estimated_extent": 20.0,
    }
    plane_path = tmp_path / "plane_candidates.json"
    wall_path = tmp_path / "wall_candidates.json"
    plane_document = {
        "scene": scene,
        "plane_candidates": [
            candidates.floor.to_dict(),
            candidates.ceiling.to_dict(),
        ],
    }
    wall_document = {
        "scene": scene,
        "wall_candidates": [candidate.to_dict() for candidate in candidates.walls],
    }
    plane_path.write_text(json.dumps(plane_document), encoding="utf-8")
    wall_path.write_text(json.dumps(wall_document), encoding="utf-8")
    return plane_path, wall_path, wall_document


def test_candidate_loader_rejects_missing_id_and_nonfinite_plane(tmp_path):
    candidates = make_envelope_candidates(RECTANGLE)
    config = make_envelope_config(candidates)
    plane_path, wall_path, wall_document = _write_documents(tmp_path, candidates)

    missing_config = copy.deepcopy(config)
    missing_config["room_envelope"]["ordered_walls"][0]["candidate_id"] = "wall_missing"
    with pytest.raises(MetadataError, match="없습니다"):
        load_envelope_candidates(plane_path, wall_path, missing_config)

    wall_document["wall_candidates"][0]["plane_equation"][0] = float("nan")
    wall_path.write_text(json.dumps(wall_document), encoding="utf-8")
    with pytest.raises(MetadataError, match="평면식"):
        load_envelope_candidates(plane_path, wall_path, config)


def test_candidate_loader_requires_wall_source_pass(tmp_path):
    candidates = make_envelope_candidates(RECTANGLE)
    config = make_envelope_config(candidates)
    plane_path, wall_path, wall_document = _write_documents(tmp_path, candidates)
    wall_document["wall_candidates"][0]["source_pass"] = "plane_extraction"
    wall_path.write_text(json.dumps(wall_document), encoding="utf-8")
    with pytest.raises(MetadataError, match="source_pass"):
        load_envelope_candidates(plane_path, wall_path, config)
