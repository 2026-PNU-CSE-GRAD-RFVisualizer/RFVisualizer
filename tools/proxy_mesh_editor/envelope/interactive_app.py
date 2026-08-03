"""Open3D 3D Viewer에서 Floor/Ceiling/Wall 후보를 클릭으로 골라 Room Envelope를 만드는 GUI.

선택 로직 자체는 selection.py에 있고(디스플레이 없이도 테스트 가능), 이 모듈은
그 상태를 3D 뷰와 사이드 패널에 그리기만 한다. 후보 사각형과 픽킹 계산은
proxy_mesh_editor의 기존 데이터 구조(PlaneCandidate, rectangle_triangles)를
그대로 쓰고, ray-triangle 픽킹과 한글 폰트 설정은 proxy_placement_editor의
검증된 헬퍼(picking.py, gui/korean_font.py, gui/section.py, gui/metrics.py)를
재사용한다.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import numpy as np
import yaml

from tools.proxy_placement_editor.gui.korean_font import (
    configure_heading_font,
    configure_korean_font,
)
from tools.proxy_placement_editor.gui.metrics import scaled, scaled_margins
from tools.proxy_placement_editor.gui.section import make_section
from tools.proxy_placement_editor.picking import nearest_obstacle_hit

from ..geometry.plane_mesher import rectangle_triangles
from ..io.metadata_io import read_json
from ..models import PlaneCandidate
from .report import write_envelope_outputs
from .selection import EnvelopeAttempt, EnvelopeSelectionState, attempt_build
from .validator import EnvelopeValidationError, validate_envelope


SELECTED_ALPHA = 0.95
UNSELECTED_ALPHA = 0.28
ENVELOPE_PREVIEW_COLOR = (0.25, 0.85, 0.35)
ENVELOPE_PREVIEW_ALPHA = 0.55
STATUS_OK_COLOR = (0.35, 0.9, 0.45)
STATUS_ERROR_COLOR = (1.0, 0.45, 0.25)
SIDE_PANEL_WIDTH = 400
CLICK_DRAG_TOLERANCE_PX = 3.0


def ensure_gui_display() -> None:
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        raise ValueError(
            "Open3D GUI를 열 display server가 없습니다. "
            "headless로는 build-envelope에 완성된 envelope_config.yaml을 지정해 주세요."
        )


class EnvelopeAssemblyApp:
    def __init__(
        self,
        plane_path: Path,
        wall_path: Path,
        base_envelope_config: Dict[str, Any],
        output: Path,
        width: int = 1440,
        height: int = 900,
    ) -> None:
        ensure_gui_display()
        import open3d as o3d
        from open3d.visualization import gui, rendering

        self.o3d, self.gui, self.rendering = o3d, gui, rendering
        self.plane_path = Path(plane_path).expanduser().resolve()
        self.wall_path = Path(wall_path).expanduser().resolve()
        self.base_config = base_envelope_config
        self.output = Path(output).expanduser().resolve()

        plane_document = read_json(self.plane_path)
        wall_document = read_json(self.wall_path)
        self.floor_ceiling_candidates: List[PlaneCandidate] = [
            PlaneCandidate.from_dict(item)
            for item in plane_document.get("plane_candidates", [])
            if item.get("orientation") == "horizontal"
        ]
        self.wall_candidates: List[PlaneCandidate] = [
            PlaneCandidate.from_dict(item)
            for item in wall_document.get("wall_candidates", [])
        ]
        if not self.floor_ceiling_candidates:
            raise ValueError("plane_candidates.json에 horizontal 후보가 없습니다.")
        if len(self.wall_candidates) < 3:
            raise ValueError("wall_candidates.json에 벽 후보가 3개 미만입니다.")
        self._wall_ids: Set[str] = {c.candidate_id for c in self.wall_candidates}

        self.state = EnvelopeSelectionState()
        self.last_attempt: Optional[EnvelopeAttempt] = None
        self._geometry_names: Set[str] = set()

        app = gui.Application.instance
        app.initialize()
        korean_font_path = configure_korean_font(gui, app, point_size=16)
        self.heading_font_id = configure_heading_font(
            gui, app, korean_font_path, point_size=18
        )
        self.window = app.create_window("Room Envelope 선택", width, height)

        self.widget = gui.SceneWidget()
        self.widget.scene = rendering.Open3DScene(self.window.renderer)
        self.widget.scene.set_background([0.05, 0.05, 0.06, 1.0])
        self.widget.scene.show_axes(True)
        self.widget.set_view_controls(gui.SceneWidget.Controls.ROTATE_CAMERA)
        self._press_xy: Optional[tuple] = None
        self.widget.set_on_mouse(self._on_mouse)

        self.side = gui.ScrollableVert(
            scaled(4, 1.0), scaled_margins(gui, 8, 8, 8, 8, 1.0)
        )
        self.status_label = gui.Label("")
        self.side.add_child(self.status_label)
        self.floor_list = self._make_candidate_list(
            "Floor 후보 (클릭 1개 선택)", self.floor_ceiling_candidates
        )
        self.ceiling_list = self._make_candidate_list(
            "Ceiling 후보 (클릭 1개 선택)", self.floor_ceiling_candidates
        )
        self.wall_list = self._make_candidate_list(
            "Wall 후보 (클릭 순서 = 벽 순서, 다시 클릭하면 해제)", self.wall_candidates
        )
        self.side.add_child(self.floor_list["section"])
        self.side.add_child(self.ceiling_list["section"])
        self.side.add_child(self.wall_list["section"])

        actions = gui.Horiz(scaled(6, 1.0))
        reset_button = gui.Button("초기화")
        reset_button.set_on_clicked(self._reset)
        confirm_button = gui.Button("선택 확정 (Build)")
        confirm_button.set_on_clicked(self._confirm)
        actions.add_child(reset_button)
        actions.add_child(confirm_button)
        self.side.add_child(actions)

        self.window.add_child(self.widget)
        self.window.add_child(self.side)
        self.window.set_on_layout(self._layout)
        self._frame_scene()
        self._refresh()

    # -- 레이아웃 -----------------------------------------------------

    def _layout(self, context) -> None:
        rect = self.window.content_rect
        side_width = SIDE_PANEL_WIDTH
        self.widget.frame = self.gui.Rect(
            rect.x, rect.y, rect.width - side_width, rect.height
        )
        self.side.frame = self.gui.Rect(
            rect.get_right() - side_width, rect.y, side_width, rect.height
        )

    def _frame_scene(self) -> None:
        all_corners = np.vstack(
            [
                candidate.rectangle.corners
                for candidate in self.floor_ceiling_candidates + self.wall_candidates
            ]
        )
        bbox = self.o3d.geometry.AxisAlignedBoundingBox(
            all_corners.min(axis=0), all_corners.max(axis=0)
        )
        self.widget.setup_camera(60.0, bbox, bbox.get_center())

    # -- 후보 목록 패널 ------------------------------------------------

    def _make_candidate_list(self, title: str, candidates: List[PlaneCandidate]) -> Dict[str, Any]:
        gui = self.gui
        section = make_section(gui, title, self.heading_font_id, 1.0)
        listview = gui.ListView()
        listview.set_max_visible_items(6)
        ids = [candidate.candidate_id for candidate in candidates]

        def _selection_changed(value, is_double_click):
            index = listview.selected_index
            if 0 <= index < len(ids):
                self._handle_pick(ids[index])

        listview.set_on_selection_changed(_selection_changed)
        section.add_child(listview)
        return {"section": section, "list": listview, "ids": ids, "candidates": candidates}

    def _item_text(self, candidate: PlaneCandidate, marker: str) -> str:
        return "{} {} (면적 {:.2f})".format(marker, candidate.candidate_id, candidate.rectangle.area)

    def _refresh_lists(self) -> None:
        self.floor_list["list"].set_items(
            [
                self._item_text(candidate, "●" if candidate.candidate_id == self.state.floor_id else " ")
                for candidate in self.floor_ceiling_candidates
            ]
        )
        self.ceiling_list["list"].set_items(
            [
                self._item_text(candidate, "●" if candidate.candidate_id == self.state.ceiling_id else " ")
                for candidate in self.floor_ceiling_candidates
            ]
        )
        wall_items = []
        for candidate in self.wall_candidates:
            if candidate.candidate_id in self.state.wall_ids:
                order = self.state.wall_ids.index(candidate.candidate_id) + 1
                marker = "[{}]".format(order)
            else:
                marker = " "
            wall_items.append(self._item_text(candidate, marker))
        self.wall_list["list"].set_items(wall_items)
        for entry in (self.floor_list, self.ceiling_list, self.wall_list):
            entry["list"].selected_index = -1

    # -- 선택 처리 -----------------------------------------------------

    def _handle_pick(self, candidate_id: str) -> None:
        if candidate_id in self._wall_ids:
            self.state.toggle_wall(candidate_id)
        elif self.state.floor_id is None:
            self.state.toggle_floor(candidate_id)
        elif self.state.ceiling_id is None:
            self.state.toggle_ceiling(candidate_id)
        elif candidate_id in (self.state.floor_id, self.state.ceiling_id):
            # Floor/Ceiling을 다시 클릭하면 해제해서 다시 고를 수 있게 한다.
            self.state.toggle_floor(candidate_id)
            self.state.toggle_ceiling(candidate_id)
        self._refresh()

    def _reset(self) -> None:
        self.state.reset()
        self._refresh()

    def _refresh(self) -> None:
        self.last_attempt = attempt_build(
            self.plane_path, self.wall_path, self.base_config, self.state
        )
        self._redraw_geometry()
        self._refresh_lists()
        if self.last_attempt.mesh is not None:
            self.status_label.text = (
                "닫힌 Room Envelope 미리보기 생성됨 (벽 {}개). "
                "'선택 확정'을 누르면 저장됩니다.".format(len(self.state.wall_ids))
            )
            self.status_label.text_color = self.gui.Color(*STATUS_OK_COLOR)
        else:
            self.status_label.text = self.last_attempt.error or ""
            self.status_label.text_color = self.gui.Color(*STATUS_ERROR_COLOR)
        self.window.set_needs_layout()
        self.window.post_redraw()

    # -- 3D 렌더링 -----------------------------------------------------

    def _material(self, color, alpha: float):
        material = self.rendering.MaterialRecord()
        material.shader = "defaultLitTransparency" if alpha < 0.999 else "defaultLit"
        material.base_color = [float(color[0]), float(color[1]), float(color[2]), float(alpha)]
        return material

    def _rectangle_mesh(self, candidate: PlaneCandidate):
        o3d = self.o3d
        mesh = o3d.geometry.TriangleMesh(
            vertices=o3d.utility.Vector3dVector(candidate.rectangle.corners),
            triangles=o3d.utility.Vector3iVector(rectangle_triangles()),
        )
        mesh.compute_vertex_normals()
        return mesh

    def _is_selected(self, candidate_id: str) -> bool:
        return candidate_id in (self.state.floor_id, self.state.ceiling_id) or (
            candidate_id in self.state.wall_ids
        )

    def _redraw_geometry(self) -> None:
        scene = self.widget.scene
        for name in self._geometry_names:
            if scene.has_geometry(name):
                scene.remove_geometry(name)
        self._geometry_names = set()
        for candidate in self.floor_ceiling_candidates + self.wall_candidates:
            name = "cand_{}".format(candidate.candidate_id)
            selected = self._is_selected(candidate.candidate_id)
            base_color = np.clip(np.asarray(candidate.color, dtype=float), 0.0, 1.0)
            color = base_color if selected else 0.5 * base_color + 0.25
            alpha = SELECTED_ALPHA if selected else UNSELECTED_ALPHA
            scene.add_geometry(name, self._rectangle_mesh(candidate), self._material(color, alpha))
            self._geometry_names.add(name)
        if scene.has_geometry("envelope_preview"):
            scene.remove_geometry("envelope_preview")
        if self.last_attempt is not None and self.last_attempt.mesh is not None:
            mesh = self.last_attempt.mesh
            preview = self.o3d.geometry.TriangleMesh(
                vertices=self.o3d.utility.Vector3dVector(mesh.vertices),
                triangles=self.o3d.utility.Vector3iVector(mesh.faces.astype(np.int32)),
            )
            preview.compute_vertex_normals()
            scene.add_geometry(
                "envelope_preview",
                preview,
                self._material(ENVELOPE_PREVIEW_COLOR, ENVELOPE_PREVIEW_ALPHA),
            )
            self._geometry_names.add("envelope_preview")

    # -- 마우스 픽킹 ----------------------------------------------------

    def _ray(self, x: int, y: int):
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
        return near, (direction / length if length > 0.0 else direction)

    def _on_mouse(self, event):
        # 왼쪽 드래그는 항상 SceneWidget의 기본 카메라 회전(궤도 회전)에 맡긴다.
        # 여기서는 어떤 이벤트도 CONSUMED로 가로채지 않고, 클릭(눌렀다 뗀 위치가
        # 거의 같음)일 때만 곁다리로 후보를 픽킹한다. 매번 BUTTON_DOWN을 그대로
        # 후보 픽킹으로 소비하면 화면 대부분을 덮은 후보 사각형 위에서 드래그를
        # 시작할 때마다 카메라 회전이 막혀버린다.
        gui = self.gui
        if event.type == gui.MouseEvent.Type.BUTTON_DOWN and event.is_button_down(
            gui.MouseButton.LEFT
        ):
            self._press_xy = (event.x, event.y)
        elif event.type == gui.MouseEvent.Type.BUTTON_UP and self._press_xy is not None:
            start_x, start_y = self._press_xy
            self._press_xy = None
            moved = abs(event.x - start_x) + abs(event.y - start_y)
            if moved <= CLICK_DRAG_TOLERANCE_PX:
                origin, direction = self._ray(start_x, start_y)
                meshes = [
                    (candidate.candidate_id, candidate.rectangle.corners, rectangle_triangles())
                    for candidate in self.floor_ceiling_candidates + self.wall_candidates
                ]
                hit = nearest_obstacle_hit(origin, direction, meshes)
                if hit is not None:
                    self._handle_pick(str(hit["object_id"]))
        return gui.Widget.EventCallbackResult.IGNORED

    # -- 확정 -----------------------------------------------------------

    def _write_resolved_config(self, config: Dict[str, Any]) -> Path:
        path = self.output / "envelope_config.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return path.resolve()

    def _confirm(self) -> None:
        attempt = self.last_attempt
        if attempt is None or attempt.mesh is None or attempt.candidates is None:
            self.window.show_message_box(
                "확정 불가", "먼저 Floor/Ceiling/Wall을 골라 닫힌 Room Envelope를 만드세요."
            )
            return
        validation_settings = attempt.envelope_config["room_envelope"]["validation"]
        try:
            topology, geometry, warnings = validate_envelope(attempt.mesh, validation_settings)
        except EnvelopeValidationError as exc:
            self.window.show_message_box("검증 실패", str(exc))
            return
        config_path = self._write_resolved_config(attempt.envelope_config)
        document = write_envelope_outputs(
            attempt.candidates,
            attempt.envelope_config,
            config_path,
            attempt.mesh,
            topology,
            geometry,
            warnings,
            self.output,
        )
        self.window.show_message_box(
            "완료",
            "Room Envelope를 저장했습니다.\n{}\n{}".format(
                document["output_files"]["combined_obj"], config_path
            ),
        )

    def run(self) -> None:
        self.gui.Application.instance.run()
