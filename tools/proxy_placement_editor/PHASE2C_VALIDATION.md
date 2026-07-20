# RFVisualizer Phase 2-C 검증 기록

## 한 줄 결론

기존 Phase 2-B schema와 builder를 재사용하는 Proxy Placement Editor의 코어·GUI 코드를 구현했고, synthetic blocker round trip·Metric/PGSR 좌표·headless preview·실제 Sionna build를 검증했다. RustDesk의 GNOME Wayland/XWayland에서는 편집기 전용 Open3D 0.18 CPU runtime으로 창 생성을 검증했다.

## 기준 저장소와 환경

- 기준 commit: `023b5c537b0c16cf49b36710cd289fb964367a42`
- OS: Linux 6.17.0-35-generic x86_64
- Core/GUI Python: 3.8.20 (`pgsr`)
- PGSR Open3D: CUDA Open3D 0.19.0
- 편집기 GUI runtime: `open3d-cpu==0.18.0` `visualization.gui.SceneWidget`
- 대안 의존성: PySide6, VTK, PyVista 모두 미설치
- GPU: NVIDIA GeForce RTX 4090, driver 595.71.05
- 원격 Display: GNOME Wayland + XWayland `:1`, RustDesk
- Sionna build: 별도 `sionna` conda 환경

Open3D는 기존 환경에 설치되어 있고 headless core와 GUI import를 분리할 수 있어 선택했다. PGSR용 0.19는 유지하고, git에서 제외한 `.venv/proxy-placement-editor`에서 0.18 CPU GUI만 분리 실행한다.

## GUI 시작 segmentation fault 조치

실제 `tsdf_fusion_post.ply`는 정점 3,666,424개와 삼각형 6,933,784개를 포함한다. 기존 로더는 전체 triangle mesh를 읽고 Open3D quadric decimation을 실행해 최대 RSS 약 4.3GB와 약 55초를 사용했다. 이 네이티브 연산과 이후 GPU GUI 초기화는 Python 예외로 복구할 수 없는 segmentation fault 위험이 있었다.

수정 후 PLY header에서 크기를 먼저 확인하고, 기준을 넘는 mesh는 face를 읽거나 단순화하지 않고 vertex/color만 읽어 최대 500,000점의 표시 전용 point cloud로 축약한다. 동일 파일 실측은 약 1.0초, 최대 RSS 약 0.64GB였다.

RustDesk 세션에서 빈 Open3D 0.19 창도 `Application.create_window()`의 `XSendEvent()`에서 signal 11로 종료됨을 GDB로 확인했다. 공식 `open3d-cpu==0.19.0`도 같은 반면 0.18.0은 동일 XWayland 화면에서 창 생성과 렌더 tick을 통과했다. 이에 `setup-gui-runtime`이 `pgsr` package를 공유하는 얇은 0.18 CPU venv를 만들고, `edit` supervisor가 이를 우선 사용하도록 변경했다. PGSR의 Open3D 설치는 수정하지 않았다.

## 입력 보존

| 입력 | SHA-256 |
|---|---|
| `room_envelope_metric.obj` | `dd3da1aba1d057b3a24fbf8cba063e649952d95c2194551ea1266e86c241fe50` |
| `room_envelope_metric.json` | `bbebc55117e6498353ba7bfad35db7e2df19ca5cebea6b47994f2790b1ad820b` |
| `calibration.json` | `829c435f5dbe9728108433f510f5d0052a2f246d601bbf7525755c7cffd39515` |
| `tsdf_fusion_post.ply` | `233fd4adeeb441789aabedee55b85eabab3c96ba5f6a0eff32394a371da9494e` |

Room/calibration/TSDF 원본은 수정하지 않았다. Reference mesh는 화면 표시용으로만 축약하고 scene→metric 변환했다.

## Synthetic blocker round trip

`configs/sionna/scenarios/pnu_classroom_synthetic_blocker.yaml`을 편집기 코어로 load/validate/export했다.

| 항목 | 결과 |
|---|---|
| 크기 | 0.15 × 2.5 × 2.0m |
| Metric bounds min | `[-5.075, -6.25, 0.2598064196869294]` |
| Metric bounds max | `[-4.925, -3.75, 2.2598064196869294]` |
| Material | wood |
| 최소 floor clearance | 0.011491880954898559m |
| 최소 ceiling clearance | 0.1414630897300384m |
| 최소 wall clearance | 3.476478973679518m |
| `rx_los` triangle 교차 | true, 2 hits |
| 최대 Metric↔scene 왕복 오차 | 1.9860273225978185e-15 |
| 전체 상태 | VALID |

기존 YAML에는 새 floor policy를 쓰지 않았으므로 기존 `anchor_point + floor_clearance_m=0.05` 결과가 그대로 유지된다. 새 `minimum_bottom_vertex_clearance` 단위 테스트는 yaw 31도에서도 설정한 0.02m와 1e-9m 이내로 일치했다.

Headless 검증에서 Draft scenario의 네 null geometry object는 렌더링하지 않고 모두 `DISABLED_INCOMPLETE`로 표시하며 전체 검증은 통과한다. GUI를 열 때만 semantic class가 candidate 하나와 명확히 대응하는 네 객체에 Room 중심의 비활성 `provisional_placeholder`를 채워 처음부터 보이게 한다. 이는 실제 강의실 위치 추정이 아니며 원본 YAML은 사용자가 저장하기 전까지 수정하지 않는다.

## 후속 편집기 버그 수정과 gizmo 검증

- 일반 편집 단축키는 Viewport에만 연결하고 Window callback은 평상시에 `False`를 반환해 TextEdit/NumberEdit의 화살표·Backspace·Delete 입력을 보존했다.
- 이동·회전·크기 모드에서 객체 본체나 빈 화면을 drag해도 변형을 시작하지 않는다. X/Y/Z gizmo handle을 선택한 이벤트만 소비하므로 Open3D 카메라 회전과 객체 변형이 동시에 실행되지 않는다.
- 이동·회전은 World/Local 전환을 지원한다. Phase 2-B primitive에 shear를 만들지 않도록 크기 조절은 항상 local XYZ dimension을 변경한다.
- drag frame마다 선택 obstacle과 gizmo만 다시 만들고 전체 validation, 다른 obstacle, Room/reference 갱신을 mouse-up까지 미뤄 대형 장면의 반복 작업을 제거했다.
- 배경은 Point Cloud/Room Proxy Mesh/둘 다를 전환한다. 장애물과 gizmo는 항상 유지하며 Point Cloud는 개수 대신 material point size만 바꾼다.
- 새 gizmo 수학, 입력 routing, World/Local 회전, draft placeholder, editor display config를 display 없이 단위 검증했다. 새 gizmo의 실제 클릭 영역과 조작감은 화면 세션에서 수동 확인해야 한다.

## 후속 실제 UI 제보 반영

- 우클릭 회전 중 Open3D DRAG event에 right-button bit가 없으면 FPS를 종료하던 조건을 제거하고 `BUTTON_UP`에서만 종료한다. Tick에서는 카메라 방향 기반 이동 계산을 한 번만 적용한다.
- Ctrl+왼쪽 drag는 객체 선택과 gizmo 판정보다 먼저 Open3D 카메라에 넘겨 평행 이동을 복구했다. Gizmo drag가 시작된 뒤 Ctrl을 누르는 동작은 기존 snap 용도로 유지한다.
- 글꼴 atlas에 없는 `━` 문자를 사용하던 구분선을 2px 배경색 layout으로 교체해 `???` 표기를 제거했다.
- Gizmo 선택을 world-space 거리만으로 판정하지 않고 14px screen-space picking으로 우선 판정한다. Mouse-down에서는 `PICK_POINTS` 제어로 SceneWidget mouse capture를 유지하고, 이동·크기 조절은 투영된 축의 pixel 이동을 meter로 환산한다. 회전은 camera ray와 평면의 각도에 의존하지 않고 화면에 투영된 링의 접선 방향 이동을 각도로 환산한다.
- 초기 top-down 카메라에서는 수평 forward가 사실상 0인데 `1e-9`보다 큰 행렬 오차를 정규화해 W 방향이 프레임마다 반전됐다. 수평 성분이 `1e-3` 미만이면 camera right와 직전의 안정된 heading을 사용하고 A/D도 그 heading에 직교하도록 계산한다.
- Open3D 0.18의 `Window::OnKeyEvent`는 ImGui `ActiveId != 0`이면 Window callback과 focused SceneWidget key dispatch를 모두 건너뛴다. TextEdit를 활성화한 뒤 우클릭한 실제 최소 창에서도 mouse event만 들어오고 key callback은 0회였다. `set_focus_widget`은 이 ImGui ID를 해제하지 않는다.
- Linux/X11·XWayland에서는 FPS active 동안 로컬 키보드의 `XQueryKeymap` 상태와 XInput2 raw key event를 결합해 ImGui focus와 독립적으로 W/A/S/D·Shift 상태를 갱신한다. XInput2를 사용할 수 없으면 local keymap polling, X11도 사용할 수 없으면 기존 Window/Viewport callback을 유지한다.
- RustDesk 1.4.9 실측에서는 W keycode 25가 약 30~45ms 간격으로 반복됐고 각 Press/Release는 동일 timestamp였다. 즉시 release는 120ms 유지 펄스로 해석하고 반복 Press가 들어올 때마다 갱신해 원격 Hold를 복원한다. 일반 키보드의 지속 keymap 상태와 시간차가 있는 실제 release는 기존 방식대로 즉시 반영한다.
- FPS 진입 시 속성 입력을 임시로 잠그고 종료 시 공유 상태에서 다시 읽어 표시하므로, native poll로 감지한 이동 키가 기존 TextEdit 값에 섞여 저장되지 않는다.
- 자동 테스트는 right-button bit 없는 DRAG 중 FPS 유지, Window/Viewport key capture, X11 bitmap decode와 callback 없는 native key polling, RustDesk 즉시 Press/Release 펄스 유지·만료, 일반 키보드 release, FPS 시작 시 이전 펄스 초기화, FPS 중 속성 입력 잠금·복원, tick 카메라 이동, 수직 시점의 부호 반전 방지, Ctrl 카메라 평행 이동 통과, 글리프 없는 divider, screen-space gizmo picking, 실제 draft object의 90도 회전과 이동 gizmo drag, camera control 복구, drag 중 전체 validation 미호출을 포함한다.
- XWayland `:1`과 편집기 전용 Open3D 0.18 runtime에서 실제 창을 열고 W를 1초간 입력했다. 수정 전에는 이동 부호가 반복 반전됐고, 수정 후에는 89개 frame이 모두 `+Y`였으며 누적 이동은 1.49008m였다.
- 활성 TextEdit를 의도적으로 유지한 실제 편집기 창에서는 Open3D key callback이 한 번도 호출되지 않았지만, X11 poller가 W를 감지해 54개 frame 연속 동일 방향의 이동을 적용했다.
- 후속 조작 요구에 따라 기본 `horizontal_only`를 `false`로 바꿨다. W/S는 카메라의 pitch를 포함한 실제 시선 벡터를 따르며, 기존 수평 방향 안정화는 설정을 `true`로 선택할 때만 적용한다.

## Preview와 Phase 2-B 연결

실제 존재하는 `PGSR/output/pnu_classroom/mesh/tsdf_fusion_post.ply`를 scene 좌표 reference로 사용해 top/front/side/perspective PNG와 Metric/scene OBJ/PLY를 생성했다. 방, reference, blocker의 정렬과 +Z 높이, 경사진 floor 접촉을 이미지로 확인했다.

기존 Phase 2-B 빌드도 별도 `sionna` 환경에서 성공했다.

```text
scenario_id: pnu_classroom_synthetic_blocker
room_object_count: 6
obstacle_object_count: 1
total_triangle_count: 24
material_resolution: verified_with_installed_sionna
```

TensorFlow는 cuDNN library 문제로 GPU를 등록하지 못했다는 기존 환경 경고를 냈지만, 이번 명령의 실제 Sionna scene load와 material resolution은 성공했다.

## 수동 UI 체크리스트

| 항목 | 상태 | 근거 또는 남은 확인 |
|---|---|---|
| Room 방향·크기, +Z, floor slope | Headless 확인 | 네 방향 preview와 수치 검증 |
| Candidate add, disabled 기본값 | Core 확인 | 통합 테스트 |
| Object List와 selection 동기화 | 코드/단위 확인 | 실제 창 클릭은 display 환경에서 필요 |
| Viewport ray selection | 수학 단위 확인 | 가장 가까운 triangle 선택, room layer 제외 |
| XYZ 이동 gizmo / XYZ 회전 링 / local scale gizmo | 수학·입력 routing 확인 | 새 handle의 실제 클릭 영역과 조작감은 display 환경에서 필요 |
| R/S 중 빈 화면 카메라 drag 분리 | 자동 확인 | gizmo가 없으면 이벤트를 소비하지 않는 회귀 테스트 |
| 텍스트 입력 화살표·Backspace·Delete | 코드·routing 확인 | 평상시 Window callback 통과와 Viewport 전용 shortcut, 실제 입력감은 display 환경에서 필요 |
| Point 크기와 Point Cloud/Proxy Mesh/둘 다 | 설정·API 확인 | Open3D 0.18/0.19 API 확인, 실제 화면 비교 필요 |
| RMB drag + WASD FPS camera | 자동·실제 창 확인 | 수직 시점 89 frame 순이동, 활성 TextEdit 상태에서도 native poll 54 frame 이동 |
| Ctrl+왼쪽 camera pan | 자동 routing 확인 | 객체 선택보다 먼저 native camera에 넘김, 실제 이동감은 display 환경에서 재확인 필요 |
| Gizmo drag 중 camera lock | 자동 routing 확인 | mouse-down 뒤 DRAG/UP을 소비하고 PICK_POINTS 제어 유지 |
| Gizmo drag 성능 | 자동 구조 확인 | 선택 객체만 preview build, 전체 validation은 mouse-up에서 1회 |
| 축 제한·snap·numeric property | Core 확인 | transform 테스트 |
| Floor snap·invalid red | Core/코드 확인 | 실제 색상 렌더는 display 환경에서 필요 |
| Undo/Redo | Core 확인 | drag 하나당 command 하나 테스트 |
| Save/load round trip | 확인 | synthetic와 draft round trip 테스트 |
| Preview export | 확인 | 실제 출력 이미지 시각 검사 |
| Phase 2-B build 호출 | 확인 | 실제 `sionna` build 성공 |
| Window open/close와 전체 mouse checklist | 창 생성·렌더 확인 | RustDesk `:1`에서 1500×920 창 확인, 실제 mouse 조작감은 수동 확인 필요 |

RustDesk 화면에서 실제 Room/reference가 포함된 전체 편집기 창을 열고 OpenGL renderer 시작과 프로세스 유지를 확인했다. 선택·drag·단축키의 실제 입력감은 사용자가 수동 체크리스트로 확인해야 한다.

## 테스트 결과

- Phase 2-C: 95 passed
- Phase 2-B: 83 passed, 1 skipped
- Phase 2-A: 15 passed, 1 skipped
- Proxy Mesh Editor: 73 passed
- 전체 headless regression: 266 passed, 2 skipped
- Phase 2-B 실제 Sionna integration: 84 passed
- Phase 2-A 실제 Sionna integration: 1 passed
- 정적 검사: Ruff 통과
- whitespace 검사: `git diff --check` 통과

Skipped 항목은 실제 display/Sionna 통합처럼 명시적 환경 변수가 필요한 기존 테스트다. 최종 통합 수치는 완료 시 다시 확인한다.

## 현재 한계와 다음 입력

- Calibration scale은 사진 추정 기반 provisional이다.
- 실제 책상·칠판·문·금속 구조물의 위치·크기·방향은 아직 측정하지 않았다.
- RF material은 실제 RSSI로 보정하지 않았다.
- AABB overlap은 warning만 제공하며 정밀 OBB/mesh collision은 구현하지 않았다.
- External mesh의 직접 transform gizmo는 MVP 범위에서 행렬 입력을 사용한다.
- 실제 GUI 창과 렌더는 확인했으며, 마우스 drag와 단축키 입력감은 수동 검증이 남아 있다.
- FPS camera는 시선 기준 자유 이동을 지원하지만 중력, floor 추적, 벽 충돌, native cursor lock은 없다.

다음 단계는 현장에서 object ID별 위치, 크기, yaw, 재질 근거와 측정 출처를 기록한 뒤 편집기에 입력하고, 별도 provisional scenario로 저장해 empty/variant Sionna A/B와 실제 RSSI 수집 계획을 연결하는 것이다.
