"""Snapshot commands: one mouse drag becomes exactly one undo record."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Type

from .editor_state import EditorState


@dataclass
class StateCommand:
    state: EditorState
    before: Dict[str, Any]
    after: Dict[str, Any]
    object_id: Optional[str] = None

    def execute(self) -> None:
        self.state.restore_document(self.after)

    def undo(self) -> None:
        self.state.restore_document(self.before)


# 아래 subclass는 동작이 아니라 이름만 다르다. 클래스 이름이 그대로
# command_log.json의 "command" 값으로 기록되므로 개별 타입을 유지한다.
class AddObjectCommand(StateCommand):
    pass


class DeleteObjectCommand(StateCommand):
    pass


class DuplicateObjectCommand(StateCommand):
    pass


class TransformObjectCommand(StateCommand):
    pass


class ResizeObjectCommand(StateCommand):
    pass


class ChangeMaterialCommand(StateCommand):
    pass


class ChangePropertyCommand(StateCommand):
    pass


class EnableObjectCommand(StateCommand):
    pass


class CommandStack:
    def __init__(self, limit: int = 200):
        self.limit = int(limit)
        self._undo: List[StateCommand] = []
        self._redo: List[StateCommand] = []
        self.log: List[Dict[str, Any]] = []

    @property
    def undo_count(self) -> int:
        return len(self._undo)

    @property
    def redo_count(self) -> int:
        return len(self._redo)

    def commit(
        self,
        state: EditorState,
        before: Dict[str, Any],
        command_type: Type[StateCommand] = ChangePropertyCommand,
        object_id: Optional[str] = None,
        already_applied: bool = True,
    ) -> Optional[StateCommand]:
        after = state.snapshot_document()
        if before == after:
            return None
        command = command_type(
            state, deepcopy(before), deepcopy(after), object_id=object_id
        )
        if not already_applied:
            command.execute()
        self._undo.append(command)
        if len(self._undo) > self.limit:
            self._undo.pop(0)
        self._redo.clear()
        self._record("commit", command)
        return command

    def undo(self) -> bool:
        if not self._undo:
            return False
        command = self._undo.pop()
        command.undo()
        self._redo.append(command)
        self._record("undo", command)
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        command = self._redo.pop()
        command.execute()
        self._undo.append(command)
        self._record("redo", command)
        return True

    def _record(self, action: str, command: StateCommand) -> None:
        self.log.append(
            {
                "timestamp": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "action": action,
                "command": command.__class__.__name__,
                "object_id": command.object_id,
            }
        )
