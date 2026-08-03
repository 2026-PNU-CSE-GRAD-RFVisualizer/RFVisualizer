"""GUI 없이 단위 테스트 가능한 Floor/Ceiling/Wall 선택 상태와 즉시 빌드 시도.

3D Viewer는 이 모듈의 EnvelopeSelectionState/attempt_build만 호출한다.
Open3D를 import하지 않으므로 디스플레이가 없는 환경에서도 그대로 테스트할 수 있다.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..io.metadata_io import MetadataError
from .builder import EnvelopeBuildError, EnvelopeMesh, build_room_envelope
from .candidate_loader import EnvelopeCandidates, load_envelope_candidates
from .config import EnvelopeConfigError, validate_envelope_config


@dataclass
class EnvelopeSelectionState:
    floor_id: Optional[str] = None
    ceiling_id: Optional[str] = None
    wall_ids: List[str] = field(default_factory=list)

    def toggle_floor(self, candidate_id: str) -> None:
        self.floor_id = None if self.floor_id == candidate_id else candidate_id

    def toggle_ceiling(self, candidate_id: str) -> None:
        self.ceiling_id = None if self.ceiling_id == candidate_id else candidate_id

    def toggle_wall(self, candidate_id: str) -> None:
        if candidate_id in self.wall_ids:
            self.wall_ids.remove(candidate_id)
        else:
            self.wall_ids.append(candidate_id)

    def reset(self) -> None:
        self.floor_id = None
        self.ceiling_id = None
        self.wall_ids = []

    def is_ready(self) -> bool:
        return (
            self.floor_id is not None
            and self.ceiling_id is not None
            and len(self.wall_ids) >= 3
        )


def resolve_envelope_config(
    base_config: Dict[str, Any], state: EnvelopeSelectionState
) -> Dict[str, Any]:
    """base_config 사본에 현재 선택을 채운다. floor/ceiling/ordered_walls를 덮어쓴다."""

    config = copy.deepcopy(base_config)
    room = config["room_envelope"]
    room["floor"] = {"candidate_id": state.floor_id or ""}
    room["ceiling"] = {"candidate_id": state.ceiling_id or ""}
    room["ordered_walls"] = [{"candidate_id": value} for value in state.wall_ids]
    return config


@dataclass
class EnvelopeAttempt:
    mesh: Optional[EnvelopeMesh] = None
    envelope_config: Optional[Dict[str, Any]] = None
    candidates: Optional[EnvelopeCandidates] = None
    error: Optional[str] = None


def attempt_build(
    plane_path: Path,
    wall_path: Path,
    base_config: Dict[str, Any],
    state: EnvelopeSelectionState,
) -> EnvelopeAttempt:
    """선택이 불완전하거나 검증에 실패하면 예외 대신 에러 메시지를 담아 돌려준다."""

    if not state.is_ready():
        return EnvelopeAttempt(
            error="Floor 1개, Ceiling 1개, Wall 3개 이상을 선택하세요 "
            "(현재 Floor={}, Ceiling={}, Wall={}개).".format(
                state.floor_id or "-", state.ceiling_id or "-", len(state.wall_ids)
            )
        )
    config = resolve_envelope_config(base_config, state)
    try:
        config = validate_envelope_config(config)
        candidates = load_envelope_candidates(plane_path, wall_path, config)
        mesh = build_room_envelope(candidates, config)
    except (MetadataError, EnvelopeConfigError, EnvelopeBuildError) as exc:
        return EnvelopeAttempt(error=str(exc))
    return EnvelopeAttempt(mesh=mesh, envelope_config=config, candidates=candidates)
