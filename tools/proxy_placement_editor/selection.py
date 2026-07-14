"""Selection synchronization shared by viewport and object list."""

from __future__ import annotations

from typing import Callable, List, Optional

from .editor_state import EditorState


class SelectionController:
    def __init__(self, state: EditorState):
        self.state = state
        self._callbacks: List[Callable[[Optional[str]], None]] = []

    def subscribe(self, callback: Callable[[Optional[str]], None]) -> None:
        self._callbacks.append(callback)

    def select(self, object_id: Optional[str]) -> None:
        self.state.select(object_id)
        for callback in tuple(self._callbacks):
            callback(object_id)
