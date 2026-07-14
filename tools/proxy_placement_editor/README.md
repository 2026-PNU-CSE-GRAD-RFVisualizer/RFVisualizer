# Phase 2-C Interactive Proxy Placement Editor

Metric Room Envelope와 선택적 PGSR 참조 형상을 보면서 Proxy Obstacle을 배치하고, 기존 Phase 2-B scenario YAML을 그대로 저장하는 Open3D 편집기다.

> **PROVISIONAL GEOMETRY**
>
> 현재 Metric scale과 proxy 배치는 현장 실측으로 검증되지 않았다. Candidate 기본 크기는 UI 편의용 placeholder이며 실제 강의실 치수가 아니다. 이 장면의 Sionna 결과를 실제 RSSI 정확도로 해석하면 안 된다.

실제 구현 검증 결과와 수동 UI 미확인 항목은 [PHASE2C_VALIDATION.md](PHASE2C_VALIDATION.md)에 기록한다.

## 설계 원칙

- Scenario YAML이 유일한 RF 장면 정의다. 카메라·패널·선택·표시 상태는 `editor_state.json`에 따로 저장한다.
- `tools/sionna_scenario/`의 obstacle schema, primitive builder, room validator, material resolver와 scene builder를 재사용한다.
- Room OBJ/JSON과 calibration은 읽기 전용으로 열고 SHA-256을 결과에 기록한다. 방 꼭짓점, boolean, 문 opening, calibration은 수정하지 않는다.
- 모든 편집은 meter/+Z Metric 좌표에서 수행한다. 각 obstacle의 Metric/PGSR vertex와 4×4 transform, 왕복 오차를 함께 내보낸다.
- Candidate를 Add하면 구체적인 placeholder geometry는 보이지만 `enabled: false`, `confidence: unset`, `placement_status: provisional_unconfirmed` 상태다. 사용자가 명시적으로 활성화해야 Sionna scene에 들어간다.
- Open3D GUI와 독립된 코어를 사용하므로 display server가 없어도 load/transform/validate/save/preview 테스트가 실행된다.

## 환경 선택

`pgsr` 환경의 Open3D 0.19.0 `visualization.gui`와 `SceneWidget`을 사용한다. 이 환경에는 PySide6, VTK, PyVista가 없으므로 새 대형 GUI 의존성을 추가하지 않았다.

```bash
conda run -n pgsr python -c "import open3d; print(open3d.__version__)"
```

Open3D 데스크톱 창에는 X11 또는 Wayland display가 필요하다. Display가 없는 서버에서는 `edit`가 명확한 오류로 종료되고 `validate`, `export-preview`는 계속 사용할 수 있다.

## 명령

### 편집기

```bash
conda run -n pgsr python -m tools.proxy_placement_editor.main edit \
  --room-obj outputs/proxy_mesh/pnu_classroom/metric_calibration/room_envelope_metric.obj \
  --room-json outputs/proxy_mesh/pnu_classroom/metric_calibration/room_envelope_metric.json \
  --calibration outputs/proxy_mesh/pnu_classroom/metric_calibration/calibration.json \
  --scenario configs/sionna/scenarios/pnu_classroom_proxy_draft.yaml \
  --output outputs/proxy_placement/pnu_classroom
```

저장소에 실제 존재하는 표시 전용 PGSR/TSDF 참조 메시 예시는 다음과 같다.

```bash
conda run -n pgsr python -m tools.proxy_placement_editor.main edit \
  --room-obj outputs/proxy_mesh/pnu_classroom/metric_calibration/room_envelope_metric.obj \
  --room-json outputs/proxy_mesh/pnu_classroom/metric_calibration/room_envelope_metric.json \
  --calibration outputs/proxy_mesh/pnu_classroom/metric_calibration/calibration.json \
  --scenario configs/sionna/scenarios/pnu_classroom_proxy_draft.yaml \
  --reference-mesh PGSR/output/pnu_classroom/mesh/tsdf_fusion_post.ply \
  --reference-coordinate-space scene \
  --output outputs/proxy_placement/pnu_classroom
```

Reference 입력은 OBJ, triangle-mesh PLY, point-cloud PLY다. `scene` 입력에는 calibration의 `T_metric_from_scene`을 적용한다. 큰 PLY mesh는 수백만 triangle을 GUI 시작 시 단순화하지 않고 PLY의 vertex/color만 읽어 최대 50만 점의 표시용 point cloud로 결정적으로 축약한다. 원본, scenario, Sionna export에는 반영하지 않는다.

### RustDesk / Wayland GUI runtime

Ubuntu 24.04 GNOME Wayland의 XWayland 세션에서 `pgsr`에 설치된 CUDA Open3D 0.19.0은 `Application.create_window()` 중 native signal 11로 종료될 수 있다. Reference mesh 크기와 무관하며 최소 빈 창에서도 재현된다. PGSR 환경의 Open3D를 교체하지 말고, 편집기 전용 Open3D 0.18 CPU runtime을 한 번 준비한다.

```bash
conda run -n pgsr python -m tools.proxy_placement_editor.main setup-gui-runtime
```

runtime은 git에서 제외되는 `.venv/proxy-placement-editor`에 생성하며, `pgsr`의 기존 Python package를 공유하고 `open3d-cpu==0.18.0`만 우선 사용한다. 이후 기존 `edit` 명령은 이 runtime을 자동 선택한다. 다른 위치의 Python을 사용하려면 `RFVIS_PROXY_EDITOR_GUI_PYTHON=/path/to/python`을 지정할 수 있다.

호환 runtime이 없으면 기존처럼 네이티브 GPU GUI를 시도하고, segmentation fault/abort signal이면 Linux Mesa 소프트웨어 렌더링으로 한 번 재시도한다. GPU 경로를 건너뛰려면 `edit` 명령에 `--software-rendering`을 추가한다. 두 경로가 모두 실패하면 GNOME 로그인 화면에서 `Ubuntu on Xorg` 세션을 선택한다. Open3D GUI에는 OpenGL 4.1 이상이 필요하며, 소프트웨어 렌더링은 GPU보다 느릴 수 있다.

### Headless 검증

Room OBJ는 Room JSON 또는 scenario가 참조하는 Phase 2-A 설정에서 추론할 수 있다.

```bash
conda run -n pgsr python -m tools.proxy_placement_editor.main validate \
  --scenario configs/sionna/scenarios/pnu_classroom_synthetic_blocker.yaml \
  --room-json outputs/proxy_mesh/pnu_classroom/metric_calibration/room_envelope_metric.json \
  --calibration outputs/proxy_mesh/pnu_classroom/metric_calibration/calibration.json \
  --output outputs/proxy_placement/pnu_classroom
```

활성 obstacle에 schema 오류, null, non-positive size, NaN/Inf, room 침투, 재질 오류, 좌표 왕복 오류가 있으면 exit code 2다. 비활성 draft의 null geometry는 `DISABLED_INCOMPLETE`로 기록하고 전체 검증은 통과한다. AABB 충돌과 벽 근접은 warning이며 저장을 막지 않는다.

### 미리보기

```bash
conda run -n pgsr python -m tools.proxy_placement_editor.main export-preview \
  --scenario configs/sionna/scenarios/pnu_classroom_synthetic_blocker.yaml \
  --reference-mesh PGSR/output/pnu_classroom/mesh/tsdf_fusion_post.ply \
  --reference-coordinate-space scene \
  --output outputs/proxy_placement/pnu_classroom/preview
```

`--exclude-reference`를 추가하면 PNG에서 reference를 제외한다.

## 화면과 상호작용

중앙 Viewport는 반투명 Room, +Z Metric 축, 경사진 floor grid, optional reference, 유효/무효/비활성 obstacle을 서로 다른 geometry layer로 표시한다. Room/reference는 picking 대상이 아니며 겹친 obstacle 중 광선의 가장 가까운 triangle hit가 선택된다. 오른쪽에는 Candidate, Object List, Identity/Geometry/Transform/Material 속성, 실시간 clearance·collision·좌표 검증, 외부 명령 로그가 있다.

| 입력 | 동작 |
|---|---|
| 왼쪽 클릭 | 가장 가까운 obstacle 선택, 빈 공간은 선택 해제 |
| 우클릭 드래그 + `W/A/S/D` | FPS 시점 회전 + 수평 전후좌우 이동 |
| 우클릭 + Shift | FPS 이동 속도 증가 |
| Alt+왼쪽 / 가운데 드래그 / Wheel | Open3D Orbit / Pan / Zoom |
| `G` + drag | 실제 floor plane 광선 교점으로 XY 이동; `floor_at_xy`는 Z 자동 갱신 |
| `R` + horizontal drag | 기본 yaw 회전 |
| `S` + horizontal drag | 균일 크기 조절 |
| `X`, `Y`, `Z` | 활성 transform 축 제한 |
| Shift / Ctrl | 미세 조작 / grid snap |
| `F`, Home | 선택 object / 전체 room frame |
| Delete, Ctrl+D | 삭제 / 비활성 복제 |
| Ctrl+Z, Ctrl+Y, Ctrl+Shift+Z | Undo / Redo |
| Ctrl+S | 전체 검증 후 저장 |
| `V`, `H` | reference / 선택 object 표시 전환 |
| `1`, `3`, `7` | Front / Side / Top view |
| Esc | Select mode 복귀 |

Toolbar 기본 snap은 translation 0.05m, rotation 5도, size 0.05m다. 지원 단위는 코어에서 임의 양수로 검증되며 UI 설정은 scenario가 아니라 editor state에 저장된다. 마우스 drag는 이동 중 preview만 바꾸고 mouse-up에 명령 하나만 쌓는다.

FPS 카메라는 우클릭을 누른 동안만 활성화된다. Open3D `FLY` interactor는 상대 마우스 이동으로 시점을 회전하고, 편집기 제어기는 camera view matrix에서 수평 forward/right를 계산해 실제 m/s 단위로 이동한다. 우클릭을 놓거나 Esc를 누르면 눌린 이동 키를 즉시 지운다. 따라서 평상시 `S`는 기존 Scale 단축키로 유지되고 FPS 중에만 후진이다. 첫 구현은 카메라 높이를 유지하며 중력, floor 추적, 벽 충돌, native cursor lock은 지원하지 않는다.

```yaml
navigation:
  fps:
    enabled: true
    movement_speed_mps: 1.5
    sprint_multiplier: 3.0
    max_frame_delta_seconds: 0.05
    horizontal_only: true
```

## Candidate library

`configs/proxy_editor/pnu_classroom_candidates.yaml`에서 다음 template를 읽는다.

- Desk Cluster
- Blackboard Panel
- Door Panel
- Large Metal Object
- Custom Box
- Custom Thin Panel

Template에는 geometry type/default size, anchor/floor policy, material category, semantic/purpose/confidence가 있다. Thin panel의 size 순서는 Phase 2-B와 동일하게 `X=thickness, Y=width, Z=height`다.

## 경사진 바닥 정책

기존 Phase 2-B 설정은 변경 없이 `anchor_point`로 해석한다.

```yaml
geometry:
  anchor: {mode: floor_at_xy}
  floor_clearance_m: 0.05
```

새 실제 물체 candidate는 선택적 정책을 사용한다.

```yaml
geometry:
  anchor:
    mode: floor_at_xy
    floor_contact_policy:
      type: minimum_bottom_vertex_clearance
      clearance_m: 0.02
```

`minimum_bottom_vertex_clearance`는 회전된 모든 bottom vertex의 XY에서 실제 경사진 floor Z를 계산하고, 가장 낮은 여유가 정확히 설정값이 되도록 Z translation을 정한다. 이후 기존 Phase 2-B validator가 모든 vertex의 floor/ceiling/wall containment를 다시 검사한다.

## 저장, Undo, 복구

- 저장은 schema → 고유 ID → 양수 size → 유한 transform → room containment → clearance → material → coordinate round trip → enabled null 순으로 확인한다.
- Invalid enabled object는 headless 저장을 막는다. Disabled invalid/incomplete object와 collision warning은 보존한다.
- 기존 알 수 없는 YAML field를 가능한 그대로 보존하고 float는 9자리 소수 정밀도로 결정적으로 쓴다.
- Add/Delete/Duplicate/Transform/Resize/Material/Property/Enable command를 지원한다.
- 10개 command 또는 60초마다 `autosave/latest_scenario.yaml`, `latest_editor_state.json`을 쓰며 원본 scenario는 덮어쓰지 않는다.
- Save As는 `scenario.provenance.authoring_method=interactive_proxy_placement`와 미실측 상태를 추가한다.

## Phase 2-B 연결

GUI의 Validate/Build/Run A/B 버튼은 solver를 재구현하지 않고 `tools.sionna_scenario.main`을 별도 worker thread에서 실행한다. 환경은 `configs/proxy_editor/pnu_classroom_editor.yaml`에서 바꾼다.

```yaml
external_commands:
  sionna_environment:
    type: conda
    name: sionna
```

## 출력

```text
outputs/proxy_placement/pnu_classroom/
├─ editor_state.json
├─ scenario_resolved.json
├─ obstacles_metric.json
├─ obstacles_scene.json
├─ obstacle_vertices_metric.csv
├─ obstacle_vertices_scene.csv
├─ placement_validation.json
├─ command_log.json
├─ autosave/
│  ├─ latest_scenario.yaml
│  └─ latest_editor_state.json
└─ preview/
   ├─ top_view.png
   ├─ front_view.png
   ├─ side_view.png
   ├─ perspective_view.png
   ├─ proxy_objects_metric.obj
   ├─ proxy_objects_metric.ply
   ├─ proxy_objects_scene.obj
   └─ placement_report.md
```

## 테스트

```bash
conda run -n pgsr python -m pytest -q --import-mode=importlib \
  tools/proxy_placement_editor/tests \
  tools/sionna_scenario/tests \
  tools/sionna_smoke_test/tests \
  tools/proxy_mesh_editor/tests
```

Display가 있는 환경의 수동 GUI 체크리스트는 검증 문서를 따른다.
