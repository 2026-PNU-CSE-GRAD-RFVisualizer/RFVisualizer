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

Draft scenario의 네 null geometry object는 렌더링하지 않고 모두 `DISABLED_INCOMPLETE`로 표시했으며 전체 검증은 통과했다. 실제 강의실 물체 위치는 자동 생성하지 않았다.

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
| XY drag / yaw drag / mouse scale | 코드/단위 확인 | 실제 장치 입력감은 display 환경에서 필요 |
| RMB drag + WASD FPS camera | 자동·실화면 확인 | XTest로 RMB drag/W/release/Home 전달 후 프로세스·렌더 유지 |
| 축 제한·snap·numeric property | Core 확인 | transform 테스트 |
| Floor snap·invalid red | Core/코드 확인 | 실제 색상 렌더는 display 환경에서 필요 |
| Undo/Redo | Core 확인 | drag 하나당 command 하나 테스트 |
| Save/load round trip | 확인 | synthetic와 draft round trip 테스트 |
| Preview export | 확인 | 실제 출력 이미지 시각 검사 |
| Phase 2-B build 호출 | 확인 | 실제 `sionna` build 성공 |
| Window open/close와 전체 mouse checklist | 창 생성·렌더 확인 | RustDesk `:1`에서 1500×920 창 확인, 실제 mouse 조작감은 수동 확인 필요 |

RustDesk 화면에서 실제 Room/reference가 포함된 전체 편집기 창을 열고 OpenGL renderer 시작과 프로세스 유지를 확인했다. 선택·drag·단축키의 실제 입력감은 사용자가 수동 체크리스트로 확인해야 한다.

## 테스트 결과

- Phase 2-C: 48 passed
- Phase 2-B: 83 passed, 1 skipped
- Phase 2-A: 15 passed, 1 skipped
- Proxy Mesh Editor: 73 passed
- 전체 headless regression: 219 passed, 2 skipped
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
- FPS camera는 수평 이동만 지원하며 중력, floor 추적, 벽 충돌, native cursor lock은 없다.

다음 단계는 현장에서 object ID별 위치, 크기, yaw, 재질 근거와 측정 출처를 기록한 뒤 편집기에 입력하고, 별도 provisional scenario로 저장해 empty/variant Sionna A/B와 실제 RSSI 수집 계획을 연결하는 것이다.
