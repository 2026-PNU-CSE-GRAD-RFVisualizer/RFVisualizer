"""GUI-independent state and math for right-mouse FPS camera movement."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Set, Tuple

import numpy as np


MOVEMENT_KEYS = frozenset({"w", "a", "s", "d"})
MIN_HORIZONTAL_FORWARD_NORM = 1.0e-3


@dataclass(frozen=True)
class FpsNavigationSettings:
    enabled: bool = True
    movement_speed_mps: float = 1.5
    sprint_multiplier: float = 3.0
    max_frame_delta_seconds: float = 0.05
    horizontal_only: bool = False

    @classmethod
    def from_dict(cls, value: Dict) -> "FpsNavigationSettings":
        return cls(
            enabled=bool(value.get("enabled", True)),
            movement_speed_mps=float(value.get("movement_speed_mps", 1.5)),
            sprint_multiplier=float(value.get("sprint_multiplier", 3.0)),
            max_frame_delta_seconds=float(
                value.get("max_frame_delta_seconds", 0.05)
            ),
            horizontal_only=bool(value.get("horizontal_only", False)),
        )


def camera_pose_from_view(
    view_matrix,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return eye, forward, right and up vectors from a world-to-camera matrix."""

    view = np.asarray(view_matrix, dtype=float)
    if view.shape != (4, 4) or not np.all(np.isfinite(view)):
        raise ValueError("Camera view matrix는 finite 4x4 matrix여야 합니다.")
    try:
        world_from_camera = np.linalg.inv(view)
    except np.linalg.LinAlgError as exc:
        raise ValueError("Camera view matrix가 singular입니다.") from exc
    eye = world_from_camera[:3, 3]
    right = world_from_camera[:3, 0]
    up = world_from_camera[:3, 1]
    forward = -world_from_camera[:3, 2]
    vectors = [eye, forward, right, up]
    if not all(np.all(np.isfinite(vector)) for vector in vectors):
        raise ValueError("Camera pose에 NaN/Inf가 있습니다.")
    return tuple(np.asarray(vector, dtype=float) for vector in vectors)


def _normalized(vector: np.ndarray, label: str) -> np.ndarray:
    length = float(np.linalg.norm(vector))
    if not np.isfinite(length) or length <= 1e-9:
        raise ValueError("{} vector의 길이가 0입니다.".format(label))
    return vector / length


def movement_basis(
    forward: np.ndarray,
    right: np.ndarray,
    horizontal_only: bool = False,
    previous_forward: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    forward = np.asarray(forward, dtype=float).copy()
    right = np.asarray(right, dtype=float).copy()
    if horizontal_only:
        forward[2] = 0.0
        right[2] = 0.0
        if float(np.linalg.norm(forward)) < MIN_HORIZONTAL_FORWARD_NORM:
            normalized_right = _normalized(right, "Camera right")
            forward = np.array(
                [-normalized_right[1], normalized_right[0], 0.0], dtype=float
            )
            if previous_forward is not None:
                previous = np.asarray(previous_forward, dtype=float).copy()
                if previous.shape != (3,) or not np.all(np.isfinite(previous)):
                    raise ValueError(
                        "Previous camera forward는 finite xyz vector여야 합니다."
                    )
                previous[2] = 0.0
                if float(np.linalg.norm(previous)) >= MIN_HORIZONTAL_FORWARD_NORM:
                    previous = _normalized(previous, "Previous camera forward")
                    if float(np.dot(forward, previous)) < 0.0:
                        forward *= -1.0
        forward = _normalized(forward, "Camera forward")
        # Derive a perpendicular horizontal right vector from the chosen
        # forward. This prevents tiny camera-matrix noise from making A/D
        # disagree with the stabilized W/S direction.
        right = np.array([forward[1], -forward[0], 0.0], dtype=float)
        return forward, right
    return _normalized(forward, "Camera forward"), _normalized(right, "Camera right")


@dataclass
class FpsCameraController:
    settings: FpsNavigationSettings
    active: bool = False
    pressed_keys: Set[str] = field(default_factory=set)
    _last_tick: Optional[float] = None
    _horizontal_forward: Optional[np.ndarray] = field(default=None, repr=False)

    def activate(self, now: float) -> None:
        if not self.settings.enabled:
            return
        self.active = True
        self.pressed_keys.clear()
        self._last_tick = float(now)
        self._horizontal_forward = None

    def deactivate(self) -> None:
        self.active = False
        self.pressed_keys.clear()
        self._last_tick = None
        self._horizontal_forward = None

    def set_key(self, key: str, is_down: bool) -> bool:
        normalized = str(key).lower()
        if normalized not in MOVEMENT_KEYS:
            return False
        if is_down and self.active:
            self.pressed_keys.add(normalized)
        else:
            self.pressed_keys.discard(normalized)
        return True

    def step(self, view_matrix, now: float, sprint: bool = False) -> np.ndarray:
        current = float(now)
        if not self.active:
            self._last_tick = None
            return np.zeros(3, dtype=float)
        previous = self._last_tick
        self._last_tick = current
        _, forward, right, _ = camera_pose_from_view(view_matrix)
        forward, right = movement_basis(
            forward,
            right,
            horizontal_only=self.settings.horizontal_only,
            previous_forward=self._horizontal_forward,
        )
        self._horizontal_forward = (
            forward.copy() if self.settings.horizontal_only else None
        )
        if previous is None or not self.pressed_keys:
            return np.zeros(3, dtype=float)
        elapsed = max(
            0.0,
            min(current - previous, self.settings.max_frame_delta_seconds),
        )
        if elapsed <= 0.0:
            return np.zeros(3, dtype=float)
        direction = np.zeros(3, dtype=float)
        if "w" in self.pressed_keys:
            direction += forward
        if "s" in self.pressed_keys:
            direction -= forward
        if "d" in self.pressed_keys:
            direction += right
        if "a" in self.pressed_keys:
            direction -= right
        length = float(np.linalg.norm(direction))
        if length <= 1e-9:
            return np.zeros(3, dtype=float)
        speed = self.settings.movement_speed_mps
        if sprint:
            speed *= self.settings.sprint_multiplier
        return direction / length * speed * elapsed
