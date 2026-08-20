# RFVisualizer 통합 Proxy Placement Editor

Metric Room Envelope와 선택적 PGSR 참조 형상을 보면서 문·계단·책상·AP/TX·RX를 한 창에서 배치하고, 기존 Phase 2-B scenario YAML과 실험 TX/RX JSON을 함께 저장하는 Open3D 편집기다.

> **PROVISIONAL GEOMETRY**
>
> 현재 Metric scale과 proxy 배치는 현장 실측으로 검증되지 않았다. Candidate 기본 크기는 UI 편의용 placeholder이며 실측 치수가 아니다. 이 장면의 Sionna 결과를 실제 RSSI 정확도로 해석하면 안 된다.

실제 구현 검증 결과와 수동 UI 미확인 항목은 [PHASE2C_VALIDATION.md](PHASE2C_VALIDATION.md)에 기록한다.

## 설계 원칙

- Scenario YAML이 유일한 RF 장면 정의다. 카메라·패널·선택·표시 상태는 `editor_state.json`에 따로 저장한다.
- `tools/sionna_scenario/`의 obstacle schema, primitive builder, room validator, material resolver와 scene builder를 재사용한다.
- Room OBJ/JSON과 calibration은 읽기 전용으로 열고 SHA-256을 결과에 기록한다. 방 꼭짓점, boolean, 문 opening, calibration은 수정하지 않는다.
- 모든 편집은 meter/+Z Metric 좌표에서 수행한다. 각 obstacle의 Metric/PGSR vertex와 4×4 transform, 왕복 오차를 함께 내보낸다.
- Candidate를 Add하면 구체적인 placeholder geometry는 보이지만 `enabled: false`, `confidence: unset`, `placement_status: provisional_unconfirmed` 상태다. 사용자가 명시적으로 활성화해야 Sionna scene에 들어간다.
- 기존 draft YAML의 null geometry도 GUI에서 semantic class가 candidate 하나와 명확히 대응하면 Room 중심의 `provisional_placeholder`로만 표시한다. 원본 YAML은 명시적으로 저장하기 전까지 바뀌지 않고, placeholder는 계속 비활성·미측정 상태다. Headless `validate`는 null draft를 기존처럼 `DISABLED_INCOMPLETE`로 다룬다.
- Open3D GUI와 독립된 코어를 사용하므로 display server가 없어도 load/transform/validate/save/preview 테스트가 실행된다.

## 환경 선택

`pgsr` 환경의 Open3D 0.19.0 `visualization.gui`와 `SceneWidget`을 사용한다. 이 환경에는 PySide6, VTK, PyVista가 없으므로 새 대형 GUI 의존성을 추가하지 않았다.

```bash
conda run -n pgsr python -c "import open3d; print(open3d.__version__)"
```

Open3D 데스크톱 창에는 X11 또는 Wayland display가 필요하다. Display가 없는 서버에서는 `edit`가 명확한 오류로 종료되고 `validate`, `export-preview`는 계속 사용할 수 있다.

편집기 창은 한국어 전용이다. 제목, 패널, 버튼, 속성, 단축키 도움말, 상태와 검증 메시지는 쉬운 한국어로 표시하고 필요한 전문 용어만 영어를 함께 적는다. YAML key, object ID, enum, material identifier는 Phase 2-B 호환성을 위해 기존 영문 값을 유지한다. Open3D 창을 만들기 전에 시스템의 Noto Sans CJK 또는 NanumGothic 글꼴을 등록해 한글 glyph를 추가한다. 명령행 출력과 생성되는 preview/report의 언어는 변경하지 않는다.

## 명령

### 편집기

```bash
conda run -n pgsr python -m tools.proxy_placement_editor.main edit \
  --room-obj scenes/<scene_id>/proxy_mesh/metric_calibration/room_envelope_metric.obj \
  --room-json scenes/<scene_id>/proxy_mesh/metric_calibration/room_envelope_metric.json \
  --calibration scenes/<scene_id>/proxy_mesh/metric_calibration/calibration.json \
  --scenario scenes/<scene_id>/configs/sionna/proxy_draft.yaml \
  --candidates scenes/<scene_id>/configs/proxy_editor/candidates.yaml \
  --markers scenes/<scene_id>/experiments/<session_id>/configs/tx_rx.json \
  --output scenes/<scene_id>/proxy_placement
```

실제 PGSR Point Cloud와 Output Mesh를 함께 표시하는 예시는 다음과 같다.

```bash
conda run -n pgsr python -m tools.proxy_placement_editor.main edit \
  --room-obj scenes/<scene_id>/proxy_mesh/metric_calibration/room_envelope_metric.obj \
  --room-json scenes/<scene_id>/proxy_mesh/metric_calibration/room_envelope_metric.json \
  --calibration scenes/<scene_id>/proxy_mesh/metric_calibration/calibration.json \
  --scenario scenes/<scene_id>/configs/sionna/proxy_draft.yaml \
  --candidates scenes/<scene_id>/configs/proxy_editor/candidates.yaml \
  --point-cloud PGSR/output/<scene_id>/point_cloud/iteration_30000/point_cloud.ply \
  --point-cloud-coordinate-space scene \
  --pgsr-output-mesh PGSR/output/<scene_id>/mesh/tsdf_fusion_post.ply \
  --pgsr-output-mesh-coordinate-space scene \
  --output scenes/<scene_id>/proxy_placement
```

`--point-cloud`는 PGSR Gaussian PLY의 위치를 최대 50만 점으로 표시하고, `--pgsr-output-mesh`는 실제 삼각형 표면을 별도 계층으로 표시한다. `scene` 입력에는 calibration의 `T_metric_from_scene`을 동일하게 적용한다. 기본 CLI는 약 693만 삼각형의 Output Mesh를 최대 100만 삼각형 캐시로 표시한다. `--pgsr-output-mesh-full-resolution`을 지정하면 캐시를 건너뛰고 원본 Mesh를 그대로 표시한다. 프로젝트의 `scripts/run_scene.py`는 구조 보존을 위해 이 원본 모드를 사용한다. PGSR 원본·scenario·Sionna export는 수정하지 않는다. 이전 `--reference-mesh` 인자는 호환용으로만 유지한다.

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
  --scenario scenes/<scene_id>/configs/sionna/synthetic_blocker.yaml \
  --candidates scenes/<scene_id>/configs/proxy_editor/candidates.yaml \
  --room-json scenes/<scene_id>/proxy_mesh/metric_calibration/room_envelope_metric.json \
  --calibration scenes/<scene_id>/proxy_mesh/metric_calibration/calibration.json \
  --output scenes/<scene_id>/proxy_placement
```

활성 obstacle에 schema 오류, null, non-positive size, NaN/Inf, room 침투, 재질 오류, 좌표 왕복 오류가 있으면 exit code 2다. 비활성 draft의 null geometry는 `DISABLED_INCOMPLETE`로 기록하고 전체 검증은 통과한다. AABB 충돌과 벽 근접은 warning이며 저장을 막지 않는다.

### 미리보기

```bash
conda run -n pgsr python -m tools.proxy_placement_editor.main export-preview \
  --scenario scenes/<scene_id>/configs/sionna/synthetic_blocker.yaml \
  --candidates scenes/<scene_id>/configs/proxy_editor/candidates.yaml \
  --point-cloud PGSR/output/<scene_id>/point_cloud/iteration_30000/point_cloud.ply \
  --pgsr-output-mesh PGSR/output/<scene_id>/mesh/tsdf_fusion_post.ply \
  --output scenes/<scene_id>/proxy_placement/preview
```

`--exclude-reference`를 추가하면 PNG에서 두 PGSR 계층을 제외한다.

## 화면과 상호작용

중앙 Viewport는 Point Cloud, 불투명 Proxy Mesh(Room Envelope), 불투명 PGSR Output Mesh, 경사진 floor grid, 유효/무효/비활성 obstacle을 서로 다른 geometry layer로 표시한다. 세 배경 계층은 picking 대상이 아니며 겹친 obstacle 중 광선의 가장 가까운 triangle hit가 선택된다. 선택한 객체의 변형 gizmo는 화살표·회전 링·크기 박스 자체를 화면 투영은 유지한 채 camera near plane 바로 뒤에 다시 만들어 깊이 가림을 우회한다. 카메라가 움직이면 이 실제 3D handle도 갱신하며, 혼동을 주는 상시 world-origin 축과 별도 색상 표식은 표시하지 않는다. 오른쪽에는 큰 제목과 구분선으로 나눈 Candidate, Object List, Identity/Geometry/Transform/Material 속성, 실시간 clearance·collision·좌표 검증, 외부 명령 로그가 있다.

상단에는 `Point Cloud`, `Proxy Mesh`, `PGSR Output Mesh` 체크박스가 따로 있다. 세 항목을 독립적으로 체크하거나 해제할 수 있어 0개부터 3개까지 원하는 조합으로 중첩 표시한다. 여기서 Proxy Mesh는 Room Envelope를 뜻하며 배치된 obstacle과 선택 gizmo는 체크 상태와 무관하게 유지된다. Proxy Mesh는 밝은 청회색 불투명 재질, PGSR Output Mesh는 원본 정점색을 보존하는 불투명 재질로 표시한다. 두 기준 계층은 조명 방향에 따라 어두워지지 않도록 비조명 셰이더를 사용한다. `점 크기` 슬라이더는 Point Cloud에만 적용되며 1–12px 범위에서 material만 갱신한다.

| 입력 | 동작 |
|---|---|
| 왼쪽 클릭 | 가장 가까운 obstacle 선택; 변형 모드에서 gizmo 보호 영역 바깥의 빈 공간/선택 객체 본체 drag는 카메라 회전 |
| 객체 목록에서 Ctrl+클릭 | 기존 선택을 유지한 채 객체를 추가하거나 제외; `●`는 대표 객체, `✓`는 함께 선택된 객체 |
| 우클릭 드래그 + `W/A/S/D` | FPS 시점 회전 + 카메라 시선 기준 전후좌우 이동 |
| 우클릭 + Shift | FPS 이동 속도 증가 |
| Alt+왼쪽 / Ctrl+왼쪽 / 가운데 드래그 / Wheel | Open3D Orbit / Pan / Pan / Zoom |
| `G` + X/Y/Z 축 drag | 선택한 World/Local 축 방향 이동; `floor_at_xy` Z축은 바닥 clearance 변경 |
| `R` + X/Y/Z 회전 링 drag | 선택한 World/Local 축 중심 회전 |
| `S` + X/Y/Z 축 drag | Phase 2-B 호환 로컬 크기 축 한 방향 조절 |
| 상단 World/Local | 이동·회전 gizmo 좌표계 전환; 크기 조절은 항상 Local |
| Shift / gizmo drag 도중 Ctrl | 미세 조작 / grid snap |
| `F`, Home | 선택 object / 전체 room frame |
| Delete, Ctrl+D | 삭제 / 비활성 복제 |
| Ctrl+Z, Ctrl+Y, Ctrl+Shift+Z | Undo / Redo |
| Ctrl+S | 전체 검증 후 저장 |
| `H` | 선택 object 표시 전환; 배경은 상단의 세 체크박스로 독립 전환 |
| `1`, `3`, `7` | Front / Side / Top view |
| Esc | Select mode 복귀 |

Toolbar 기본 snap은 translation 0.05m, rotation 5도, size 0.05m다. 지원 단위는 코어에서 임의 양수로 검증되며 World/Local, 배경 모드, 점 크기를 포함한 UI 설정은 scenario가 아니라 editor state에 저장된다. 여러 객체를 선택하면 결합 경계상자 중심에 World 축 gizmo 하나를 표시한다. 이동은 같은 변위를 적용하고, 회전·크기 조절은 각 객체 자체 변형과 그룹 중심으로부터의 위치 변화를 함께 적용한다. 이때 RX 점도 그룹 내 위치 변환에는 참여한다. 마우스 drag 중에는 선택 객체와 gizmo만 다시 만들고, 전체 장면 검증과 다른 객체 갱신은 mouse-up에 한 번만 수행한다. Mouse-up에는 선택 개수와 무관하게 명령 하나만 쌓인다. Gizmo handle은 화면 기준 22px 범위에서 선택하고, 그 바깥 34px까지는 좁게 빗나간 클릭이 다른 객체 선택이나 카메라 조작으로 전달되지 않게 막는다. 이동·크기는 화면에 투영된 축 방향의 mouse 이동을 실제 거리로 환산하고, 회전은 선택한 링의 화면상 접선 방향 이동을 각도로 환산한다. Gizmo drag 중에는 SceneWidget을 `PICK_POINTS` 제어로 전환해 mouse capture는 유지하면서 카메라 회전은 막고, mouse-up에 `ROTATE_CAMERA`로 복구한다.

일반 편집 단축키는 Viewport에만 연결한다. 따라서 TextEdit/NumberEdit에 포커스가 있을 때 화살표, Backspace, Delete 등의 편집 키는 입력창이 직접 처리한다. Open3D 0.18은 ImGui 입력창이 활성화된 동안 Window와 SceneWidget key callback을 모두 건너뛰므로, Linux/X11·XWayland에서는 우클릭 FPS 중 로컬 키보드의 `XQueryKeymap` 상태와 XInput2 raw key event를 함께 읽는다. RustDesk 1.4.9가 키를 누른 상태 대신 즉시 Press/Release 펄스로 반복 전송하면, 실측 반복 간격보다 긴 180ms 유지 창을 반복 Press로 갱신해 연속 입력으로 복원한다. FPS 중에는 활성 속성 입력을 잠그고 우클릭을 놓을 때 상태 값으로 다시 표시해, 이동 키가 기존 입력값에 섞이지 않게 한다. XInput2를 사용할 수 없으면 로컬 keymap polling을 유지하고, X11 poller도 사용할 수 없는 환경에서는 기존 Window/Viewport callback을 fallback으로 유지한다. 우클릭 DRAG 이벤트의 버튼 bit가 비어 있어도 이동 상태를 유지하고 실제 `BUTTON_UP`에서만 종료한다. Ctrl+왼쪽 drag도 객체 선택보다 먼저 Open3D에 넘겨 카메라 평행 이동을 보존한다.

오른쪽 섹션의 구분선은 box-drawing 문자를 쓰지 않는다. Open3D fallback font에서 `?`로 표시되지 않도록 2px 높이의 배경색 layout으로 그린다.

FPS 카메라는 우클릭을 누른 동안만 활성화된다. 상대 마우스 회전은 Open3D `FLY` interactor가 처리하고, `W/S`는 카메라가 실제로 바라보는 3차원 방향의 앞뒤로, `A/D`는 카메라의 좌우 방향으로 매 tick 이동한다. 아래를 보며 W를 누르면 전진하면서 내려가고 위를 보면 올라간다. `horizontal_only: true`로 바꾸면 높이를 고정한 예전 수평 이동을 사용할 수 있으며, 이 모드에서는 수직 시점의 미세한 행렬 오차가 이동 방향을 뒤집지 않도록 안정된 수평 방향을 유지한다. Shift는 설정된 배율만큼 속도를 높인다. 우클릭을 놓으면 입력 상태를 지우고 다음 tick에 일반 회전 제어로 복구한다. 따라서 평상시 `S`는 기존 Scale 단축키로 유지되고 FPS 중에만 후진이다. 첫 구현은 중력, floor 추적, 벽 충돌, native cursor lock을 지원하지 않는다.

### 한국어 UI 수동 확인

화면이 있는 환경에서는 다음 항목을 확인한다.

- 창 제목과 모든 패널·버튼·단축키 설명이 한글로 표시되고 네모 글자가 없는지 확인한다.
- 오른쪽 패널을 기본 폭과 최소 사용 폭에서 열어 긴 문구가 기능을 구분하기 어려울 정도로 잘리지 않는지 확인한다.
- 한국어로 표시된 확신도·형상·기준점·바닥 정책·재질을 변경한 뒤 저장한 YAML에는 기존 영문 enum이 기록되는지 확인한다.
- 유효·경고·오류·비활성 상태와 저장 차단 대화상자가 한국어로 표시되는지 확인한다.

```yaml
reference:
  point_size: 2.0
  point_cloud_visible: true
  proxy_mesh_visible: true
  pgsr_output_mesh_visible: true
navigation:
  fps:
    enabled: true
    movement_speed_mps: 1.5
    sprint_multiplier: 3.0
    max_frame_delta_seconds: 0.05
    horizontal_only: false  # false: 카메라 시선 방향, true: 높이 고정 수평 이동
```

## Candidate library

`scenes/<scene_id>/configs/proxy_editor/candidates.yaml`에서 다음 template를 읽는다.

- Desk Cluster
- Blackboard Panel
- Door Panel
- Stair Step
- AP / TX
- Large Metal Object
- Custom Box
- Custom Thin Panel

Candidate 패널의 `보정 RX 추가`와 `Test RX 추가`는 크기가 없는 측정점을 만든다. RX는 이동 기즈모와 숫자 X/Y/Z 입력을 지원하고, 물리 객체가 아니므로 회전·크기 조절과 Sionna 장애물 활성화는 지원하지 않는다. AP/TX는 하나의 물리 객체이며 일반 장애물 변형 기즈모와 송신 주파수·세기 속성을 함께 사용한다.

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

GUI의 Validate/Build/Run A/B 버튼은 solver를 재구현하지 않고 `tools.sionna_scenario.main`을 별도 worker thread에서 실행한다. 환경은 `scenes/<scene_id>/configs/proxy_editor/editor.yaml`에서 바꾼다.

```yaml
external_commands:
  sionna_environment:
    type: conda
    name: sionna
```

## 출력

```text
scenes/<scene_id>/proxy_placement/
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
