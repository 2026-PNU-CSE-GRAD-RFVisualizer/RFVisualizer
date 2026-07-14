"""Phase 2-B obstacle configuration schema.

The schema layer deliberately has no Sionna dependency.  It turns the fairly
human-friendly YAML representation into small, immutable value objects before
geometry or scene code is allowed to use it.  Disabled draft obstacles may
contain ``null`` geometry values; the same values are rejected as soon as an
obstacle is enabled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import math
import re


SUPPORTED_GEOMETRY_TYPES = ("box", "thin_panel", "mesh")
SUPPORTED_ANCHOR_MODES = ("center", "bottom_center", "floor_at_xy", "explicit_transform")
SUPPORTED_FLOOR_CONTACT_POLICIES = ("anchor_point", "minimum_bottom_vertex_clearance")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")


class ObstacleSchemaError(ValueError):
    """Raised when an obstacle document is ambiguous or unsafe to build."""


Vector3 = Tuple[float, float, float]
Matrix4 = Tuple[Tuple[float, float, float, float], ...]


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ObstacleSchemaError("{} 값은 숫자여야 합니다.".format(label))
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ObstacleSchemaError("{} 값은 숫자여야 합니다.".format(label)) from exc
    if not math.isfinite(result):
        raise ObstacleSchemaError("{} 값은 유한한 숫자여야 합니다.".format(label))
    return result


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ObstacleSchemaError("{} 값은 비어 있지 않은 문자열이어야 합니다.".format(label))
    return value.strip()


def _optional_text(value: Any, label: str) -> Optional[str]:
    if value is None:
        return None
    return _required_text(value, label)


def _safe_name(value: Any, label: str) -> str:
    text = _required_text(value, label)
    if not _SAFE_NAME.fullmatch(text) or text in {".", ".."}:
        raise ObstacleSchemaError(
            "{}에는 영문자, 숫자, '_', '-', '.'만 사용할 수 있고 경로 문자를 포함할 수 없습니다.".format(
                label
            )
        )
    return text


def _strict_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ObstacleSchemaError("{} 값은 true 또는 false여야 합니다.".format(label))
    return value


def _xyz_vector(value: Any, label: str, allow_xy: bool = False) -> Tuple[float, ...]:
    if not isinstance(value, (Mapping, Sequence, str, bytes)) and hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, Mapping):
        keys = ("x", "y") if allow_xy and value.get("z") is None else ("x", "y", "z")
        missing = [key for key in keys if value.get(key) is None]
        if missing:
            raise ObstacleSchemaError("{}에 {} 좌표가 필요합니다.".format(label, ", ".join(missing)))
        return tuple(_finite_number(value[key], "{}.{}".format(label, key)) for key in keys)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if len(value) not in ((2, 3) if allow_xy else (3,)):
            description = "x/y 또는 x/y/z" if allow_xy else "x/y/z"
            raise ObstacleSchemaError("{}에는 {} 좌표가 필요합니다.".format(label, description))
        return tuple(_finite_number(item, "{}[{}]".format(label, index)) for index, item in enumerate(value))
    raise ObstacleSchemaError("{}에는 x/y/z 좌표 또는 숫자 배열이 필요합니다.".format(label))


def _rotation_vector(value: Any, label: str) -> Vector3:
    if value is None:
        return (0.0, 0.0, 0.0)
    if isinstance(value, Mapping):
        return tuple(
            _finite_number(value.get(key, 0.0), "{}.{}".format(label, key))
            for key in ("roll", "pitch", "yaw")
        )  # type: ignore[return-value]
    values = _xyz_vector(value, label)
    return (values[0], values[1], values[2])


def _matrix4(value: Any, label: str) -> Matrix4:
    if isinstance(value, Mapping):
        for key in ("matrix", "matrix_4x4", "values"):
            if key in value:
                value = value[key]
                break
    if not isinstance(value, (Sequence, str, bytes)) and hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ObstacleSchemaError("{}에는 4x4 행렬이 필요합니다.".format(label))
    if len(value) == 16 and not any(isinstance(item, Sequence) for item in value):
        value = [value[index : index + 4] for index in range(0, 16, 4)]
    if len(value) != 4 or any(
        not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or len(row) != 4
        for row in value
    ):
        raise ObstacleSchemaError("{}에는 4x4 행렬이 필요합니다.".format(label))
    rows = tuple(
        tuple(_finite_number(item, "{}[{}][{}]".format(label, row_index, column_index)) for column_index, item in enumerate(row))
        for row_index, row in enumerate(value)
    )
    if any(abs(rows[3][index] - expected) > 1.0e-9 for index, expected in enumerate((0.0, 0.0, 0.0, 1.0))):
        raise ObstacleSchemaError("{}의 마지막 행은 [0, 0, 0, 1]이어야 합니다.".format(label))
    # Avoid importing NumPy in the schema module just to reject a singular
    # affine transform.
    a, b, c = rows[0][:3]
    d, e, f = rows[1][:3]
    g, h, i = rows[2][:3]
    determinant = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(determinant) <= 1.0e-12:
        raise ObstacleSchemaError("{}의 선형 변환은 역행렬을 가져야 합니다.".format(label))
    return rows  # type: ignore[return-value]


def _size_vector(data: Mapping[str, Any], geometry_type: str, enabled: bool) -> Optional[Vector3]:
    value = data.get("size_m")
    if geometry_type == "thin_panel" and value is None:
        separate = (data.get("thickness_m"), data.get("width_m"), data.get("height_m"))
        if any(item is not None for item in separate):
            if not all(item is not None for item in separate):
                if enabled:
                    raise ObstacleSchemaError("thin_panel에는 thickness_m, width_m, height_m이 모두 필요합니다.")
                return None
            result = tuple(
                _finite_number(item, "geometry.{}_m".format(name))
                for name, item in zip(("thickness", "width", "height"), separate)
            )
        elif enabled:
            raise ObstacleSchemaError("활성 thin_panel에는 size_m 또는 thickness/width/height가 필요합니다.")
        else:
            return None
    elif value is None:
        if geometry_type == "box" and enabled:
            raise ObstacleSchemaError("활성 box에는 size_m이 필요합니다.")
        return None
    elif isinstance(value, Mapping) and geometry_type == "thin_panel" and any(
        key in value for key in ("width", "height", "thickness", "width_m", "height_m", "thickness_m")
    ):
        def component(name: str) -> Any:
            return value.get(name, value.get(name + "_m"))

        if any(component(name) is None for name in ("thickness", "width", "height")):
            raise ObstacleSchemaError("thin_panel size_m에는 thickness, width, height가 모두 필요합니다.")
        # Thin panels use local X=thickness, Y=width, Z=height.  This makes the
        # default panel normal agree with the Phase 2-B blocker direction.
        result = tuple(
            _finite_number(component(name), "geometry.size_m.{}".format(name))
            for name in ("thickness", "width", "height")
        )
    else:
        parsed = _xyz_vector(value, "geometry.size_m")
        result = (parsed[0], parsed[1], parsed[2])
    if any(item <= 0.0 for item in result):
        raise ObstacleSchemaError("geometry.size_m의 모든 길이는 0보다 커야 합니다.")
    return result  # type: ignore[return-value]


@dataclass(frozen=True)
class FloorContactPolicy:
    type: str = "anchor_point"
    clearance_m: float = 0.0

    def __post_init__(self) -> None:
        if self.type not in SUPPORTED_FLOOR_CONTACT_POLICIES:
            raise ObstacleSchemaError(
                "지원하지 않는 floor contact policy '{}': {}".format(
                    self.type, ", ".join(SUPPORTED_FLOOR_CONTACT_POLICIES)
                )
            )
        if not math.isfinite(self.clearance_m) or self.clearance_m < 0.0:
            raise ObstacleSchemaError("floor contact clearance_m은 유한한 0 이상 값이어야 합니다.")


@dataclass(frozen=True)
class AnchorSpec:
    mode: str = "center"
    floor_contact_policy: FloorContactPolicy = field(default_factory=FloorContactPolicy)

    def __post_init__(self) -> None:
        if self.mode not in SUPPORTED_ANCHOR_MODES:
            raise ObstacleSchemaError(
                "지원하지 않는 anchor mode '{}': {}".format(self.mode, ", ".join(SUPPORTED_ANCHOR_MODES))
            )


@dataclass(frozen=True)
class GeometrySpec:
    type: str
    anchor: AnchorSpec
    position_m: Optional[Tuple[float, ...]] = None
    size_m: Optional[Vector3] = None
    rotation_deg: Vector3 = (0.0, 0.0, 0.0)
    floor_clearance_m: float = 0.0
    path: Optional[Path] = None
    transform: Optional[Matrix4] = None

    @property
    def thickness_m(self) -> Optional[float]:
        return self.size_m[0] if self.type == "thin_panel" and self.size_m else None

    @property
    def width_m(self) -> Optional[float]:
        return self.size_m[1] if self.type == "thin_panel" and self.size_m else None

    @property
    def height_m(self) -> Optional[float]:
        return self.size_m[2] if self.type == "thin_panel" and self.size_m else None

    def to_dict(self) -> Dict[str, Any]:
        anchor: Dict[str, Any] = {"mode": self.anchor.mode}
        if self.anchor.floor_contact_policy.type != "anchor_point":
            anchor["floor_contact_policy"] = {
                "type": self.anchor.floor_contact_policy.type,
                "clearance_m": self.anchor.floor_contact_policy.clearance_m,
            }
        result: Dict[str, Any] = {
            "type": self.type,
            "anchor": anchor,
            "position_m": list(self.position_m) if self.position_m is not None else None,
            "size_m": list(self.size_m) if self.size_m is not None else None,
            "rotation_deg": {
                "roll": self.rotation_deg[0],
                "pitch": self.rotation_deg[1],
                "yaw": self.rotation_deg[2],
            },
            "floor_clearance_m": self.floor_clearance_m,
        }
        if self.path is not None:
            result["path"] = str(self.path)
        if self.transform is not None:
            result["transform"] = [list(row) for row in self.transform]
        return result


@dataclass(frozen=True)
class ObstacleSpec:
    id: str
    enabled: bool
    semantic_class: str
    purpose: str
    physical_object: bool
    confidence: str
    geometry: GeometrySpec
    material: Dict[str, Any]
    object_name: str
    group_name: str
    state: Optional[str] = None
    source_path: Optional[Path] = None
    source: Dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "id": self.id,
            "enabled": self.enabled,
            "semantic_class": self.semantic_class,
            "purpose": self.purpose,
            "physical_object": self.physical_object,
            "confidence": self.confidence,
            "geometry": self.geometry.to_dict(),
            "material": dict(self.material),
            "export": {"object_name": self.object_name, "group_name": self.group_name},
        }
        if self.state is not None:
            result["state"] = self.state
        return result


def _parse_floor_contact_policy(value: Any) -> FloorContactPolicy:
    if value is None:
        return FloorContactPolicy()
    if isinstance(value, str):
        return FloorContactPolicy(type=_required_text(value, "geometry.anchor.floor_contact_policy"))
    if not isinstance(value, Mapping):
        raise ObstacleSchemaError("geometry.anchor.floor_contact_policy는 문자열 또는 mapping이어야 합니다.")
    policy_type = _required_text(value.get("type"), "geometry.anchor.floor_contact_policy.type")
    clearance = _finite_number(
        value.get("clearance_m", 0.0), "geometry.anchor.floor_contact_policy.clearance_m"
    )
    return FloorContactPolicy(type=policy_type, clearance_m=clearance)


def _parse_anchor(value: Any) -> AnchorSpec:
    if value is None:
        return AnchorSpec("center")
    if isinstance(value, str):
        return AnchorSpec(_required_text(value, "geometry.anchor"))
    if not isinstance(value, Mapping):
        raise ObstacleSchemaError("geometry.anchor는 문자열 또는 mapping이어야 합니다.")
    return AnchorSpec(
        _required_text(value.get("mode"), "geometry.anchor.mode"),
        _parse_floor_contact_policy(value.get("floor_contact_policy")),
    )


def _parse_geometry(
    value: Any,
    enabled: bool,
    base_dir: Optional[Path],
) -> GeometrySpec:
    if not isinstance(value, Mapping):
        raise ObstacleSchemaError("geometry는 mapping이어야 합니다.")
    geometry_type = _required_text(value.get("type"), "geometry.type")
    if geometry_type not in SUPPORTED_GEOMETRY_TYPES:
        raise ObstacleSchemaError(
            "지원하지 않는 geometry type '{}': {}".format(geometry_type, ", ".join(SUPPORTED_GEOMETRY_TYPES))
        )
    raw_anchor = value.get("anchor", value.get("anchor_mode"))
    # The external-mesh form in the Phase 2-B contract is intentionally terse:
    # ``type/path/transform``.  An explicit matrix unambiguously selects the
    # corresponding anchor when no anchor field was written.
    if raw_anchor is None and value.get("transform") is not None:
        anchor = AnchorSpec("explicit_transform")
    else:
        anchor = _parse_anchor(raw_anchor)
    allow_xy = anchor.mode == "floor_at_xy"
    position_value = value.get("position_m")
    if position_value is None:
        position = None
    else:
        position = _xyz_vector(position_value, "geometry.position_m", allow_xy=allow_xy)
    size = _size_vector(value, geometry_type, enabled)
    rotation = _rotation_vector(value.get("rotation_deg"), "geometry.rotation_deg")
    clearance = _finite_number(value.get("floor_clearance_m", 0.0), "geometry.floor_clearance_m")
    if clearance < 0.0:
        raise ObstacleSchemaError("geometry.floor_clearance_m은 음수일 수 없습니다.")

    raw_path = value.get("path")
    path: Optional[Path] = None
    if raw_path is not None:
        text = _required_text(raw_path, "geometry.path")
        path = Path(text).expanduser()
        if base_dir is not None and not path.is_absolute():
            path = (base_dir / path).resolve()

    transform_value = value.get("transform")
    anchor_value = value.get("anchor")
    if transform_value is None and isinstance(anchor_value, Mapping):
        transform_value = anchor_value.get("transform")
    transform = _matrix4(transform_value, "geometry.transform") if transform_value is not None else None

    if enabled:
        if geometry_type in ("box", "thin_panel") and size is None:
            raise ObstacleSchemaError("활성 primitive에는 size_m이 필요합니다.")
        if geometry_type == "mesh" and path is None:
            raise ObstacleSchemaError("활성 mesh에는 geometry.path가 필요합니다.")
        if anchor.mode == "explicit_transform":
            if transform is None:
                raise ObstacleSchemaError("explicit_transform anchor에는 geometry.transform이 필요합니다.")
            if position is not None:
                raise ObstacleSchemaError("explicit_transform은 position_m과 함께 사용할 수 없습니다.")
            if any(abs(item) > 1.0e-12 for item in rotation):
                raise ObstacleSchemaError("explicit_transform은 rotation_deg와 함께 사용할 수 없습니다.")
        elif position is None:
            raise ObstacleSchemaError("활성 {} anchor에는 position_m이 필요합니다.".format(anchor.mode))
        elif anchor.mode != "floor_at_xy" and len(position) != 3:
            raise ObstacleSchemaError("{} anchor의 position_m에는 x/y/z가 필요합니다.".format(anchor.mode))
        if transform is not None and anchor.mode != "explicit_transform":
            raise ObstacleSchemaError("geometry.transform은 explicit_transform anchor에서만 사용할 수 있습니다.")
    return GeometrySpec(
        type=geometry_type,
        anchor=anchor,
        position_m=position,
        size_m=size,
        rotation_deg=rotation,
        floor_clearance_m=clearance,
        path=path,
        transform=transform,
    )


def parse_obstacle(
    value: Mapping[str, Any],
    base_dir: Optional[Union[str, Path]] = None,
    source_path: Optional[Union[str, Path]] = None,
) -> ObstacleSpec:
    """Parse and validate one obstacle mapping.

    Relative external-mesh paths are resolved against ``base_dir``.  When a
    source YAML path is supplied, its parent directory is used automatically.
    """

    if not isinstance(value, Mapping):
        raise ObstacleSchemaError("obstacle 항목은 mapping이어야 합니다.")
    source = Path(source_path).expanduser().resolve() if source_path is not None else None
    root = Path(base_dir).expanduser().resolve() if base_dir is not None else (source.parent if source else None)
    obstacle_id = _safe_name(value.get("id"), "obstacle.id")
    enabled = _strict_bool(value.get("enabled"), "obstacle.enabled")
    semantic_class = _safe_name(value.get("semantic_class"), "obstacle.semantic_class")
    purpose = _required_text(value.get("purpose"), "obstacle.purpose")
    physical_object = _strict_bool(value.get("physical_object"), "obstacle.physical_object")
    confidence = _required_text(value.get("confidence"), "obstacle.confidence")
    if purpose == "validation_only" and (physical_object or confidence != "synthetic"):
        raise ObstacleSchemaError(
            "validation_only obstacle은 physical_object=false, confidence=synthetic이어야 합니다."
        )
    geometry = _parse_geometry(value.get("geometry"), enabled, root)
    material_value = value.get("material")
    if not isinstance(material_value, Mapping):
        raise ObstacleSchemaError("obstacle.material은 mapping이어야 합니다.")
    material = dict(material_value)
    if enabled and not any(material.get(key) for key in ("category", "preset", "name")):
        raise ObstacleSchemaError("활성 obstacle material에는 category, preset 또는 name이 필요합니다.")

    export_value = value.get("export", {})
    if export_value is None:
        export_value = {}
    if not isinstance(export_value, Mapping):
        raise ObstacleSchemaError("obstacle.export는 mapping이어야 합니다.")
    object_name = (
        _safe_name(export_value.get("object_name"), "export.object_name")
        if export_value.get("object_name") is not None
        else obstacle_id
    )
    group_name = (
        _safe_name(export_value.get("group_name"), "export.group_name")
        if export_value.get("group_name") is not None
        else semantic_class
    )
    state = _optional_text(value.get("state"), "obstacle.state")
    return ObstacleSpec(
        id=obstacle_id,
        enabled=enabled,
        semantic_class=semantic_class,
        purpose=purpose,
        physical_object=physical_object,
        confidence=confidence,
        geometry=geometry,
        material=material,
        object_name=object_name,
        group_name=group_name,
        state=state,
        source_path=source,
        source=dict(value),
    )


def parse_obstacles(
    values: Iterable[Mapping[str, Any]],
    base_dir: Optional[Union[str, Path]] = None,
    source_path: Optional[Union[str, Path]] = None,
) -> List[ObstacleSpec]:
    obstacles = [parse_obstacle(value, base_dir=base_dir, source_path=source_path) for value in values]
    seen_ids: Dict[str, int] = {}
    seen_objects: Dict[str, int] = {}
    for index, obstacle in enumerate(obstacles):
        if obstacle.id in seen_ids:
            raise ObstacleSchemaError(
                "obstacle id '{}'가 {}번과 {}번 항목에서 중복됩니다.".format(
                    obstacle.id, seen_ids[obstacle.id], index
                )
            )
        if obstacle.object_name in seen_objects:
            raise ObstacleSchemaError(
                "export.object_name '{}'가 {}번과 {}번 항목에서 중복됩니다.".format(
                    obstacle.object_name, seen_objects[obstacle.object_name], index
                )
            )
        seen_ids[obstacle.id] = index
        seen_objects[obstacle.object_name] = index
    return obstacles


def obstacles_from_document(
    document: Mapping[str, Any],
    base_dir: Optional[Union[str, Path]] = None,
    source_path: Optional[Union[str, Path]] = None,
) -> List[ObstacleSpec]:
    """Read obstacles from either a scenario document or a bare list wrapper."""

    if not isinstance(document, Mapping):
        raise ObstacleSchemaError("scenario 문서는 mapping이어야 합니다.")
    root: Any = document.get("scenario", document)
    if not isinstance(root, Mapping):
        raise ObstacleSchemaError("scenario 값은 mapping이어야 합니다.")
    values = root.get("obstacles", [])
    if values is None:
        values = []
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise ObstacleSchemaError("scenario.obstacles는 배열이어야 합니다.")
    return parse_obstacles(values, base_dir=base_dir, source_path=source_path)


def load_obstacles(path: Union[str, Path]) -> List[ObstacleSpec]:
    """Load the obstacle list from a YAML scenario file."""

    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ObstacleSchemaError("scenario 파일을 찾을 수 없습니다: {}".format(source))
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - project environments include PyYAML
        raise ObstacleSchemaError("YAML scenario를 읽으려면 PyYAML이 필요합니다.") from exc
    try:
        document = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ObstacleSchemaError("scenario YAML을 읽을 수 없습니다: {}".format(exc)) from exc
    return obstacles_from_document(document, source_path=source)


# Explicit aliases make the intended public API discoverable to callers that
# use schema/loader terminology.
obstacle_from_dict = parse_obstacle
load_obstacle_document = load_obstacles
