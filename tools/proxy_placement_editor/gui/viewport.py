"""Open3D SceneWidget rendering and camera/ray utilities."""

from __future__ import annotations

from typing import Any, Dict, Tuple

import numpy as np

from ..fps_camera_controller import camera_pose_from_view


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
        self.refresh(core.validate())
        self.frame_room()

    def _material(self, color, alpha=1.0, line=False, point=False):
        material = self.rendering.MaterialRecord()
        if line:
            material.shader = "unlitLine"
            material.line_width = 1.5
        elif point:
            material.shader = "defaultUnlit"
            material.point_size = 2.0
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
        self.widget.scene.add_geometry("reference", geometry, material)

    def refresh(self, report: Dict[str, Any]) -> None:
        self.widget.scene.clear_geometry()
        self._obstacle_meshes.clear()
        self._add_room()
        if self.core.state.grid_visible:
            self._add_grid()
        if self.core.state.reference_visible:
            self._add_reference()
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
            self.widget.scene.add_geometry(
                "obstacle::{}".format(record["id"]),
                self._triangle_mesh(vertices, faces),
                self._material(color, alpha),
            )
        self.widget.force_redraw()

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
