# Sionna RT Obstacle Scenario & A/B Validation

Phase 2-B 도구는 Phase 2-A의 미터 단위 Room Envelope를 그대로 두고, 장애물을 독립 `proxy_obstacle` shape로 추가해 Empty Room과 obstacle variant를 같은 조건에서 비교한다.

> **현재 결과의 의미**
>
> 이 단계의 blocker는 `purpose=validation_only`, `physical_object=false`, `confidence=synthetic`인 검증용 형상이다. 좌표 배율과 RF 재질도 `provisional`, `physically_validated=false`다. 결과는 장애물 계층과 Sionna RT A/B 파이프라인이 동작한다는 근거이지, 실제 물체 배치나 RSSI 정확도를 뜻하지 않는다.

실제 Sionna 1.2.2 실행 결과는 [PHASE2B_VALIDATION.md](PHASE2B_VALIDATION.md)에 기록한다. 기반 Empty-Room 도구와 결과는 [Phase 2-A README](../sionna_smoke_test/README.md)와 [검증 문서](../sionna_smoke_test/PHASE2A_SMOKE_TEST_VALIDATION.md)를 참고한다.

Phase 2-C의 대화형 배치 UI는 이 schema를 새로 만들지 않고 그대로 편집한다. 사용법과 검증 상태는 [Proxy Placement Editor README](../proxy_placement_editor/README.md)를 참고한다.

## 보존하는 기준

- `room_envelope_metric.obj`와 Phase 2-A 설정을 수정하지 않는다.
- Room Envelope와 각 obstacle은 `merge_shapes=false`인 독립 shape다.
- Metric Calibration과 provisional scale을 다시 계산하지 않는다.
- Empty와 variant는 같은 Room 입력, TX/RX, antenna, solver 설정, seed, coverage grid를 사용한다.
- 실제 책상·칠판·문·대형 금속 물체 예시는 기본적으로 `enabled: false`이며 위치와 치수를 추정해 채우지 않는다.
- 기존 `scenes/<scene_id>/sionna/smoke_test/`를 덮어쓰지 않고 Phase 2-B 전용 출력 폴더를 사용한다.

## 환경

Phase 2-A와 같은 Sionna 전용 환경을 사용한다.

```bash
conda create -n sionna python=3.10
conda activate sionna
python -m pip install -r tools/sionna_smoke_test/requirements-sionna.txt
```

명령은 저장소 루트에서 실행한다. Scenario/experiment의 project 경로는 저장소 루트를 기준으로 하고, external mesh의 상대 `path`는 scenario YAML 폴더를 기준으로 한다. 실제 검증 환경은 Python 3.10.20, Sionna RT 1.2.2, Mitsuba 3.8.0, Dr.Jit 1.3.1이었다.

## 명령

Scenario schema, 미터 장면, 장애물 형상, Room containment, TX/RX 및 필수 LoS 교차를 검증한다. 결과 JSON은 표준 출력으로만 내보낸다.

```bash
conda run -n sionna python -m tools.sionna_scenario.main validate \
  --scenario scenes/<scene_id>/configs/sionna/synthetic_blocker.yaml
```

Room과 obstacle을 독립 PLY/Mitsuba shape로 구성하고 manifest와 좌표 변환 파일을 만든다. Path/Coverage solver는 실행하지 않지만, Sionna 환경이 사용 가능하면 장면을 실제로 load해 runtime object ID와 재질 등록을 검증한다. Sionna가 없으면 runtime 검증은 명시적으로 deferred 상태가 된다.

```bash
conda run -n sionna python -m tools.sionna_scenario.main build \
  --scenario scenes/<scene_id>/configs/sionna/synthetic_blocker.yaml \
  --output scenes/<scene_id>/sionna/phase2b/scenarios/synthetic_blocker
```

Empty baseline을 같은 seed로 두 번 실행한 뒤 synthetic blocker variant를 실행하고 경로와 Coverage를 비교한다.

```bash
conda run -n sionna python -m tools.sionna_scenario.main run-ab \
  --experiment scenes/<scene_id>/configs/sionna/phase2b_ab_experiment.yaml \
  --output scenes/<scene_id>/sionna/phase2b/experiments/synthetic_blocker_ab
```

`--verbose`는 하위 명령 앞에 둔다.

```bash
conda run -n sionna python -m tools.sionna_scenario.main --verbose validate \
  --scenario scenes/<scene_id>/configs/sionna/synthetic_blocker.yaml
```

기본 제공 설정은 다음 세 scenario와 한 A/B experiment다.

- `scenes/<scene_id>/configs/sionna/empty.yaml`: obstacle이 없는 Phase 2-A Room
- `scenes/<scene_id>/configs/sionna/synthetic_blocker.yaml`: 실제 실행용 synthetic blocker
- `scenes/<scene_id>/configs/sionna/proxy_draft.yaml`: 실제 물체 정보를 나중에 입력할 비활성 template
- `scenes/<scene_id>/configs/sionna/phase2b_ab_experiment.yaml`: Empty 대 synthetic blocker 비교

## Scenario schema

문서 최상위 구조는 다음과 같다.

```yaml
schema_version: "1.0"

scenario:
  id: example_scenario
  status: provisional
  physically_validated: false
  synthetic_validation: false

  base_scene:
    phase2a_config: scenes/<scene_id>/configs/sionna/smoke_test.yaml

  obstacles: []
```

`status`는 반드시 `provisional`, `physically_validated`는 반드시 `false`여야 한다. `synthetic_validation: true`인 scenario에는 활성 `validation_only` obstacle이 하나 이상 필요하다.

### Obstacle 공통 필드

```yaml
- id: blocker_panel_000
  enabled: true
  semantic_class: validation_blocker
  purpose: validation_only
  physical_object: false
  confidence: synthetic

  geometry: ...
  material: ...

  export:
    object_name: blocker_panel_000
    group_name: obstacle_validation
```

- `id`와 `export.object_name`은 scenario 안에서 각각 고유해야 한다.
- `validation_only`이면 `physical_object: false`, `confidence: synthetic` 조합을 강제한다.
- `export`는 선택 사항이며 기본 object 이름은 `id`, group 이름은 `semantic_class`다.
- 비활성 draft도 공통 metadata, `geometry` mapping, `material` mapping은 유지한다. 단, `position_m`, `size_m`, `rotation_deg` 같은 측정 전 값은 `null`이어도 된다. 같은 항목을 활성화하면 누락값은 즉시 오류다.

### Geometry

지원 형식은 `box`, `thin_panel`, `mesh`다.

Box:

```yaml
geometry:
  type: box
  anchor:
    mode: floor_at_xy
  position_m: {x: -5.0, y: -5.0}
  size_m: {x: 0.15, y: 2.5, z: 2.0}
  rotation_deg: {roll: 0.0, pitch: 0.0, yaw: 0.0}
  floor_clearance_m: 0.05
```

Thin panel은 닫힌 얇은 box로 생성되며 로컬 축은 `X=thickness`, `Y=width`, `Z=height`다. `size_m` mapping 또는 세 개의 개별 길이를 사용할 수 있다.

```yaml
geometry:
  type: thin_panel
  anchor: {mode: bottom_center}
  position_m: {x: 0.0, y: 0.0, z: 0.5}
  size_m: {thickness: 0.05, width: 3.0, height: 1.2}
  rotation_deg: {roll: 0.0, pitch: 0.0, yaw: 90.0}
```

```yaml
geometry:
  type: thin_panel
  thickness_m: 0.05
  width_m: 3.0
  height_m: 1.2
  # anchor, position_m, rotation_deg도 함께 지정
```

External mesh interface는 OBJ와 ASCII PLY만 읽으며 polygon face는 삼각형으로 나눈다. 바이너리 PLY, STL과 일반 mesh 편집은 지원하지 않는다. 상대 `path`는 scenario YAML이 있는 폴더를 기준으로 해석한다.

```yaml
geometry:
  type: mesh
  path: meshes/cabinet.obj
  anchor: {mode: explicit_transform}
  transform:
    - [1.0, 0.0, 0.0, 1.0]
    - [0.0, 1.0, 0.0, 2.0]
    - [0.0, 0.0, 1.0, 0.5]
    - [0.0, 0.0, 0.0, 1.0]
```

모든 길이와 좌표는 유한해야 하고 primitive 길이는 양수여야 한다. 회전은 degree 단위의 roll/pitch/yaw이며 `Rz(yaw) @ Ry(pitch) @ Rx(roll)` 순서로 적용한다.

### Anchor mode

| mode | `position_m` | 의미 |
|---|---|---|
| `center` | XYZ | 로컬 bounds 중심을 지정한 위치에 둔다. |
| `bottom_center` | XYZ | 로컬 bounds 바닥 중심을 지정한 위치에 둔다. |
| `floor_at_xy` | XY 또는 XYZ | 해당 XY에서 Room floor plane의 Z를 계산하고 `floor_clearance_m`를 더해 바닥 중심을 둔다. 입력 Z는 사용하지 않는다. |
| `explicit_transform` | 없음 | 유한하고 가역인 4×4 affine matrix를 직접 사용한다. 마지막 행은 `[0,0,0,1]`이어야 한다. |

`explicit_transform`은 `position_m` 또는 0이 아닌 `rotation_deg`와 함께 사용할 수 없다. `floor_at_xy`는 중심점의 floor Z를 해결하지만, 경사진 바닥에서 회전하거나 넓은 장애물의 모서리가 바닥 아래로 들어갈 수 있다. 그래서 anchor 계산 뒤 모든 vertex의 floor, ceiling, wall clearance를 다시 검사한다.

Phase 2-C는 backward compatibility를 유지하면서 선택적 `floor_contact_policy`를 추가한다. 기존 설정은 `anchor_point`로 해석한다. `minimum_bottom_vertex_clearance`는 회전된 모든 bottom vertex 위치에서 경사진 바닥을 계산해 최소 여유가 `clearance_m`가 되도록 배치한다.

```yaml
anchor:
  mode: floor_at_xy
  floor_contact_policy:
    type: minimum_bottom_vertex_clearance
    clearance_m: 0.02
```

### Material

```yaml
material:
  source: sionna_preset
  category: wood
  thickness_m: 0.1
  scattering_coefficient: 0.0
```

지원 category는 `concrete`, `wood`, `metal`, `glass`다. 현재 source는 `sionna_preset`만 지원한다. 각 장애물은 예를 들어 `wood` category를 Sionna 공식 ITU type `wood`와 고유 이름 `itu_wood_blocker_panel_000`으로 resolve한다.

재질 해석은 엄격하다.

- 알 수 없는 category/source, 설치본에 없는 ITU type, 0 이하 thickness, 0~1 밖 scattering coefficient는 오류다.
- 재질을 찾지 못했을 때 concrete로 조용히 대체하지 않는다. `fallback_policy`는 `none`, `fallback_used`는 항상 `false`다.
- standalone `build`는 먼저 요청 category/type을 기록한다. Sionna가 사용 가능하면 장면을 실제 load해 `scenario_manifest.json`에 runtime object ID를 추가하고 `materials_resolved.json`을 full runtime 값으로 갱신한다. 사용 불가능하면 CLI에 `material_resolution=deferred_until_sionna_runtime`을 표시하며, 이 상태는 runtime 검증 증거가 아니다.
- `run-ab`는 실제 Sionna scene을 로드한 뒤 material 이름과 ITU type, 등록 여부, `is_used`, 주파수에 따른 relative permittivity/conductivity, thickness, scattering coefficient를 다시 읽는다. 누락 또는 type 불일치는 실패다.

## Experiment schema

```yaml
schema_version: "1.0"

experiment:
  id: example_phase2b_ab
  status: provisional
  physically_validated: false

  baseline:
    scenario: scenes/<scene_id>/configs/sionna/empty.yaml
  variants:
    - scenario: scenes/<scene_id>/configs/sionna/synthetic_blocker.yaml

  solver:
    reuse_phase2a_settings: true
    carrier_frequency_hz: 2.4e9
    max_depth: 2
    enable_los: true
    enable_reflection: true
    enable_refraction: false
    enable_diffraction: false
    enable_scattering: false
    path_samples: 200000
    coverage_samples: 200000
    path_seed: 42
    coverage_seed: 43

  comparison:
    coverage_delta_unit: dB
    changed_cell_threshold_db: 1.0
    require_common_grid: true
    require_common_valid_mask: true

  reproducibility:
    rerun_baseline: true
    baseline_repeat_count: 2
```

현재 공개 workflow는 `reuse_phase2a_settings: true`, obstacle 없는 baseline, 활성 obstacle이 있는 variant 한 개를 요구한다. `variants` schema는 목록이지만 `run-ab`는 한 번에 정확히 하나만 실행한다. baseline 반복 실행은 최소 두 번이어야 한다.

Phase 2-A 설정에서 Room 입력, TX/RX, array, coverage height/grid/cell size를 재사용하고 solver 항목만 experiment 값으로 덮어쓴다. baseline과 variant의 Room 입력과 resolved TX/RX가 다르면 실행 전에 중단한다.

## 검증과 비교 의미

Obstacle은 mesh 생성 뒤 다음을 모두 통과해야 한다.

- 유한한 vertex, 비퇴화 triangle, closed manifold, 양의 signed volume
- 모든 vertex가 floor 위, ceiling 아래, 모든 wall 안쪽
- TX와 RX가 obstacle 내부가 아님
- synthetic validation obstacle이 설정된 TX-RX 선분과 실제 triangle 수준에서 교차함

경로는 반환 순서나 `path_index`에 의존하지 않고 `TX, RX, path type, ordered interaction object IDs`로 구조를 맞춘다. 거리, delay, amplitude와 interaction point 차이는 baseline 반복 noise floor와 함께 기록한다. blocker 성공 근거는 단순 total count 차이가 아니라 `rx_los` LoS 변화 또는 blocker object interaction이다.

Coverage 입력은 선형 path gain에서 dB로 한 번만 변환한다.

```text
delta_db = variant_db - baseline_db
```

`inside_mask`, 양쪽 `valid_mask`, 유한값의 교집합만 비교한다. 공통 grid와 valid mask가 필수인 기본 설정에서는 하나라도 다르면 실패한다. baseline 반복들의 최대 절대 차이를 보수적인 noise floor로 사용하며, A/B 최대 절대 변화가 이보다 커야 성공 조건을 만족한다.

## 출력 파일

### `build`

```text
<scenario-output>/
├─ scene/
│  ├─ scene.xml
│  └─ meshes/
│     ├─ floor_000.ply
│     ├─ ceiling_000.ply
│     ├─ wall_*.ply
│     └─ <obstacle object_name>.ply
├─ scene_manifest.json
├─ scenario_manifest.json
├─ materials_resolved.json
├─ resolved_scenario.yaml
├─ scenario_preview.png
├─ obstacles_combined.obj
├─ obstacles_combined.mtl
├─ obstacles_metric.json
├─ obstacles_scene.json
├─ obstacle_vertices_metric.csv
└─ obstacle_vertices_scene.csv
```

`scene_manifest.json`은 재사용한 Phase 2-A Room 변환 기록이고, 결합된 Room+Obstacle의 권위 있는 object/layer/material/transform 목록은 `scenario_manifest.json`이다. Sionna를 사용할 수 있는 `build`에서는 후자에 runtime object ID가 추가된다. `obstacles_combined.obj`는 미리보기·교환용이며 RF 재질 값은 `scene.xml`과 `materials_resolved.json`을 기준으로 한다.

`scenario_manifest.json`, `obstacles_metric.json`, `obstacles_scene.json`의 `coordinate_bridge_validation`은 obstacle vertex 뿐만 아니라 4×4 `local_to_metric`/`local_to_scene` transform도 Metric↔PGSR 양방향으로 왕복 검사한다. Point 오차와 transform 행렬 최대 요소 오차를 별도로 기록한다.

### `run-ab`

```text
<experiment-output>/
├─ baseline/                 # 첫 Empty 실행 + scenario build 산출물
├─ baseline_repeat_02/       # 두 번째 Empty solver 산출물
├─ variant/                  # obstacle variant 실행 + scenario build 산출물
├─ coverage/
│  ├─ coverage_baseline.png
│  ├─ coverage_variant.png
│  ├─ coverage_delta.png
│  ├─ coverage_delta.npy
│  ├─ coverage_delta.csv
│  └─ coverage_comparison.json
├─ previews/
│  ├─ paths_baseline_top.png
│  ├─ paths_variant_top.png
│  └─ paths_overlay_top.png
├─ environment.json
├─ reproducibility.json
├─ path_comparison.json
├─ coverage_comparison.json
├─ experiment_validation.json
├─ resolved_experiment.yaml
└─ PHASE2B_AB_REPORT.md
```

각 solver 실행 폴더에는 다음이 추가된다.

- `materials_resolved.json`: 실제 runtime Room+Obstacle material 값
- `paths/paths_all.json`, `paths/paths_all.csv`: LoS/정반사 경로와 interaction object ID/name/point
- `coverage/coverage_values.npy`, `coverage_valid_mask.npy`, `coverage_values.csv`, `coverage_metadata.json`, `coverage_map.png`
- `coverage/coverage_points_metric.csv`, `coverage_points_scene.csv`: Metric과 원본 PGSR 좌표

`coverage_delta.csv` 열은 `x_m`, `y_m`, `z_m`, `baseline_db`, `variant_db`, `delta_db`, `is_inside`, `is_valid_baseline`, `is_valid_variant`, `is_common_valid`다. `coverage_comparison.json`은 편의를 위해 experiment root와 `coverage/`에 모두 저장된다.

`experiment_validation.json.performance`는 baseline 반복과 variant의 scene load/path/Coverage solver 시간, A/B comparison 계산 시간, CSV·JSON·preview export 시간, report 작성 전 전체 시간을 구분해 기록한다. GPU 값은 진단 시점 snapshot이며 peak memory가 아니다.

## 종료 및 실패 조건

정상 종료 코드는 `0`이다. 예상된 schema/geometry/runtime/I/O 오류는 로그와 함께 `2`를 반환한다. `build`와 `run-ab`는 출력 폴더를 만들 수 있었다면 `phase2b_failure.json`에 exception type, 원인, 재현 명령을 남긴다. `validate`는 출력 인자가 없으므로 실패 JSON 없이 stderr와 종료 코드로 보고한다. 예상하지 못한 예외는 `1`이다.

다음 조건에서는 성공으로 계속하지 않는다.

- 설정 파일 누락, 잘못된 provisional marker, 중복 ID/object name, 활성 obstacle의 `null` geometry
- 지원하지 않는 geometry/material, 유효하지 않은 transform, external mesh parse 실패
- floor/ceiling/wall 관통, 퇴화/열린 mesh, TX/RX가 obstacle 내부, 필수 LoS 미교차
- Room object와 obstacle object 이름 충돌, PLY round-trip 실패, runtime shape 누락
- `run-ab`의 Sionna 환경/API 사용 불가, 또는 Sionna를 load한 `build`/`run-ab`의 strict material 등록·type 불일치
- Empty가 아닌 baseline, obstacle 없는 variant, 서로 다른 Room 입력이나 TX/RX, variant가 두 개 이상
- baseline 반복 2회 미만, 필수 grid/mask 불일치, 공통 유한 Coverage cell 없음

solver 실행은 끝났지만 LoS가 막히지 않았거나 blocker 관련 경로 근거가 없거나 Coverage 변화가 0/noise floor 이하인 경우에도 `experiment_validation.json`의 `overall_success=false`가 되고 CLI는 `2`를 반환한다. 부분 산출물이 존재할 수 있으므로 파일 존재 여부만으로 성공을 판단하지 말고 항상 이 필드를 확인한다. 재실행은 이전 실패 파일과 결과가 섞이지 않도록 새 출력 폴더를 권장한다.

## 테스트

Sionna가 필요 없는 geometry/schema/comparator/reproducibility 테스트:

```bash
conda run -n pgsr python -m pytest -q --import-mode=importlib \
  tools/sionna_scenario/tests
```

기존 Proxy Mesh와 Phase 2-A 회귀를 포함한 전체 기본 테스트:

```bash
conda run -n pgsr python -m pytest -q \
  --import-mode=importlib \
  tools/proxy_mesh_editor/tests \
  tools/sionna_smoke_test/tests \
  tools/sionna_scenario/tests
```

전용 Sionna 환경의 실제 Empty/Blocker integration test:

```bash
RUN_SIONNA_PHASE2B_INTEGRATION=1 conda run -n sionna \
  python -m pytest -q --import-mode=importlib \
  tools/sionna_scenario/tests
```

기존 Phase 2-A 실제 solver integration 회귀:

```bash
RUN_SIONNA_INTEGRATION=1 conda run -n sionna \
  python -m pytest -q --import-mode=importlib \
  tools/sionna_smoke_test/tests/test_sionna_integration.py
```

실제 integration의 최종 판정은 이 테스트들과 `run-ab` 결과의 `experiment_validation.json` 모든 check, `overall_success`를 함께 확인한다.

저장소 루트 전체에 대한 범위 없는 `pytest`는 사용하지 않는다. Vendored COLMAP test는 선택 의존성 `pycolmap`을 요구하고, 기본 import mode에서는 여러 디렉터리의 동명 `test_config.py` 모듈이 충돌할 수 있다. 위처럼 테스트 디렉터리를 범위로 지정하고 `--import-mode=importlib`을 사용한다.

## 범위와 다음 입력

이번 단계는 정밀 책상·의자 mesh, semantic segmentation, Room Envelope boolean/opening, 실제 물체 위치 추정, obstacle editor, 고해상도 Radio Map, ESP32 RSSI 비교, Viewer/실시간/network 기능을 구현하지 않는다.

`proxy_draft.yaml`을 실제 scenario로 바꾸려면 각 물체의 Metric 위치, 크기, 방향, floor clearance, 재질 category와 신뢰도, 문 상태 같은 측정값이 필요하다. 측정 전에는 draft 항목을 활성화하지 않는다.
