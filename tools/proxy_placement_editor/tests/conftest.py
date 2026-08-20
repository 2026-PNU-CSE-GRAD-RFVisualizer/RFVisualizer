from pathlib import Path

import pytest

from tools.proxy_placement_editor.candidate_library import load_candidate_library
from tools.proxy_placement_editor.editor_core import EditorCore
from tools.proxy_placement_editor.editor_state import EditorState
from tools.proxy_placement_editor.scenario_io import load_editor_scenario
from tools.proxy_placement_editor.scene_loader import load_placement_scene


ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
ROOM_DIR = FIXTURES / "room"


@pytest.fixture(scope="session")
def project_root():
    return ROOT


@pytest.fixture(scope="session")
def fixtures_dir():
    return FIXTURES


@pytest.fixture(scope="session")
def placement_scene():
    return load_placement_scene(
        ROOM_DIR / "room_envelope_metric.json",
        ROOM_DIR / "calibration.json",
        ROOM_DIR / "room_envelope_metric.obj",
    )


@pytest.fixture
def draft_core(tmp_path, placement_scene):
    source = FIXTURES / "configs/proxy_draft.yaml"
    return EditorCore(
        placement_scene,
        EditorState(load_editor_scenario(source), source_path=source),
        load_candidate_library(FIXTURES / "configs/candidates.yaml"),
        tmp_path,
    )
