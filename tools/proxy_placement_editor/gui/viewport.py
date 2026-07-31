"""Open3D SceneWidget rendering and camera/ray utilities."""

from __future__ import annotations

from typing import Any, Dict, Tuple

import numpy as np

from ..fps_camera_controller import camera_pose_from_view, constrained_look_pose
from ..gizmo import (
    AXIS_COLORS,
    AXIS_NAMES,
    GIZMO_GUARD_TOLERANCE_PX,
    GIZMO_PICK_TOLERANCE_PX,
    GizmoFrame,
    make_gizmo_frame,
    make_front_gizmo_frame,
    pick_gizmo_axis,
    pick_projected_gizmo_axis,
    ring_points,
)
from .metrics import validate_ui_scale


GIZMO_RENDER_PRIORITY = 7


BACKGROUND_MESH_STYLES = {
    "proxy_mesh": {
        "color": (0.82, 0.88, 0.98),
        "alpha": 1.0,
        "unlit": True,
    },
    "pgsr_output_mesh": {
        # White preserves the PGSR vertex colors instead of tinting them.
        "color": (1.0, 1.0, 1.0),
        "alpha": 1.0,
        "unlit": True,
    },
}


def origin_camera_pose(bounds_min, eye_offset_m, target_offset_m) -> Dict[str, list]:
    origin = np.asarray(bounds_min, dtype=float)
    eye_offset = np.asarray(eye_offset_m, dtype=float)
    target_offset = np.asarray(target_offset_m, dtype=float)
    if origin.shape != (3,) or eye_offset.shape != (3,) or target_offset.shape != (3,):
        raise ValueError("초기 카메라 좌표는 3차원 벡터여야 합니다.")
    if not all(
        np.all(np.isfinite(value)) for value in (origin, eye_offset, target_offset)
    ):
        raise ValueError("초기 카메라 좌표는 finite 숫자여야 합니다.")
    eye = origin + eye_offset
    target = origin + target_offset
    direction = target - eye
    length = float(np.linalg.norm(direction))
    if length <= 1.0e-9:
        raise ValueError("초기 카메라 eye와 target은 서로 달라야 합니다.")
    return {
        "eye": eye.tolist(),
        "target": target.tolist(),
        "forward": (direction / length).tolist(),
        "up": [0.0, 0.0, 1.0],
    }


def background_mesh_material_spec(layer_name: str) -> Dict[str, Any]:
    try:
        return dict(BACKGROUND_MESH_STYLES[layer_name])
    except KeyError as exc:
        raise ValueError("알 수 없는 배경 Mesh 계층입니다: {}".format(layer_name)) from exc


def background_layer_visibility(state) -> Dict[str, bool]:
    """Map independent UI checks to renderer geometry names."""

    return {
        "point_cloud": bool(state.point_cloud_visible),
        "room": bool(state.proxy_mesh_visible),
        "pgsr_output_mesh": bool(state.pgsr_output_mesh_visible),
    }


class PlacementViewport:
    def __init__(self, renderer, core, initial_camera=None, ui_scale=1.0):
        import open3d as o3d
        from open3d.visualization import gui, rendering

        self.o3d, self.gui, self.rendering = o3d, gui, rendering
        self.core = core
        self.ui_scale = validate_ui_scale(ui_scale)
        self.widget = gui.SceneWidget()
        self.widget.scene = rendering.Open3DScene(renderer)
        self.widget.scene.set_background([0.04, 0.045, 0.055, 1.0])
        # The persistent world-origin axis is not a transform handle and easily
        # gets mistaken for the selected object's gizmo.
        self.widget.scene.show_axes(False)
        self._obstacle_meshes: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}
        self._obstacle_geometry_names = set()
        self._gizmo_geometry_names = set()
        self._gizmo_frame = None
        self._gizmo_object_ids = []
        self._gizmo_camera_signature = None
        self._point_cloud_material = None
        self._add_room()
        self._add_grid()
        self._add_background_layers()
        self.refresh(core.validate())
        self.frame_room()
        if (initial_camera or {}).get("mode") == "origin":
            self.frame_origin(initial_camera)

    def _material(
        self,
        color,
        alpha=1.0,
        line=False,
        point=False,
        point_size=None,
        unlit=False,
        line_width=1.5,
    ):
        material = self.rendering.MaterialRecord()
        if line:
            material.shader = "unlitLine"
            material.line_width = float(line_width)
        elif point:
            material.shader = "defaultUnlit"
            material.point_size = float(
                self.core.state.reference_point_size
                if point_size is None
                else point_size
            )
        elif unlit:
            material.shader = "defaultUnlit"
        elif alpha < 0.999:
            material.shader = "defaultLitTransparency"
            material.has_alpha = True
        else:
            material.shader = "defaultLit"
        material.base_color = [
            float(color[0]),
            float(color[1]),
            float(color[2]),
            float(alpha),
        ]
        return material

    def _triangle_mesh(self, vertices, faces, colors=None):
        mesh = self.o3d.geometry.TriangleMesh(
            self.o3d.utility.Vector3dVector(np.asarray(vertices, dtype=float)),
            self.o3d.utility.Vector3iVector(np.asarray(faces, dtype=int)),
        )
        if colors is not None and len(colors) == len(vertices):
            mesh.vertex_colors = self.o3d.utility.Vector3dVector(
                np.asarray(colors, dtype=float)
            )
        mesh.compute_vertex_normals()
        return mesh

    def _add_room(self):
        mesh = self._triangle_mesh(
            self.core.scene.room_vertices, self.core.scene.room_faces
        )
        self.widget.scene.add_geometry(
            "room",
            mesh,
            self._material(**background_mesh_material_spec("proxy_mesh")),
        )

    def _add_grid(self):
        room = self.core.scene.containment
        minimum, maximum = room.bounds_min, room.bounds_max
        spacing = 1.0
        points, lines = [], []
        index = 0
        for x in np.arange(
            np.floor(minimum[0]), np.ceil(maximum[0]) + spacing, spacing
        ):
            for xy in [((x, minimum[1]), (x, maximum[1]))]:
                for px, py in xy:
                    points.append([px, py, room.floor_ceiling_z(px, py)[0]])
                lines.append([index, index + 1])
                index += 2
        for y in np.arange(
            np.floor(minimum[1]), np.ceil(maximum[1]) + spacing, spacing
        ):
            for xy in [((minimum[0], y), (maximum[0], y))]:
                for px, py in xy:
                    points.append([px, py, room.floor_ceiling_z(px, py)[0]])
                lines.append([index, index + 1])
                index += 2
        grid = self.o3d.geometry.LineSet(
            self.o3d.utility.Vector3dVector(points),
            self.o3d.utility.Vector2iVector(lines),
        )
        self.widget.scene.add_geometry(
            "floor_grid", grid, self._material((0.25, 0.28, 0.32), line=True)
        )

    def _add_background_layers(self):
        point_cloud = self.core.point_cloud
        if point_cloud is not None:
            if point_cloud.kind == "mesh":
                geometry = self._triangle_mesh(
                    point_cloud.vertices_metric,
                    point_cloud.faces,
                    point_cloud.colors,
                )
                material = self._material(
                    **background_mesh_material_spec("pgsr_output_mesh")
                )
            else:
                geometry = self.o3d.geometry.PointCloud(
                    self.o3d.utility.Vector3dVector(point_cloud.vertices_metric)
                )
                if point_cloud.colors is not None:
                    geometry.colors = self.o3d.utility.Vector3dVector(
                        point_cloud.colors
                    )
                material = self._material(
                    (0.72, 0.75, 0.78), 0.25, point=True
                )
            self._point_cloud_material = material
            self.widget.scene.add_geometry("point_cloud", geometry, material)

        pgsr_mesh = self.core.pgsr_output_mesh
        if pgsr_mesh is not None:
            geometry = self._triangle_mesh(
                pgsr_mesh.vertices_metric,
                pgsr_mesh.faces,
                pgsr_mesh.colors,
            )
            material = self._material(
                **background_mesh_material_spec("pgsr_output_mesh")
            )
            self.widget.scene.add_geometry(
                "pgsr_output_mesh", geometry, material
            )

    def _remove_obstacles(self):
        for name in self._obstacle_geometry_names:
            if self.widget.scene.has_geometry(name):
                self.widget.scene.remove_geometry(name)
        self._obstacle_geometry_names.clear()

    def _remove_gizmo(self):
        self._remove_gizmo_geometry()
        self._gizmo_frame = None
        self._gizmo_object_ids = []
        self._gizmo_camera_signature = None

    def _remove_gizmo_geometry(self):
        for name in self._gizmo_geometry_names:
            if self.widget.scene.has_geometry(name):
                self.widget.scene.remove_geometry(name)
        self._gizmo_geometry_names.clear()

    @staticmethod
    def _align_z_to_axis(axis):
        z_axis = np.asarray([0.0, 0.0, 1.0])
        target = np.asarray(axis, dtype=float)
        target /= np.linalg.norm(target)
        cosine = float(np.clip(np.dot(z_axis, target), -1.0, 1.0))
        if cosine > 1.0 - 1.0e-10:
            return np.eye(3)
        if cosine < -1.0 + 1.0e-10:
            return np.asarray([[1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]])
        vector = np.cross(z_axis, target)
        skew = np.asarray(
            [
                [0.0, -vector[2], vector[1]],
                [vector[2], 0.0, -vector[0]],
                [-vector[1], vector[0], 0.0],
            ]
        )
        return np.eye(3) + skew + skew @ skew * (1.0 / (1.0 + cosine))

    def _colored_line_set(self, points, lines, colors):
        geometry = self.o3d.geometry.LineSet(
            self.o3d.utility.Vector3dVector(np.asarray(points, dtype=float)),
            self.o3d.utility.Vector2iVector(np.asarray(lines, dtype=int)),
        )
        geometry.colors = self.o3d.utility.Vector3dVector(
            np.asarray(colors, dtype=float)
        )
        return geometry

    def _add_gizmo_geometry(self, name, geometry, material) -> None:
        """Add one high-priority gizmo part to the Open3D scene."""

        self.widget.scene.add_geometry(name, geometry, material)
        self.widget.scene.scene.set_geometry_priority(
            name, GIZMO_RENDER_PRIORITY
        )
        self._gizmo_geometry_names.add(name)

    def _add_gizmo(self, record):
        mode = self.core.state.viewport_mode
        if mode not in {"translate", "rotate", "scale"}:
            return
        if record.get("object_kind") == "rx" and mode != "translate":
            return
        room_diagonal = float(
            np.linalg.norm(
                self.core.scene.containment.bounds_max
                - self.core.scene.containment.bounds_min
            )
        )
        frame = make_gizmo_frame(
            record["metric_vertices"],
            record["metric_transform"],
            mode,
            record.get("gizmo_space", self.core.state.transform_space),
            room_diagonal,
        )
        if record.get("gizmo_center") is not None:
            frame = GizmoFrame(
                center=np.asarray(record["gizmo_center"], dtype=float),
                axes=frame.axes,
                length=frame.length,
                mode=frame.mode,
                space=frame.space,
            )
        self._gizmo_frame = frame
        self.update_gizmo_front_geometry(force=True, redraw=False)

    def _add_gizmo_geometry_for_frame(self, frame):
        mode = frame.mode
        if mode == "rotate":
            points, lines, colors = [], [], []
            for axis_name in AXIS_NAMES:
                ring = ring_points(frame, axis_name)
                start = len(points)
                points.extend(ring.tolist())
                lines.extend(
                    [start + index, start + (index + 1) % len(ring)]
                    for index in range(len(ring))
                )
                colors.extend([AXIS_COLORS[axis_name]] * len(ring))
            name = "gizmo::rotation_rings"
            self._add_gizmo_geometry(
                name,
                self._colored_line_set(points, lines, colors),
                self._material(
                    (1.0, 1.0, 1.0),
                    line=True,
                    line_width=3.0 * self.ui_scale,
                ),
            )

        else:
            points = [frame.center.tolist()]
            lines, colors = [], []
            for index, axis_name in enumerate(AXIS_NAMES, 1):
                axis = frame.axis(axis_name)
                endpoint = frame.center + axis * frame.length
                points.append(endpoint.tolist())
                lines.append([0, index])
                colors.append(AXIS_COLORS[axis_name])
                if mode == "translate":
                    handle_height = frame.length * 0.24 * self.ui_scale
                    handle = self.o3d.geometry.TriangleMesh.create_cone(
                        radius=frame.length * 0.075 * self.ui_scale,
                        height=handle_height,
                        resolution=16,
                    )
                    handle.rotate(self._align_z_to_axis(axis), center=(0, 0, 0))
                    handle.translate(
                        frame.center + axis * (frame.length - handle_height)
                    )
                else:
                    size = frame.length * 0.13 * self.ui_scale
                    handle = self.o3d.geometry.TriangleMesh.create_box(size, size, size)
                    handle.translate(endpoint - size / 2.0)
                handle.compute_vertex_normals()
                name = "gizmo::{}::{}".format(mode, axis_name)
                self._add_gizmo_geometry(
                    name,
                    handle,
                    self._material(AXIS_COLORS[axis_name], unlit=True),
                )
            name = "gizmo::axis_lines"
            self._add_gizmo_geometry(
                name,
                self._colored_line_set(points, lines, colors),
                self._material(
                    (1.0, 1.0, 1.0),
                    line=True,
                    line_width=3.0 * self.ui_scale,
                ),
            )

    def update_gizmo_front_geometry(
        self, force: bool = False, redraw: bool = True
    ) -> bool:
        """Rebuild actual 3D handles just beyond the camera near plane."""

        if self._gizmo_frame is None:
            return False
        camera = self.widget.scene.camera
        view = np.asarray(camera.get_view_matrix(), dtype=float)
        near = float(camera.get_near())
        signature = (view.tobytes(), near)
        if not force and signature == self._gizmo_camera_signature:
            return False
        try:
            eye, forward, _, _ = camera_pose_from_view(view)
            display_frame = make_front_gizmo_frame(
                self._gizmo_frame, eye, forward, near
            )
        except ValueError:
            return False
        self._remove_gizmo_geometry()
        self._add_gizmo_geometry_for_frame(display_frame)
        self._gizmo_camera_signature = signature
        if redraw:
            self.widget.force_redraw()
        return True


    def _update_background_visibility(self):
        for geometry_name, visible in background_layer_visibility(
            self.core.state
        ).items():
            if self.widget.scene.has_geometry(geometry_name):
                self.widget.scene.show_geometry(geometry_name, visible)
        if self.widget.scene.has_geometry("floor_grid"):
            self.widget.scene.show_geometry(
                "floor_grid", self.core.state.grid_visible
            )

    def _object_is_shown(self, object_id: str) -> bool:
        if not self.core.state.object_visibility.get(object_id, True):
            return False
        if self.core.state.object_kind(object_id) == "rx":
            return True
        return bool(
            self.core.state.get_object(object_id).get("enabled")
            or self.core.state.show_disabled
        )

    def refresh(self, report: Dict[str, Any]) -> None:
        self._remove_obstacles()
        self._remove_gizmo()
        self._obstacle_meshes.clear()
        self._update_background_visibility()
        colors = {
            "concrete": (0.55, 0.55, 0.58),
            "wood": (0.55, 0.31, 0.12),
            "metal": (0.25, 0.45, 0.68),
            "glass": (0.25, 0.75, 0.85),
            "calibration_rx": (0.18, 0.55, 0.95),
            "test_rx": (0.15, 0.85, 0.35),
        }
        selected_ids = list(
            getattr(self.core.state, "selected_object_ids", [])
        )
        if (
            not selected_ids
            and self.core.state.selected_object_id is not None
        ):
            selected_ids = [self.core.state.selected_object_id]
        selected_id_set = set(selected_ids)
        selected_records = []
        for record in report["objects"]:
            if not record.get("renderable"):
                continue
            if record["id"] in selected_id_set:
                selected_records.append(record)
            if not self._object_is_shown(record["id"]):
                continue
            vertices = np.asarray(record["metric_vertices"], dtype=float)
            faces = np.asarray(record["faces"], dtype=int)
            self._obstacle_meshes[record["id"]] = (vertices, faces)
            if record["id"] == self.core.state.selected_object_id:
                color, alpha = (1.0, 0.75, 0.08), 0.95
            elif record["id"] in selected_id_set:
                color, alpha = (1.0, 0.48, 0.08), 0.9
            elif record["status"] in {"INVALID", "DISABLED_INVALID"}:
                color, alpha = (0.9, 0.08, 0.08), 0.9
            else:
                color = colors.get(record["material"]["category"], (0.7, 0.7, 0.7))
                alpha = 0.85 if record["enabled"] else 0.22
            geometry_name = "obstacle::{}".format(record["id"])
            self.widget.scene.add_geometry(
                geometry_name,
                self._triangle_mesh(vertices, faces),
                self._material(color, alpha),
            )
            self._obstacle_geometry_names.add(geometry_name)
        if len(selected_records) == 1:
            self._gizmo_object_ids = [selected_records[0]["id"]]
            self._add_gizmo(selected_records[0])
        elif len(selected_records) > 1:
            combined_vertices = np.concatenate(
                [
                    np.asarray(value["metric_vertices"], dtype=float)
                    for value in selected_records
                ],
                axis=0,
            )
            self._gizmo_object_ids = [
                value["id"] for value in selected_records
            ]
            self._add_gizmo(
                {
                    "metric_vertices": combined_vertices,
                    "metric_transform": np.eye(4, dtype=float),
                    "object_kind": "selection_group",
                    "gizmo_space": "world",
                }
            )
        self.widget.force_redraw()

    def update_object_preview(self, object_id, mesh) -> None:
        """Replace only the dragged object and gizmo; keep all background layers."""

        geometry_name = "obstacle::{}".format(object_id)
        if self.widget.scene.has_geometry(geometry_name):
            self.widget.scene.remove_geometry(geometry_name)
        vertices = np.asarray(mesh.vertices, dtype=float)
        faces = np.asarray(mesh.faces, dtype=int)
        if self._object_is_shown(object_id):
            self.widget.scene.add_geometry(
                geometry_name,
                self._triangle_mesh(vertices, faces),
                self._material((1.0, 0.75, 0.08), 0.95),
            )
            self._obstacle_geometry_names.add(geometry_name)
            self._obstacle_meshes[object_id] = (vertices, faces)
        else:
            self._obstacle_meshes.pop(object_id, None)
        self._remove_gizmo()
        self._gizmo_object_ids = [object_id]
        self._add_gizmo(
            {
                "metric_vertices": vertices,
                "metric_transform": np.asarray(mesh.transform, dtype=float),
                "object_kind": self.core.state.object_kind(object_id),
            }
        )
        self.widget.force_redraw()

    def update_group_preview(self, object_ids, meshes, pivot) -> None:
        """Replace selected objects and keep one fixed world-space group gizmo."""

        identifiers = [str(value) for value in object_ids]
        primary = self.core.state.selected_object_id
        vertices_by_id = []
        for object_id in identifiers:
            mesh = meshes[object_id]
            geometry_name = "obstacle::{}".format(object_id)
            if self.widget.scene.has_geometry(geometry_name):
                self.widget.scene.remove_geometry(geometry_name)
            vertices = np.asarray(mesh.vertices, dtype=float)
            faces = np.asarray(mesh.faces, dtype=int)
            color = (
                (1.0, 0.75, 0.08)
                if object_id == primary
                else (1.0, 0.48, 0.08)
            )
            if self._object_is_shown(object_id):
                self.widget.scene.add_geometry(
                    geometry_name,
                    self._triangle_mesh(vertices, faces),
                    self._material(color, 0.95),
                )
                self._obstacle_geometry_names.add(geometry_name)
                self._obstacle_meshes[object_id] = (vertices, faces)
            else:
                self._obstacle_meshes.pop(object_id, None)
            vertices_by_id.append(vertices)
        self._remove_gizmo()
        if vertices_by_id:
            self._gizmo_object_ids = identifiers
            self._add_gizmo(
                {
                    "metric_vertices": np.concatenate(vertices_by_id, axis=0),
                    "metric_transform": np.eye(4, dtype=float),
                    "object_kind": "selection_group",
                    "gizmo_space": "world",
                    "gizmo_center": np.asarray(pivot, dtype=float),
                }
            )
        self.widget.force_redraw()

    def set_reference_point_size(self, value: float) -> None:
        size = float(value)
        if not np.isfinite(size) or size <= 0.0:
            raise ValueError("Point Cloud 점 크기는 유한한 양수여야 합니다.")
        self.core.state.reference_point_size = size
        reference = self.core.point_cloud
        if (
            reference is not None
            and reference.kind != "mesh"
            and self.widget.scene.has_geometry("point_cloud")
        ):
            self._point_cloud_material = self._material(
                (0.72, 0.75, 0.78), 0.25, point=True, point_size=size
            )
            self.widget.scene.modify_geometry_material(
                "point_cloud", self._point_cloud_material
            )
            self.widget.force_redraw()

    def _project_gizmo_point(self, point):
        frame = self.widget.frame
        width, height = max(1, frame.width), max(1, frame.height)
        camera = self.widget.scene.camera
        view = np.asarray(camera.get_view_matrix(), dtype=float)
        projection = np.asarray(camera.get_projection_matrix(), dtype=float)
        homogeneous = np.append(np.asarray(point, dtype=float), 1.0)
        clip = projection @ view @ homogeneous
        if clip.shape != (4,) or not np.all(np.isfinite(clip)) or clip[3] <= 1.0e-10:
            return None
        ndc = clip[:3] / clip[3]
        if not np.all(np.isfinite(ndc)) or ndc[2] < -1.1 or ndc[2] > 1.1:
            return None
        return np.asarray(
            [
                frame.x + (ndc[0] + 1.0) * 0.5 * width,
                frame.y + (1.0 - ndc[1]) * 0.5 * height,
                ndc[2],
            ],
            dtype=float,
        )

    def project_gizmo_point(self, point):
        return self._project_gizmo_point(point)

    def pick_gizmo(self, origin, direction, screen_xy=None):
        if screen_xy is not None:
            hit = pick_projected_gizmo_axis(
                np.asarray(screen_xy, dtype=float),
                self._gizmo_frame,
                self._project_gizmo_point,
                tolerance_px=GIZMO_PICK_TOLERANCE_PX * self.ui_scale,
            )
            if hit is not None:
                return hit
        return pick_gizmo_axis(origin, direction, self._gizmo_frame)

    def is_near_gizmo(self, screen_xy) -> bool:
        """Protect selection when a click narrowly misses a visible handle."""

        return (
            pick_projected_gizmo_axis(
                np.asarray(screen_xy, dtype=float),
                self._gizmo_frame,
                self._project_gizmo_point,
                tolerance_px=GIZMO_GUARD_TOLERANCE_PX * self.ui_scale,
            )
            is not None
        )

    def set_gizmo_interaction(self, enabled: bool) -> None:
        controls = (
            self.gui.SceneWidget.Controls.PICK_POINTS
            if enabled
            else self.gui.SceneWidget.Controls.ROTATE_CAMERA
        )
        self.widget.set_view_controls(controls)

    @property
    def gizmo_frame(self) -> GizmoFrame:
        return self._gizmo_frame

    @property
    def gizmo_object_ids(self):
        return list(self._gizmo_object_ids)

    @property
    def obstacle_meshes(self):
        return [
            (key, value[0], value[1]) for key, value in self._obstacle_meshes.items()
        ]

    def ray(self, x: int, y: int):
        frame = self.widget.frame
        local_x, local_y = float(x - frame.x), float(y - frame.y)
        width, height = max(1, frame.width), max(1, frame.height)
        near = np.asarray(
            self.widget.scene.camera.unproject(local_x, local_y, 0.0, width, height),
            dtype=float,
        )
        far = np.asarray(
            self.widget.scene.camera.unproject(local_x, local_y, 1.0, width, height),
            dtype=float,
        )
        direction = far - near
        length = float(np.linalg.norm(direction))
        return near, direction / length

    def set_fps_navigation(self, enabled: bool) -> None:
        controls = (
            self.gui.SceneWidget.Controls.PICK_POINTS
            if enabled
            else self.gui.SceneWidget.Controls.ROTATE_CAMERA
        )
        self.widget.set_view_controls(controls)

    def camera_view_matrix(self) -> np.ndarray:
        return np.asarray(self.widget.scene.camera.get_view_matrix(), dtype=float)

    def translate_camera(self, delta) -> Dict[str, list]:
        eye, forward, _, up = camera_pose_from_view(self.camera_view_matrix())
        movement = np.asarray(delta, dtype=float)
        if movement.shape != (3,) or not np.all(np.isfinite(movement)):
            raise ValueError("Camera movement는 finite xyz vector여야 합니다.")
        new_eye = eye + movement
        target = new_eye + forward
        self.widget.scene.camera.look_at(target, new_eye, up)
        self.update_gizmo_front_geometry(force=True, redraw=False)
        self.widget.force_redraw()
        return {
            "eye": new_eye.tolist(),
            "forward": forward.tolist(),
            "up": up.tolist(),
        }

    def rotate_fps_camera(self, delta_x, delta_y, settings) -> Dict[str, list]:
        pose = constrained_look_pose(
            self.camera_view_matrix(),
            delta_x,
            delta_y,
            settings.mouse_sensitivity_deg_per_pixel,
            settings.maximum_pitch_deg,
        )
        eye = np.asarray(pose["eye"], dtype=float)
        forward = np.asarray(pose["forward"], dtype=float)
        self.widget.scene.camera.look_at(eye + forward, eye, pose["up"])
        self.update_gizmo_front_geometry(force=True, redraw=False)
        self.widget.force_redraw()
        return pose

    def frame_room(self):
        box = self.o3d.geometry.AxisAlignedBoundingBox(
            self.core.scene.containment.bounds_min,
            self.core.scene.containment.bounds_max,
        )
        self.widget.setup_camera(60.0, box, self.core.scene.center)
        self.update_gizmo_front_geometry(force=True)

    def frame_origin(self, config):
        pose = origin_camera_pose(
            self.core.scene.containment.bounds_min,
            config["eye_offset_m"],
            config["target_offset_m"],
        )
        self.widget.look_at(pose["target"], pose["eye"], pose["up"])
        self.core.state.camera = {
            key: pose[key] for key in ("eye", "forward", "up")
        }
        self.update_gizmo_front_geometry(force=True)

    def frame_selected(self):
        object_ids = list(
            getattr(self.core.state, "selected_object_ids", [])
        )
        if not object_ids and self.core.state.selected_object_id is not None:
            object_ids = [self.core.state.selected_object_id]
        vertices_by_id = [
            self._obstacle_meshes[object_id][0]
            for object_id in object_ids
            if object_id in self._obstacle_meshes
        ]
        if not vertices_by_id:
            return
        vertices = np.concatenate(vertices_by_id, axis=0)
        box = self.o3d.geometry.AxisAlignedBoundingBox(
            np.min(vertices, axis=0), np.max(vertices, axis=0)
        )
        self.widget.setup_camera(60.0, box, np.mean(vertices, axis=0))
        self.update_gizmo_front_geometry(force=True)

    def set_view(self, view: str):
        center = self.core.scene.center
        extent = np.linalg.norm(
            self.core.scene.containment.bounds_max
            - self.core.scene.containment.bounds_min
        )
        directions = {
            "front": np.array([0.0, -1.0, 0.0]),
            "side": np.array([1.0, 0.0, 0.0]),
            "top": np.array([0.0, 0.0, 1.0]),
        }
        eyes = center + directions[view] * extent
        up = np.array([0.0, 0.0, 1.0]) if view != "top" else np.array([0.0, 1.0, 0.0])
        self.widget.look_at(center, eyes, up)
        self.update_gizmo_front_geometry(force=True)
