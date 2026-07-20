"""Open3D SceneWidget rendering and camera/ray utilities."""

from __future__ import annotations

from typing import Any, Dict, Tuple

import numpy as np

from ..fps_camera_controller import camera_pose_from_view
from ..gizmo import (
    AXIS_COLORS,
    AXIS_NAMES,
    GizmoFrame,
    make_gizmo_frame,
    pick_gizmo_axis,
    pick_projected_gizmo_axis,
    ring_points,
)


class PlacementViewport:
    def __init__(self, renderer, core):
        import open3d as o3d
        from open3d.visualization import gui, rendering

        self.o3d, self.gui, self.rendering = o3d, gui, rendering
        self.core = core
        self.widget = gui.SceneWidget()
        self.widget.scene = rendering.Open3DScene(renderer)
        self.widget.scene.set_background([0.04, 0.045, 0.055, 1.0])
        self.widget.scene.show_axes(True)
        self._obstacle_meshes: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}
        self._obstacle_geometry_names = set()
        self._gizmo_geometry_names = set()
        self._gizmo_labels = []
        self._gizmo_frame = None
        self._reference_material = None
        self._add_room()
        self._add_grid()
        self._add_reference()
        self.refresh(core.validate())
        self.frame_room()

    def _material(
        self, color, alpha=1.0, line=False, point=False, point_size=None
    ):
        material = self.rendering.MaterialRecord()
        if line:
            material.shader = "unlitLine"
            material.line_width = 1.5
        elif point:
            material.shader = "defaultUnlit"
            material.point_size = float(
                self.core.state.reference_point_size
                if point_size is None
                else point_size
            )
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

    def _triangle_mesh(self, vertices, faces):
        mesh = self.o3d.geometry.TriangleMesh(
            self.o3d.utility.Vector3dVector(np.asarray(vertices, dtype=float)),
            self.o3d.utility.Vector3iVector(np.asarray(faces, dtype=int)),
        )
        mesh.compute_vertex_normals()
        return mesh

    def _add_room(self):
        mesh = self._triangle_mesh(
            self.core.scene.room_vertices, self.core.scene.room_faces
        )
        self.widget.scene.add_geometry(
            "room", mesh, self._material((0.55, 0.58, 0.62), 0.18)
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

    def _add_reference(self):
        reference = self.core.reference
        if reference is None:
            return
        if reference.kind == "mesh":
            geometry = self._triangle_mesh(reference.vertices_metric, reference.faces)
            material = self._material((0.72, 0.75, 0.78), 0.12)
        else:
            geometry = self.o3d.geometry.PointCloud(
                self.o3d.utility.Vector3dVector(reference.vertices_metric)
            )
            if reference.colors is not None:
                geometry.colors = self.o3d.utility.Vector3dVector(reference.colors)
            material = self._material((0.72, 0.75, 0.78), 0.25, point=True)
        self._reference_material = material
        self.widget.scene.add_geometry("reference", geometry, material)

    def _remove_obstacles(self):
        for name in self._obstacle_geometry_names:
            if self.widget.scene.has_geometry(name):
                self.widget.scene.remove_geometry(name)
        self._obstacle_geometry_names.clear()

    def _remove_gizmo(self):
        for name in self._gizmo_geometry_names:
            if self.widget.scene.has_geometry(name):
                self.widget.scene.remove_geometry(name)
        self._gizmo_geometry_names.clear()
        for label in self._gizmo_labels:
            self.widget.remove_3d_label(label)
        self._gizmo_labels.clear()
        self._gizmo_frame = None

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

    def _add_gizmo(self, record):
        mode = self.core.state.viewport_mode
        if mode not in {"translate", "rotate", "scale"}:
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
            self.core.state.transform_space,
            room_diagonal,
        )
        self._gizmo_frame = frame
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
                label = self.widget.add_3d_label(
                    ring[0], "{} {}".format(axis_name.upper(), "회전")
                )
                label.color = self.gui.Color(*AXIS_COLORS[axis_name])
                self._gizmo_labels.append(label)
            name = "gizmo::rotation_rings"
            self.widget.scene.add_geometry(
                name,
                self._colored_line_set(points, lines, colors),
                self._material((1.0, 1.0, 1.0), line=True),
            )
            self._gizmo_geometry_names.add(name)
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
                    handle = self.o3d.geometry.TriangleMesh.create_cone(
                        radius=frame.length * 0.075,
                        height=frame.length * 0.24,
                        resolution=16,
                    )
                    handle.rotate(self._align_z_to_axis(axis), center=(0, 0, 0))
                    handle.translate(frame.center + axis * frame.length * 0.76)
                else:
                    size = frame.length * 0.13
                    handle = self.o3d.geometry.TriangleMesh.create_box(size, size, size)
                    handle.translate(endpoint - size / 2.0)
                handle.compute_vertex_normals()
                name = "gizmo::{}::{}".format(mode, axis_name)
                self.widget.scene.add_geometry(
                    name, handle, self._material(AXIS_COLORS[axis_name])
                )
                self._gizmo_geometry_names.add(name)
                label = self.widget.add_3d_label(
                    endpoint + axis * frame.length * 0.10, axis_name.upper()
                )
                label.color = self.gui.Color(*AXIS_COLORS[axis_name])
                self._gizmo_labels.append(label)
            name = "gizmo::axis_lines"
            self.widget.scene.add_geometry(
                name,
                self._colored_line_set(points, lines, colors),
                self._material((1.0, 1.0, 1.0), line=True),
            )
            self._gizmo_geometry_names.add(name)

    def _update_background_visibility(self):
        mode = self.core.state.scene_display_mode
        if self.widget.scene.has_geometry("room"):
            self.widget.scene.show_geometry(
                "room", mode in {"both", "proxy_mesh"}
            )
        if self.widget.scene.has_geometry("reference"):
            self.widget.scene.show_geometry(
                "reference",
                mode in {"both", "point_cloud"}
                and self.core.state.reference_visible,
            )
        if self.widget.scene.has_geometry("floor_grid"):
            self.widget.scene.show_geometry(
                "floor_grid", self.core.state.grid_visible
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
        }
        for record in report["objects"]:
            if not record.get(
                "renderable"
            ) or not self.core.state.object_visibility.get(record["id"], True):
                continue
            if not record["enabled"] and not self.core.state.show_disabled:
                continue
            vertices = np.asarray(record["metric_vertices"], dtype=float)
            faces = np.asarray(record["faces"], dtype=int)
            self._obstacle_meshes[record["id"]] = (vertices, faces)
            if record["id"] == self.core.state.selected_object_id:
                color, alpha = (1.0, 0.75, 0.08), 0.95
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
        selected = next(
            (
                value
                for value in report["objects"]
                if value["id"] == self.core.state.selected_object_id
                and value.get("renderable")
            ),
            None,
        )
        if selected is not None:
            self._add_gizmo(selected)
        self.widget.force_redraw()

    def update_object_preview(self, object_id, mesh) -> None:
        """Replace only the dragged object and gizmo; keep all background layers."""

        geometry_name = "obstacle::{}".format(object_id)
        if self.widget.scene.has_geometry(geometry_name):
            self.widget.scene.remove_geometry(geometry_name)
        vertices = np.asarray(mesh.vertices, dtype=float)
        faces = np.asarray(mesh.faces, dtype=int)
        self.widget.scene.add_geometry(
            geometry_name,
            self._triangle_mesh(vertices, faces),
            self._material((1.0, 0.75, 0.08), 0.95),
        )
        self._obstacle_geometry_names.add(geometry_name)
        self._obstacle_meshes[object_id] = (vertices, faces)
        self._remove_gizmo()
        self._add_gizmo(
            {
                "metric_vertices": vertices,
                "metric_transform": np.asarray(mesh.transform, dtype=float),
            }
        )
        self.widget.force_redraw()

    def set_reference_point_size(self, value: float) -> None:
        size = float(value)
        if not np.isfinite(size) or size <= 0.0:
            raise ValueError("Point Cloud 점 크기는 유한한 양수여야 합니다.")
        self.core.state.reference_point_size = size
        reference = self.core.reference
        if (
            reference is not None
            and reference.kind != "mesh"
            and self.widget.scene.has_geometry("reference")
        ):
            self._reference_material = self._material(
                (0.72, 0.75, 0.78), 0.25, point=True, point_size=size
            )
            self.widget.scene.modify_geometry_material(
                "reference", self._reference_material
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
            )
            if hit is not None:
                return hit
        return pick_gizmo_axis(origin, direction, self._gizmo_frame)

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
            self.gui.SceneWidget.Controls.FLY
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
        self.widget.force_redraw()
        return {
            "eye": new_eye.tolist(),
            "forward": forward.tolist(),
            "up": up.tolist(),
        }

    def frame_room(self):
        box = self.o3d.geometry.AxisAlignedBoundingBox(
            self.core.scene.containment.bounds_min,
            self.core.scene.containment.bounds_max,
        )
        self.widget.setup_camera(60.0, box, self.core.scene.center)

    def frame_selected(self):
        object_id = self.core.state.selected_object_id
        if object_id not in self._obstacle_meshes:
            return
        vertices = self._obstacle_meshes[object_id][0]
        box = self.o3d.geometry.AxisAlignedBoundingBox(
            np.min(vertices, axis=0), np.max(vertices, axis=0)
        )
        self.widget.setup_camera(60.0, box, np.mean(vertices, axis=0))

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
