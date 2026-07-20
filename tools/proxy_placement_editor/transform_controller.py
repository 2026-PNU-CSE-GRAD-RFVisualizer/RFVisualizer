"""Deterministic translate/rotate/resize operations for obstacle dictionaries."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Optional, Sequence

import numpy as np

from tools.sionna_scenario.primitive_builder import rotation_matrix_xyz


class TransformError(ValueError):
    pass


def snap_value(value: float, increment: float, enabled: bool = True) -> float:
    number = float(value)
    step = float(increment)
    if not np.isfinite(number) or not np.isfinite(step) or step <= 0.0:
        raise TransformError("Snap 값과 간격은 유한하고 간격은 양수여야 합니다.")
    return round(number / step) * step if enabled else number


def _vector(value: Any, names: Sequence[str], label: str) -> np.ndarray:
    if isinstance(value, dict):
        result = [value.get(name) for name in names]
    else:
        result = value
    try:
        array = np.asarray(result, dtype=float)
    except (TypeError, ValueError) as exc:
        raise TransformError("{} 값이 숫자가 아닙니다.".format(label)) from exc
    if array.shape != (len(names),) or not np.all(np.isfinite(array)):
        raise TransformError(
            "{}에는 유한한 값 {}개가 필요합니다.".format(label, len(names))
        )
    return array


def _position(geometry: Dict[str, Any]) -> np.ndarray:
    anchor = geometry.get("anchor", {})
    mode = anchor if isinstance(anchor, str) else anchor.get("mode", "center")
    names = ("x", "y") if mode == "floor_at_xy" else ("x", "y", "z")
    return _vector(geometry.get("position_m"), names, "position_m")


def _set_position(geometry: Dict[str, Any], value: np.ndarray) -> None:
    names = ("x", "y") if len(value) == 2 else ("x", "y", "z")
    geometry["position_m"] = {
        name: float(value[index]) for index, name in enumerate(names)
    }


def _snap_vector(values: np.ndarray, increment: float, enabled: bool) -> np.ndarray:
    return np.asarray(
        [snap_value(value, increment, enabled) for value in values], dtype=float
    )


def translate_obstacle(
    obstacle: Dict[str, Any],
    delta_m: Sequence[float],
    axis: Optional[str] = None,
    snap_increment_m: float = 0.05,
    snap_enabled: bool = False,
) -> Dict[str, Any]:
    result = deepcopy(obstacle)
    geometry = result.setdefault("geometry", {})
    delta = _vector(delta_m, ("x", "y", "z"), "translation delta")
    if axis in {"x", "y", "z"}:
        mask = np.zeros(3, dtype=float)
        mask[{"x": 0, "y": 1, "z": 2}[axis]] = 1.0
        delta *= mask
    elif axis is not None:
        raise TransformError("Translate axis는 x/y/z 또는 None이어야 합니다.")
    anchor = geometry.get("anchor", {})
    mode = anchor if isinstance(anchor, str) else anchor.get("mode", "center")
    if mode == "explicit_transform":
        matrix = np.asarray(geometry.get("transform"), dtype=float)
        if matrix.shape != (4, 4):
            raise TransformError("explicit transform이 4x4가 아닙니다.")
        matrix[:3, 3] = _snap_vector(
            matrix[:3, 3] + delta, snap_increment_m, snap_enabled
        )
        geometry["transform"] = matrix.tolist()
    elif mode == "floor_at_xy":
        position = _position(geometry)
        position = _snap_vector(position + delta[:2], snap_increment_m, snap_enabled)
        _set_position(geometry, position)
        if abs(delta[2]) > 0.0:
            if not isinstance(anchor, dict):
                anchor = {"mode": "floor_at_xy"}
                geometry["anchor"] = anchor
            policy = anchor.setdefault(
                "floor_contact_policy", {"type": "anchor_point", "clearance_m": 0.0}
            )
            if isinstance(policy, str):
                policy = {"type": policy, "clearance_m": 0.0}
                anchor["floor_contact_policy"] = policy
            current = float(
                policy.get("clearance_m", geometry.get("floor_clearance_m", 0.0))
            )
            policy["clearance_m"] = max(
                0.0, snap_value(current + delta[2], snap_increment_m, snap_enabled)
            )
    else:
        position = _snap_vector(
            _position(geometry) + delta, snap_increment_m, snap_enabled
        )
        _set_position(geometry, position)
    return result


def rotate_obstacle(
    obstacle: Dict[str, Any],
    delta_deg: float,
    axis: str = "z",
    snap_increment_deg: float = 5.0,
    snap_enabled: bool = False,
) -> Dict[str, Any]:
    if axis not in {"x", "y", "z"}:
        raise TransformError("Rotate axis는 x/y/z여야 합니다.")
    result = deepcopy(obstacle)
    geometry = result.setdefault("geometry", {})
    anchor = geometry.get("anchor", {})
    mode = anchor if isinstance(anchor, str) else anchor.get("mode", "center")
    if mode == "explicit_transform":
        raise TransformError(
            "explicit_transform mesh 회전은 Properties의 행렬 입력을 사용해야 합니다."
        )
    rotation = _vector(
        geometry.get("rotation_deg", [0.0, 0.0, 0.0]),
        ("roll", "pitch", "yaw"),
        "rotation_deg",
    )
    index = {"x": 0, "y": 1, "z": 2}[axis]
    rotation[index] = snap_value(
        rotation[index] + float(delta_deg), snap_increment_deg, snap_enabled
    )
    geometry["rotation_deg"] = {
        "roll": float(rotation[0]),
        "pitch": float(rotation[1]),
        "yaw": float(rotation[2]),
    }
    return result


def _axis_rotation(axis: str, angle_deg: float) -> np.ndarray:
    angle = np.deg2rad(float(angle_deg))
    cosine, sine = float(np.cos(angle)), float(np.sin(angle))
    if axis == "x":
        return np.asarray(
            [[1.0, 0.0, 0.0], [0.0, cosine, -sine], [0.0, sine, cosine]]
        )
    if axis == "y":
        return np.asarray(
            [[cosine, 0.0, sine], [0.0, 1.0, 0.0], [-sine, 0.0, cosine]]
        )
    return np.asarray(
        [[cosine, -sine, 0.0], [sine, cosine, 0.0], [0.0, 0.0, 1.0]]
    )


def _matrix_to_rotation_xyz(matrix: np.ndarray) -> np.ndarray:
    value = np.asarray(matrix, dtype=float)
    pitch = float(np.arcsin(np.clip(-value[2, 0], -1.0, 1.0)))
    if abs(float(np.cos(pitch))) > 1.0e-8:
        roll = float(np.arctan2(value[2, 1], value[2, 2]))
        yaw = float(np.arctan2(value[1, 0], value[0, 0]))
    else:
        roll = float(np.arctan2(-value[1, 2], value[1, 1]))
        yaw = 0.0
    return np.degrees([roll, pitch, yaw])


def rotate_obstacle_in_space(
    obstacle: Dict[str, Any],
    delta_deg: float,
    axis: str = "z",
    space: str = "world",
    snap_increment_deg: float = 5.0,
    snap_enabled: bool = False,
) -> Dict[str, Any]:
    """Compose an axis rotation in world or local space and store XYZ Euler."""

    if axis not in {"x", "y", "z"}:
        raise TransformError("Rotate axis는 x/y/z여야 합니다.")
    if space not in {"world", "local"}:
        raise TransformError("Rotate space는 world/local이어야 합니다.")
    result = deepcopy(obstacle)
    geometry = result.setdefault("geometry", {})
    anchor = geometry.get("anchor", {})
    mode = anchor if isinstance(anchor, str) else anchor.get("mode", "center")
    if mode == "explicit_transform":
        raise TransformError(
            "explicit_transform mesh 회전은 Properties의 행렬 입력을 사용해야 합니다."
        )
    rotation = _vector(
        geometry.get("rotation_deg", [0.0, 0.0, 0.0]),
        ("roll", "pitch", "yaw"),
        "rotation_deg",
    )
    angle = snap_value(delta_deg, snap_increment_deg, snap_enabled)
    current = rotation_matrix_xyz(rotation)
    delta = _axis_rotation(axis, angle)
    composed = delta @ current if space == "world" else current @ delta
    values = _matrix_to_rotation_xyz(composed)
    geometry["rotation_deg"] = {
        "roll": float(values[0]),
        "pitch": float(values[1]),
        "yaw": float(values[2]),
    }
    return result


def resize_obstacle(
    obstacle: Dict[str, Any],
    factor: float,
    axis: Optional[str] = None,
    snap_increment_m: float = 0.05,
    snap_enabled: bool = False,
    minimum_size_m: float = 0.001,
) -> Dict[str, Any]:
    scale = float(factor)
    if not np.isfinite(scale) or scale <= 0.0:
        raise TransformError("Scale factor는 유한한 양수여야 합니다.")
    if axis not in {None, "x", "y", "z"}:
        raise TransformError("Scale axis는 x/y/z 또는 None이어야 합니다.")
    result = deepcopy(obstacle)
    geometry = result.setdefault("geometry", {})
    size = _vector(geometry.get("size_m"), ("x", "y", "z"), "size_m")
    indices = range(3) if axis is None else ({"x": 0, "y": 1, "z": 2}[axis],)
    for index in indices:
        size[index] *= scale
    size = _snap_vector(size, snap_increment_m, snap_enabled)
    if np.any(size < minimum_size_m):
        raise TransformError(
            "Obstacle size는 {:.6f} m 이상이어야 합니다.".format(minimum_size_m)
        )
    geometry["size_m"] = {"x": float(size[0]), "y": float(size[1]), "z": float(size[2])}
    return result


def set_numeric_geometry(
    obstacle: Dict[str, Any],
    position: Optional[Sequence[float]] = None,
    size: Optional[Sequence[float]] = None,
    rotation: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    result = deepcopy(obstacle)
    geometry = result.setdefault("geometry", {})
    if position is not None:
        values = np.asarray(position, dtype=float)
        mode_value = geometry.get("anchor", {})
        mode = (
            mode_value
            if isinstance(mode_value, str)
            else mode_value.get("mode", "center")
        )
        expected = 2 if mode == "floor_at_xy" else 3
        if values.shape != (expected,) or not np.all(np.isfinite(values)):
            raise TransformError("Position 차원 또는 값이 유효하지 않습니다.")
        _set_position(geometry, values)
    if size is not None:
        values = np.asarray(size, dtype=float)
        if (
            values.shape != (3,)
            or not np.all(np.isfinite(values))
            or np.any(values <= 0.0)
        ):
            raise TransformError("Size에는 유한한 양수 3개가 필요합니다.")
        geometry["size_m"] = {
            "x": float(values[0]),
            "y": float(values[1]),
            "z": float(values[2]),
        }
    if rotation is not None:
        values = np.asarray(rotation, dtype=float)
        if values.shape != (3,) or not np.all(np.isfinite(values)):
            raise TransformError("Rotation에는 유한한 값 3개가 필요합니다.")
        geometry["rotation_deg"] = {
            "roll": float(values[0]),
            "pitch": float(values[1]),
            "yaw": float(values[2]),
        }
    return result
