import json

from tools.proxy_mesh_editor.envelope.config import DEFAULT_ENVELOPE_CONFIG
from tools.proxy_mesh_editor.envelope.selection import (
    EnvelopeSelectionState,
    attempt_build,
    resolve_envelope_config,
)
from tools.proxy_mesh_editor.tests._envelope_test_utils import make_envelope_candidates


RECTANGLE = [[-2.0, -4.0], [2.0, -4.0], [2.0, 4.0], [-2.0, 4.0]]


def _write_documents(tmp_path, candidates):
    scene = {"up_vector": candidates.up_vector.tolist(), "estimated_extent": 20.0}
    plane_path = tmp_path / "plane_candidates.json"
    wall_path = tmp_path / "wall_candidates.json"
    plane_path.write_text(
        json.dumps(
            {
                "scene": scene,
                "plane_candidates": [
                    candidates.floor.to_dict(),
                    candidates.ceiling.to_dict(),
                ],
            }
        ),
        encoding="utf-8",
    )
    wall_path.write_text(
        json.dumps(
            {
                "scene": scene,
                "wall_candidates": [candidate.to_dict() for candidate in candidates.walls],
            }
        ),
        encoding="utf-8",
    )
    return plane_path, wall_path


def test_selection_state_toggles():
    state = EnvelopeSelectionState()
    state.toggle_floor("plane_a")
    assert state.floor_id == "plane_a"
    state.toggle_floor("plane_a")
    assert state.floor_id is None

    state.toggle_wall("wall_000")
    state.toggle_wall("wall_001")
    assert state.wall_ids == ["wall_000", "wall_001"]
    state.toggle_wall("wall_000")
    assert state.wall_ids == ["wall_001"]
    state.toggle_wall("wall_000")
    assert state.wall_ids == ["wall_001", "wall_000"]

    assert not state.is_ready()
    state.toggle_ceiling("plane_b")
    state.toggle_floor("plane_a")
    state.toggle_wall("wall_002")
    assert state.is_ready()

    state.reset()
    assert state.floor_id is None and state.ceiling_id is None and state.wall_ids == []


def test_resolve_envelope_config_fills_selection():
    state = EnvelopeSelectionState(floor_id="plane_floor", ceiling_id="plane_ceiling", wall_ids=["wall_000", "wall_001"])
    config = resolve_envelope_config(DEFAULT_ENVELOPE_CONFIG, state)
    room = config["room_envelope"]
    assert room["floor"]["candidate_id"] == "plane_floor"
    assert room["ceiling"]["candidate_id"] == "plane_ceiling"
    assert room["ordered_walls"] == [
        {"candidate_id": "wall_000"},
        {"candidate_id": "wall_001"},
    ]
    # 원본 기본 설정은 그대로 유지되어야 한다 (사본이어야 함).
    assert DEFAULT_ENVELOPE_CONFIG["room_envelope"]["floor"]["candidate_id"] == ""


def test_attempt_build_reports_incomplete_selection_without_raising():
    state = EnvelopeSelectionState()
    result = attempt_build(
        plane_path="plane_candidates.json",
        wall_path="wall_candidates.json",
        base_config=DEFAULT_ENVELOPE_CONFIG,
        state=state,
    )
    assert result.mesh is None
    assert "Floor" in result.error


def test_attempt_build_succeeds_for_valid_ordered_walls(tmp_path):
    candidates = make_envelope_candidates(RECTANGLE)
    plane_path, wall_path = _write_documents(tmp_path, candidates)
    state = EnvelopeSelectionState(
        floor_id=candidates.floor.candidate_id,
        ceiling_id=candidates.ceiling.candidate_id,
        wall_ids=[candidate.candidate_id for candidate in candidates.walls],
    )
    result = attempt_build(plane_path, wall_path, DEFAULT_ENVELOPE_CONFIG, state)
    assert result.error is None
    assert result.mesh is not None
    assert result.candidates is not None
    assert len(result.mesh.wall_candidates) == len(candidates.walls)


def test_attempt_build_surfaces_build_error_instead_of_raising(tmp_path):
    candidates = make_envelope_candidates(RECTANGLE)
    plane_path, wall_path = _write_documents(tmp_path, candidates)
    # 벽 순서를 뒤섞어 인접하지 않게 만들면 self-intersection으로 실패해야 한다.
    scrambled = [
        candidates.walls[0].candidate_id,
        candidates.walls[2].candidate_id,
        candidates.walls[1].candidate_id,
        candidates.walls[3].candidate_id,
    ]
    state = EnvelopeSelectionState(
        floor_id=candidates.floor.candidate_id,
        ceiling_id=candidates.ceiling.candidate_id,
        wall_ids=scrambled,
    )
    result = attempt_build(plane_path, wall_path, DEFAULT_ENVELOPE_CONFIG, state)
    assert result.mesh is None
    assert result.error
