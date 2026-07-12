"""Deterministic obstacle primitive and external-mesh construction.

All returned vertices are expressed in the Phase 1.5-C metric coordinate
system.  Box faces have outward winding and positive signed volume, including
when an explicit transform contains a reflection.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import math
import numpy as np

from .obstacle_schema import GeometrySpec, ObstacleSpec, parse_obstacle


class PrimitiveBuildError(ValueError):
    """Raised when an obstacle cannot be converted to a triangle mesh."""


@dataclass
class TriangleMesh:
    vertices: np.ndarray
    faces: np.ndarray
    obstacle_id: str = ""
    geometry_type: str = "mesh"
    transform: Optional[np.ndarray] = None
    source_path: Optional[Path] = None

    def __post_init__(self) -> None:
        self.vertices = np.asarray(self.vertices, dtype=float)
        self.faces = np.asarray(self.faces, dtype=int)
        if self.vertices.ndim != 2 or self.vertices.shape[1:] != (3,) or len(self.vertices) < 3:
            raise PrimitiveBuildError("mesh vertices는 N x 3 배열이어야 합니다.")
        if not np.all(np.isfinite(self.vertices)):
            raise PrimitiveBuildError("mesh vertices에는 유한한 좌표만 허용됩니다.")
        if self.faces.ndim != 2 or self.faces.shape[1:] != (3,) or len(self.faces) < 1:
            raise PrimitiveBuildError("mesh faces는 M x 3 삼각형 index 배열이어야 합니다.")
        if np.any(self.faces < 0) or np.any(self.faces >= len(self.vertices)):
            raise PrimitiveBuildError("mesh face index가 vertex 범위를 벗어납니다.")
        if any(len(set(int(item) for item in face)) != 3 for face in self.faces):
            raise PrimitiveBuildError("같은 vertex를 반복하는 삼각형은 허용되지 않습니다.")
        if self.transform is None:
            self.transform = np.eye(4, dtype=float)
        else:
            self.transform = np.asarray(self.transform, dtype=float)
            if self.transform.shape != (4, 4) or not np.all(np.isfinite(self.transform)):
                raise PrimitiveBuildError("mesh transform은 유한한 4x4 행렬이어야 합니다.")
        self.vertices = self.vertices.copy()
        self.faces = self.faces.copy()
        self.transform = self.transform.copy()

    @property
    def triangles(self) -> np.ndarray:
        """Alias used by scene exporters."""

        return self.faces

    @property
    def bounds_min(self) -> np.ndarray:
        return np.min(self.vertices, axis=0)

    @property
    def bounds_max(self) -> np.ndarray:
        return np.max(self.vertices, axis=0)

    @property
    def bounds(self) -> Dict[str, List[float]]:
        minimum, maximum = self.bounds_min, self.bounds_max
        return {
            "min": minimum.tolist(),
            "max": maximum.tolist(),
            "extent": (maximum - minimum).tolist(),
        }

    @property
    def vertex_count(self) -> int:
        return int(len(self.vertices))

    @property
    def triangle_count(self) -> int:
        return int(len(self.faces))

    def statistics(self) -> Dict[str, Any]:
        return mesh_statistics(self.vertices, self.faces)

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "obstacle_id": self.obstacle_id,
            "geometry_type": self.geometry_type,
            "vertex_count": self.vertex_count,
            "triangle_count": self.triangle_count,
            "bounds": self.bounds,
            "transform": self.transform.tolist(),
            "statistics": self.statistics(),
        }
        if self.source_path is not None:
            result["source_path"] = str(self.source_path)
        return result


def mesh_statistics(vertices: np.ndarray, faces: np.ndarray) -> Dict[str, Any]:
    points = np.asarray(vertices, dtype=float)
    triangles = np.asarray(faces, dtype=int)
    first = points[triangles[:, 0]]
    second = points[triangles[:, 1]]
    third = points[triangles[:, 2]]
    cross = np.cross(second - first, third - first)
    double_areas = np.linalg.norm(cross, axis=1)
    signed_volume = float(np.sum(np.einsum("ij,ij->i", first, np.cross(second, third))) / 6.0)
    minimum, maximum = np.min(points, axis=0), np.max(points, axis=0)
    undirected_edges: Dict[Tuple[int, int], int] = {}
    for face in triangles:
        for start, end in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            key = tuple(sorted((int(start), int(end))))
            undirected_edges[key] = undirected_edges.get(key, 0) + 1
    boundary = [list(edge) for edge, count in undirected_edges.items() if count == 1]
    non_manifold = [list(edge) for edge, count in undirected_edges.items() if count > 2]
    centroid = np.mean(points, axis=0)
    face_centroids = (first + second + third) / 3.0
    orientation_dot = np.einsum("ij,ij->i", cross, face_centroids - centroid)
    return {
        "vertex_count": int(len(points)),
        "triangle_count": int(len(triangles)),
        "bounds": {
            "min": minimum.tolist(),
            "max": maximum.tolist(),
            "extent": (maximum - minimum).tolist(),
        },
        "surface_area": float(0.5 * np.sum(double_areas)),
        "signed_volume": signed_volume,
        "absolute_volume": abs(signed_volume),
        "degenerate_triangle_count": int(np.count_nonzero(double_areas <= 1.0e-12)),
        "boundary_edge_count": len(boundary),
        "non_manifold_edge_count": len(non_manifold),
        "closed_manifold": not boundary and not non_manifold,
        "outward_or_tangent_face_count": int(np.count_nonzero(orientation_dot >= -1.0e-12)),
        "strictly_outward_face_count": int(np.count_nonzero(orientation_dot > 1.0e-12)),
    }


def rotation_matrix_xyz(rotation_deg: Sequence[float]) -> np.ndarray:
    """Return ``Rz(yaw) @ Ry(pitch) @ Rx(roll)`` for degree inputs."""

    values = np.asarray(rotation_deg, dtype=float)
    if values.shape != (3,) or not np.all(np.isfinite(values)):
        raise PrimitiveBuildError("rotation_deg에는 유한한 roll/pitch/yaw 3개가 필요합니다.")
    roll, pitch, yaw = np.deg2rad(values)
    cx, sx = math.cos(roll), math.sin(roll)
    cy, sy = math.cos(pitch), math.sin(pitch)
    cz, sz = math.cos(yaw), math.sin(yaw)
    rx = np.asarray([[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]])
    ry = np.asarray([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]])
    rz = np.asarray([[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]])
    return rz @ ry @ rx


def _affine(linear: np.ndarray, translation: Sequence[float]) -> np.ndarray:
    result = np.eye(4, dtype=float)
    result[:3, :3] = np.asarray(linear, dtype=float)
    result[:3, 3] = np.asarray(translation, dtype=float)
    return result


def transform_mesh(mesh: TriangleMesh, transform: np.ndarray, obstacle_id: Optional[str] = None) -> TriangleMesh:
    matrix = np.asarray(transform, dtype=float)
    if matrix.shape != (4, 4) or not np.all(np.isfinite(matrix)):
        raise PrimitiveBuildError("transform은 유한한 4x4 행렬이어야 합니다.")
    if not np.allclose(matrix[3], [0.0, 0.0, 0.0, 1.0], atol=1.0e-9):
        raise PrimitiveBuildError("transform 마지막 행은 [0, 0, 0, 1]이어야 합니다.")
    determinant = float(np.linalg.det(matrix[:3, :3]))
    if abs(determinant) <= 1.0e-12:
        raise PrimitiveBuildError("transform의 선형 부분은 역행렬을 가져야 합니다.")
    homogeneous = np.column_stack([mesh.vertices, np.ones(len(mesh.vertices))])
    vertices = (matrix @ homogeneous.T).T[:, :3]
    faces = mesh.faces.copy()
    if determinant < 0.0:
        faces = faces[:, [0, 2, 1]]
    return TriangleMesh(
        vertices=vertices,
        faces=faces,
        obstacle_id=obstacle_id if obstacle_id is not None else mesh.obstacle_id,
        geometry_type=mesh.geometry_type,
        transform=matrix @ mesh.transform,
        source_path=mesh.source_path,
    )


def create_box_mesh(size_m: Sequence[float], obstacle_id: str = "box") -> TriangleMesh:
    """Create a centered, outward-wound box before anchor placement."""

    size = np.asarray(size_m, dtype=float)
    if size.shape != (3,) or not np.all(np.isfinite(size)) or np.any(size <= 0.0):
        raise PrimitiveBuildError("box size_m에는 0보다 큰 유한한 x/y/z 길이가 필요합니다.")
    x, y, z = size / 2.0
    vertices = np.asarray(
        [
            [-x, -y, -z],
            [x, -y, -z],
            [x, y, -z],
            [-x, y, -z],
            [-x, -y, z],
            [x, -y, z],
            [x, y, z],
            [-x, y, z],
        ],
        dtype=float,
    )
    faces = np.asarray(
        [
            [0, 2, 1], [0, 3, 2],       # bottom (-Z)
            [4, 5, 6], [4, 6, 7],       # top (+Z)
            [0, 1, 5], [0, 5, 4],       # -Y
            [1, 2, 6], [1, 6, 5],       # +X
            [2, 3, 7], [2, 7, 6],       # +Y
            [3, 0, 4], [3, 4, 7],       # -X
        ],
        dtype=int,
    )
    return TriangleMesh(vertices, faces, obstacle_id=obstacle_id, geometry_type="box")


def create_thin_panel_mesh(
    width_m: float,
    height_m: float,
    thickness_m: float,
    obstacle_id: str = "thin_panel",
) -> TriangleMesh:
    """Create a panel with local X=thickness, Y=width and Z=height."""

    mesh = create_box_mesh((thickness_m, width_m, height_m), obstacle_id=obstacle_id)
    mesh.geometry_type = "thin_panel"
    return mesh


def _floor_z(room: Any, x: float, y: float) -> float:
    if room is None:
        raise PrimitiveBuildError("floor_at_xy anchor에는 Room Envelope 정보가 필요합니다.")
    candidate = room
    if isinstance(candidate, Mapping):
        if "metric_metadata" in candidate:
            candidate = candidate["metric_metadata"]
        if "normalized_plane_equations" in candidate:
            try:
                from tools.sionna_smoke_test.placement import RoomContainment

                candidate = RoomContainment.from_metadata(dict(candidate))
            except (ImportError, ValueError, TypeError) as exc:
                raise PrimitiveBuildError("Room Envelope metadata를 읽을 수 없습니다: {}".format(exc)) from exc
    elif hasattr(candidate, "metric_metadata"):
        return _floor_z(candidate.metric_metadata, x, y)
    if hasattr(candidate, "floor_ceiling_z"):
        try:
            return float(candidate.floor_ceiling_z(float(x), float(y))[0])
        except (ValueError, TypeError, IndexError) as exc:
            raise PrimitiveBuildError("바닥 Z를 계산할 수 없습니다: {}".format(exc)) from exc
    if hasattr(candidate, "floor"):
        plane = np.asarray(candidate.floor, dtype=float)
        if plane.shape == (4,) and abs(float(plane[2])) > 1.0e-12:
            return float(-(plane[0] * x + plane[1] * y + plane[3]) / plane[2])
    raise PrimitiveBuildError("Room Envelope에서 floor plane을 찾을 수 없습니다.")


def resolve_anchor_transform(geometry: GeometrySpec, local_vertices: np.ndarray, room: Any = None) -> np.ndarray:
    """Resolve one geometry anchor to a metric 4x4 affine transform."""

    if geometry.anchor.mode == "explicit_transform":
        if geometry.transform is None:
            raise PrimitiveBuildError("explicit_transform 행렬이 없습니다.")
        return np.asarray(geometry.transform, dtype=float)
    if geometry.position_m is None:
        raise PrimitiveBuildError("{} anchor에 position_m이 없습니다.".format(geometry.anchor.mode))
    position = np.asarray(geometry.position_m, dtype=float)
    if len(position) < 2:
        raise PrimitiveBuildError("anchor position에는 최소 x/y가 필요합니다.")
    if geometry.anchor.mode == "floor_at_xy":
        target = np.asarray(
            [position[0], position[1], _floor_z(room, position[0], position[1]) + geometry.floor_clearance_m],
            dtype=float,
        )
    else:
        if position.shape != (3,):
            raise PrimitiveBuildError("{} anchor position에는 x/y/z가 필요합니다.".format(geometry.anchor.mode))
        target = position
    minimum, maximum = np.min(local_vertices, axis=0), np.max(local_vertices, axis=0)
    reference = (minimum + maximum) / 2.0
    if geometry.anchor.mode in ("bottom_center", "floor_at_xy"):
        reference[2] = minimum[2]
    rotation = rotation_matrix_xyz(geometry.rotation_deg)
    translate_to_reference = np.eye(4, dtype=float)
    translate_to_reference[:3, 3] = -reference
    return _affine(rotation, target) @ translate_to_reference


def _parse_obj(path: Path) -> Tuple[np.ndarray, np.ndarray]:
    vertices: List[List[float]] = []
    faces: List[List[int]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise PrimitiveBuildError("OBJ mesh를 읽을 수 없습니다: {}".format(exc)) from exc
    for line_number, line in enumerate(lines, 1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        parts = text.split()
        if parts[0] == "v":
            if len(parts) < 4:
                raise PrimitiveBuildError("OBJ {}행 vertex 좌표가 부족합니다.".format(line_number))
            try:
                vertices.append([float(parts[1]), float(parts[2]), float(parts[3])])
            except ValueError as exc:
                raise PrimitiveBuildError("OBJ {}행 vertex를 읽을 수 없습니다.".format(line_number)) from exc
        elif parts[0] == "f":
            if len(parts) < 4:
                raise PrimitiveBuildError("OBJ {}행 face에는 vertex가 3개 이상 필요합니다.".format(line_number))
            polygon = []
            for token in parts[1:]:
                try:
                    raw = int(token.split("/", 1)[0])
                except ValueError as exc:
                    raise PrimitiveBuildError("OBJ {}행 face index를 읽을 수 없습니다.".format(line_number)) from exc
                if raw == 0:
                    raise PrimitiveBuildError("OBJ face index 0은 허용되지 않습니다.")
                index = raw - 1 if raw > 0 else len(vertices) + raw
                if index < 0 or index >= len(vertices):
                    raise PrimitiveBuildError("OBJ face index가 vertex 범위를 벗어납니다.")
                polygon.append(index)
            for index in range(1, len(polygon) - 1):
                faces.append([polygon[0], polygon[index], polygon[index + 1]])
    return np.asarray(vertices, dtype=float), np.asarray(faces, dtype=int)


def _parse_ascii_ply(path: Path) -> Tuple[np.ndarray, np.ndarray]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise PrimitiveBuildError("PLY mesh를 읽을 수 없습니다: {}".format(exc)) from exc
    if not lines or lines[0].strip() != "ply":
        raise PrimitiveBuildError("PLY header가 없습니다.")
    vertex_count = face_count = None
    vertex_properties: List[str] = []
    current_element = None
    header_end = None
    is_ascii = False
    for index, line in enumerate(lines[1:], 1):
        parts = line.strip().split()
        if not parts:
            continue
        if parts[:3] == ["format", "ascii", "1.0"]:
            is_ascii = True
        elif parts[0] == "element" and len(parts) == 3:
            current_element = parts[1]
            if current_element == "vertex":
                vertex_count = int(parts[2])
            elif current_element == "face":
                face_count = int(parts[2])
        elif parts[0] == "property" and current_element == "vertex" and len(parts) >= 3:
            vertex_properties.append(parts[-1])
        elif parts[0] == "end_header":
            header_end = index + 1
            break
    if not is_ascii:
        raise PrimitiveBuildError("현재 external mesh interface는 ASCII PLY만 지원합니다.")
    if header_end is None or vertex_count is None or face_count is None:
        raise PrimitiveBuildError("PLY vertex/face header가 부족합니다.")
    try:
        xyz = [vertex_properties.index(axis) for axis in ("x", "y", "z")]
    except ValueError as exc:
        raise PrimitiveBuildError("PLY vertex에 x/y/z property가 필요합니다.") from exc
    vertices = []
    for row in lines[header_end : header_end + vertex_count]:
        parts = row.split()
        vertices.append([float(parts[index]) for index in xyz])
    faces = []
    start = header_end + vertex_count
    for row in lines[start : start + face_count]:
        parts = row.split()
        if not parts:
            continue
        count = int(parts[0])
        polygon = [int(item) for item in parts[1 : count + 1]]
        if len(polygon) != count or count < 3:
            raise PrimitiveBuildError("PLY face vertex list가 유효하지 않습니다.")
        for index in range(1, count - 1):
            faces.append([polygon[0], polygon[index], polygon[index + 1]])
    return np.asarray(vertices, dtype=float), np.asarray(faces, dtype=int)


def load_external_mesh(path: Union[str, Path]) -> TriangleMesh:
    """Load the deliberately small Phase 2-B external mesh interface.

    OBJ and ASCII PLY are supported without adding a heavy mesh dependency.
    """

    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise PrimitiveBuildError("external mesh를 찾을 수 없습니다: {}".format(source))
    suffix = source.suffix.lower()
    if suffix == ".obj":
        vertices, faces = _parse_obj(source)
    elif suffix == ".ply":
        vertices, faces = _parse_ascii_ply(source)
    else:
        raise PrimitiveBuildError("external mesh는 OBJ 또는 ASCII PLY만 지원합니다: {}".format(source))
    return TriangleMesh(vertices, faces, geometry_type="mesh", source_path=source)


MeshLoader = Callable[[Path], Union[TriangleMesh, Tuple[np.ndarray, np.ndarray], Mapping[str, Any]]]


def _loaded_mesh(value: Any, path: Path) -> TriangleMesh:
    if isinstance(value, TriangleMesh):
        mesh = value
    elif isinstance(value, Mapping):
        mesh = TriangleMesh(value.get("vertices"), value.get("faces", value.get("triangles")))
    elif isinstance(value, tuple) and len(value) == 2:
        mesh = TriangleMesh(value[0], value[1])
    else:
        raise PrimitiveBuildError("mesh loader는 TriangleMesh, (vertices, faces) 또는 mapping을 반환해야 합니다.")
    mesh.geometry_type = "mesh"
    if mesh.source_path is None:
        mesh.source_path = path
    return mesh


def build_obstacle_mesh(
    obstacle: Union[ObstacleSpec, Mapping[str, Any]],
    room: Any = None,
    mesh_loader: Optional[MeshLoader] = None,
    base_dir: Optional[Union[str, Path]] = None,
) -> TriangleMesh:
    """Build one enabled obstacle in metric world coordinates."""

    spec = obstacle if isinstance(obstacle, ObstacleSpec) else parse_obstacle(obstacle, base_dir=base_dir)
    if not spec.enabled:
        raise PrimitiveBuildError("비활성 obstacle '{}'은 mesh로 만들 수 없습니다.".format(spec.id))
    geometry = spec.geometry
    if geometry.type == "box":
        if geometry.size_m is None:
            raise PrimitiveBuildError("box size_m이 없습니다.")
        local = create_box_mesh(geometry.size_m, obstacle_id=spec.id)
    elif geometry.type == "thin_panel":
        if geometry.size_m is None:
            raise PrimitiveBuildError("thin_panel size_m이 없습니다.")
        local = create_thin_panel_mesh(
            width_m=geometry.size_m[1],
            height_m=geometry.size_m[2],
            thickness_m=geometry.size_m[0],
            obstacle_id=spec.id,
        )
    elif geometry.type == "mesh":
        if geometry.path is None:
            raise PrimitiveBuildError("external mesh path가 없습니다.")
        loader = mesh_loader or load_external_mesh
        try:
            local = _loaded_mesh(loader(geometry.path), geometry.path)
        except PrimitiveBuildError:
            raise
        except Exception as exc:
            raise PrimitiveBuildError("external mesh loader가 실패했습니다: {}".format(exc)) from exc
        local.obstacle_id = spec.id
    else:  # schema validation should make this unreachable
        raise PrimitiveBuildError("지원하지 않는 geometry type입니다: {}".format(geometry.type))
    transform = resolve_anchor_transform(geometry, local.vertices, room=room)
    result = transform_mesh(local, transform, obstacle_id=spec.id)
    result.geometry_type = geometry.type
    return result


def build_box(obstacle: Union[ObstacleSpec, Mapping[str, Any]], room: Any = None) -> TriangleMesh:
    """Build a schema-backed box, rejecting accidental non-box input."""

    spec = obstacle if isinstance(obstacle, ObstacleSpec) else parse_obstacle(obstacle)
    if spec.geometry.type != "box":
        raise PrimitiveBuildError("build_box에는 box obstacle이 필요합니다.")
    return build_obstacle_mesh(spec, room=room)


def build_thin_panel(obstacle: Union[ObstacleSpec, Mapping[str, Any]], room: Any = None) -> TriangleMesh:
    """Build a schema-backed thin panel."""

    spec = obstacle if isinstance(obstacle, ObstacleSpec) else parse_obstacle(obstacle)
    if spec.geometry.type != "thin_panel":
        raise PrimitiveBuildError("build_thin_panel에는 thin_panel obstacle이 필요합니다.")
    return build_obstacle_mesh(spec, room=room)
