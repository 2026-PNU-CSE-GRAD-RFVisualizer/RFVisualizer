# RFVisualizer Phase 2-B Major Obstacle & Multi-Material A/B 검증 결과

> **SYNTHETIC / PROVISIONAL / NOT PHYSICALLY VALIDATED**
>
> 아래 Phase 2-B 수치는 전용 Sionna 환경에서 생성된 실제 실행 결과다. 다만 blocker는 검증 전용 인공 box이고 Room 배율과 RF 재질은 현장 실측으로 검증되지 않았다. 따라서 실제 강의실 물체 배치나 RSSI 정확도를 주장하지 않는다.

## 결론

Empty Room Envelope를 수정하지 않고 독립 wood obstacle shape를 추가했으며, 같은 TX/RX, solver, seed, Coverage grid로 Empty baseline 2회와 blocker variant 1회를 실제 Sionna RT 1.2.2에서 실행했다. `experiment_validation.json`의 22개 check가 모두 `true`, `overall_success=true`였다.

Synthetic blocker는 설정된 `tx_test → rx_los` 선분과 두 면에서 교차했고, solver 결과에서 해당 LoS는 `1 → 0`으로 사라졌다. 전체 경로 구성도 바뀌었고, Coverage 151개 공통 유효 셀에서 최대 절대 변화 `8.426285 dB`가 baseline 반복 noise floor `5.198781e-6 dB`보다 충분히 컸다. Metric↔PGSR obstacle vertex 왕복 최대 오차는 `1.986027e-15`, 4×4 transform 왕복 최대 오차는 `8.881784e-16`였다.

최종 산출물 재생성 후 담당자가 `scenario_preview.png`, `coverage_delta.png`, `paths_overlay_top.png`를 다시 시각 확인했다. 이 확인은 렌더링과 배치가 의도와 일치한다는 검증이며 물리적 치수나 RF 정확도 검증은 아니다.

## 증거 구분과 실행 provenance

이 문서에서 `실제 Phase 2-B 결과`는 다음 폴더의 solver 산출물 JSON을 직접 읽어 기록한 값이다.

```text
outputs/sionna/pnu_classroom/phase2b/experiments/synthetic_blocker_ab/
```

실행 명령:

```bash
conda run -n sionna python -m tools.sionna_scenario.main run-ab \
  --experiment configs/sionna/experiments/pnu_classroom_phase2b_ab.yaml \
  --output outputs/sionna/pnu_classroom/phase2b/experiments/synthetic_blocker_ab
```

- 실제 Phase 2-B 판정 원본: `experiment_validation.json`, `reproducibility.json`, `path_comparison.json`, `coverage_comparison.json`
- 실제 Phase 2-B 실행 보고서: `PHASE2B_AB_REPORT.md`
- 상속한 Phase 2-A 참고값: [PHASE2A_SMOKE_TEST_VALIDATION.md](../sionna_smoke_test/PHASE2A_SMOKE_TEST_VALIDATION.md)
- 문서 작성 시 로컬 `main` HEAD: `ddf14d0d29e09c0a41867e9b280b373edec7e06b`
- 최종 Phase 2-B commit: 문서 작성 시점에 아직 생성되지 않아 확정 값으로 기록하지 않았다. 실제 실행은 Phase 2-B 구현이 작업 트리에 있는 상태에서 수행했으므로 위 resolved config와 산출물 JSON이 현 수치의 직접 provenance다.

Phase 2-A의 `151`개 내부 유효 Coverage cell과 2.4 GHz 환경은 이번 실행이 같은 기반 장면을 사용한다는 sanity reference다. Phase 2-A 경로 보고와 Phase 2-B 전체 경로 수는 집계 대상이 다르므로 단순히 같은 숫자여야 하는 기준으로 사용하지 않았다. Phase 2-B는 두 RX의 모든 LoS/정반사 경로를 함께 집계한다.

## 환경

| 항목 | 실제 값 |
|---|---|
| Python | `3.10.20` |
| Sionna / Sionna RT distribution | `1.2.2 / 1.2.2` |
| Mitsuba | `3.8.0` |
| Dr.Jit | `1.3.1` |
| TensorFlow | `2.21.0` |
| Mitsuba variant | `cuda_ad_mono_polarized` |
| Dr.Jit backends | CUDA `true`, LLVM `true` |
| GPU | NVIDIA GeForce RTX 4090, 24,564 MiB |
| NVIDIA driver | `595.71.05` |
| CUDA version | 별도 버전은 기록되지 않음; Dr.Jit CUDA backend는 활성 |
| 실행 시 GPU memory snapshot | 12,358 MiB used; peak 측정값 아님 |
| TensorFlow physical GPU | 없음 |
| 환경 판정 | `available` |

전파 계산은 활성 Dr.Jit CUDA backend를 사용했다. TensorFlow GPU가 등록되지 않은 상태는 Phase 2-A와 같으며 이번 Sionna RT 실행을 막지 않았다.

## 입력과 동일 조건

Baseline과 variant는 모두 `configs/sionna/pnu_classroom_smoke_test.yaml`의 Metric Room, TX/RX, array, Coverage 배치를 사용했다.

```text
TX tx_test:       [-7.0, -5.0, 1.5] m
RX rx_los:        [-3.0, -5.0, 1.5] m
RX rx_reflection: [-10.0, -8.0, 1.5] m
```

Solver 설정:

```text
carrier frequency: 2.4 GHz
maximum depth: 2
LoS: enabled
specular reflection: enabled
refraction/diffraction/diffuse reflection: disabled
path samples: 200,000, seed 42
coverage samples: 200,000, seed 43
coverage delta: variant_db - baseline_db
common grid and valid mask: required
```

Variant manifest는 `room_envelope_modified=false`, `object_layers_independent=true`, `merge_shapes=false`를 기록했다. 기존 Phase 2-A 결과와 Metric Calibration은 다시 생성하거나 덮어쓰지 않았다.

## Synthetic blocker

| 항목 | 실제 값 |
|---|---|
| ID / runtime object ID | `blocker_panel_000` / `7` |
| 표식 | `validation_only`, `physical_object=false`, `confidence=synthetic` |
| Geometry | box, 8 vertices, 12 triangles, closed manifold |
| 입력 anchor | `floor_at_xy`, XY `[-5,-5]` m, floor clearance `0.05` m |
| 입력 크기 | `0.15 × 2.5 × 2.0` m |
| Metric bounds | `[-5.075,-6.25,0.259806]` ~ `[-4.925,-3.75,2.259806]` m |
| Signed volume | `0.75 m³` |
| PGSR bounds | `[-1.430430,-0.631763,0.451850]` ~ `[-0.094289,0.675099,1.778942]` |
| 최소 floor clearance | `0.0114919 m` |
| 최소 ceiling clearance | `0.1414631 m` |
| 최소 wall clearance | `3.4764790 m` |
| TX/RX obstacle 내부 | 둘 다 `false` |
| `tx_test → rx_los` 교차 | `true`, 2 intersections |

LoS 교차점은 Metric 좌표 `[-5.075,-5,1.5]`와 `[-4.925,-5,1.5]`였고 TX에서 각각 `1.925 m`, `2.075 m` 떨어져 있었다. `tx_test → rx_reflection` 선분은 blocker와 교차하지 않았다. 모든 vertex의 floor/ceiling/wall 검사, face winding, 양의 부피, PLY round-trip이 통과했다.

`floor_clearance_m=0.05`는 anchor 지점의 수직 offset이다. 바닥이 경사져 있으므로 최종 모든 모서리 중 최소 실제 clearance는 `0.0114919 m`이며, 0.05 m 전체가 최소 여유라는 뜻은 아니다.

## Material resolution

Obstacle 요청은 `source=sionna_preset`, `category=wood`, thickness `0.1 m`, scattering coefficient `0.0`이었다. 설치된 Sionna ITU catalog와 실제 scene runtime에서 다음처럼 엄격하게 확인됐다.

| 항목 | 실제 값 |
|---|---|
| Sionna material name | `itu_wood_blocker_panel_000` |
| ITU type / class | `wood` / `ITURadioMaterial` |
| Relative permittivity at 2.4 GHz | `1.99000001` |
| Conductivity at 2.4 GHz | `0.012011805 S/m` |
| Runtime thickness | `0.100000001 m` |
| Scattering coefficient | `0.0` |
| `is_used` | `true` |
| Fallback | `false`, policy `none` |

Room Envelope는 Phase 2-A의 concrete material 세 개(floor, ceiling, walls)를 유지했다. Variant runtime에는 Room 3개와 obstacle 1개, 총 4개 material이 등록됐다. 이 wood 값은 Sionna 공식 ITU 모델의 실행값이지 실제 blocker 또는 강의실 목재를 측정한 값이 아니다.

## Scene composition

| 항목 | Empty baseline | Synthetic variant |
|---|---:|---:|
| Room objects | 6 | 6 |
| Obstacle objects | 0 | 1 |
| Total objects | 6 | 7 |
| Room triangles | 12 | 12 |
| Obstacle triangles | 0 | 12 |
| Total triangles | 12 | 24 |

Room의 `floor_000`, `ceiling_000`, `wall_000..003`과 `blocker_panel_000`은 서로 다른 PLY 및 Mitsuba shape로 유지됐다. Runtime object name/ID가 manifest와 모두 일치했다.

## Baseline reproducibility

동일 path seed `42`, Coverage seed `43`으로 Empty baseline을 두 번 실행했다. 정확한 bitwise 동일 결과는 아니었지만 선언한 수치 허용오차 안에서 재현됐다.

| 검사 | 실제 값 |
|---|---:|
| 반복 수 / pair 수 | 2 / 1 |
| 같은 seed metadata | `true` |
| Path count/structure/numeric availability | 모두 일치 |
| 매칭된 path | 53 |
| Coverage common cells | 151 |
| Coverage mean absolute repeat delta | `7.928162e-7 dB` |
| Coverage p95 absolute repeat delta | `2.353474e-6 dB` |
| Coverage maximum absolute repeat delta | `5.198781e-6 dB` |
| Coverage deterministic tolerance | `1.0e-4 dB` |
| Overall within tolerance | `true` |

보수적 noise floor는 각 반복의 최대 절대 차이로 정했다.

| Path 값 | 실제 noise floor |
|---|---:|
| Distance | `2.130154e-6 m` |
| Delay | `7.105427e-15 s` |
| Amplitude magnitude | `3.733703e-10` |
| Interaction point displacement | `5.801663e-6 m` |

경로별 `path_gain_linear`와 `path_gain_db` field는 이번 path record에 없어서 해당 repeat sample count는 0이다. 복소 amplitude magnitude는 기록됐고, Coverage path gain은 별도로 비교했다.

## Path A/B 결과

두 RX 전체 집계:

| 항목 | Empty baseline | Synthetic variant | 변화 |
|---|---:|---:|---:|
| LoS paths | 2 | 1 | -1 |
| Specular reflection paths | 51 | 34 | -17 |
| Total paths | 53 | 35 | -18 |
| Maximum interactions | 2 | 2 | 0 |

전체 variant 경로 중 blocker runtime object ID `7`과 interaction한 경로는 4개였다. 구조가 바뀌었고 `path_configuration_changed=true`, `change_exceeds_numerical_noise=true`였다.

차폐 검증의 핵심인 `rx_los`만 보면 다음과 같다.

| 항목 | Empty baseline | Synthetic variant | 변화 |
|---|---:|---:|---:|
| LoS 존재 | `true` | `false` | 차단 |
| LoS paths | 1 | 0 | -1 |
| Specular reflection paths | 26 | 12 | -14 |
| Total paths | 27 | 12 | -15 |

`rx_los` variant에는 blocker 표면을 반사점으로 사용하는 경로가 0개였지만, geometry 교차와 LoS 제거가 직접 blocker 관련 증거로 기록됐다. 전체 수신기 집계에서는 blocker interaction 경로도 별도로 4개 확인됐다. 따라서 단순 path count 차이만으로 성공 처리한 것이 아니다.

## Coverage A/B 결과

Coverage는 선형 path gain을 양쪽 모두 같은 방식으로 dB로 한 번 변환했고, `variant_db - baseline_db`로 계산했다.

| 항목 | 실제 값 |
|---|---:|
| Grid | `11 × 15`, 165 cells |
| Common finite valid cells | 151 |
| Grid / valid mask match | `true / true` |
| Mean delta | `-1.011710646 dB` |
| Mean absolute delta | `1.011710646 dB` |
| Median delta | `-0.501312445 dB` |
| Minimum / maximum delta | `-8.426284580 / -0.000083106 dB` |
| Maximum absolute delta | `8.426284580 dB` |
| p05 / p25 delta | `-2.614722787 / -1.320048304 dB` |
| p75 / p95 delta | `-0.329166107 / -0.135619185 dB` |
| `abs(delta) > 1 dB` | 48 cells |
| `abs(delta) > 3 dB` | 6 cells |
| Positive / negative / zero delta | `0 / 151 / 0` cells |
| Baseline repeat noise floor | `5.198781e-6 dB` |
| Meaningful cells (`abs(delta)>max(1dB,noise)`) | 48 |
| A/B change exceeds noise floor | `true` |

공통 유효 셀의 delta는 모두 finite였으며 모두 음수였다. 이 결과는 synthetic blocker가 solver 출력에 비영향이 아니라 명확한 감쇠 변화를 만들었다는 A/B 증거다. 실제 환경의 절대 path gain 또는 RSSI 오차를 검증한 값은 아니다.

## Coordinate bridge

Obstacle vertex와 4×4 local transform을 Metric에서 원본 PGSR scene 좌표로 변환했고 두 방향 왕복을 각각 확인했다.

```text
metric → scene → metric maximum error: 1.9860273226e-15
scene → metric → scene maximum error: 1.4261072965e-15
point maximum error:                  1.9860273226e-15
transform metric → scene → metric:     8.8817841970e-16
transform scene → metric → scene:      8.8817841970e-16
transform maximum error:              8.8817841970e-16
overall point/transform maximum:      1.9860273226e-15
success: true
```

Obstacle 좌표는 `variant/obstacles_metric.json`, `variant/obstacles_scene.json`, 두 vertex CSV에 저장됐다. Coverage의 Metric/PGSR 좌표는 각 실행의 `coverage_points_metric.csv`, `coverage_points_scene.csv`에 저장됐다.

## 성능

| 실행 | Scene load | Path solve | Coverage solve |
|---|---:|---:|---:|
| Baseline 1 | 0.165873 s | 0.087678 s | 0.004645 s |
| Baseline 2 | 0.021605 s | 0.052107 s | 0.002274 s |
| Variant | 0.031538 s | 0.059841 s | 0.002833 s |

A/B comparison 계산은 `0.010719335 s`, delta CSV/JSON·Coverage/path preview export는 `1.167309496 s`였다. Report 작성 전 전체 pipeline 시간은 `2.204184969 s`였다. GPU peak memory는 계측하지 않았고, 환경 진단 시 GPU 사용량 snapshot만 `12,358 MiB`로 기록했다.

## 시각 확인

다음 실제 이미지를 여러 결과 JSON과 함께 확인했다.

- `variant/scenario_preview.png`: Room top view에서 blocker footprint와 TX/RX 배치 확인
- `coverage/coverage_delta.png`: 0 dB 중심 diverging scale, obstacle footprint, TX/RX, Metric 축 확인
- `previews/paths_overlay_top.png`: baseline/variant path와 obstacle overlay 확인

`coverage_baseline.png`, `coverage_variant.png`, `paths_baseline_top.png`, `paths_variant_top.png`도 생성됐다. 시각 확인은 synthetic A/B wiring 검증 범위다.

## 자동 판정

`experiment_validation.json`의 다음 check가 모두 실제로 `true`였다.

```text
environment_available
room_envelope_unmodified
independent_obstacle_layer
scene_object_count_increased_by_obstacles
runtime_obstacle_shape_loaded
strict_material_resolution
baseline_repeated
baseline_reproducible_within_tolerance
synthetic_blocker_geometry_valid
synthetic_blocker_intersects_configured_los
baseline_rx_los_exists
variant_rx_los_blocked
blocker_related_path_evidence
path_configuration_changed
coverage_grid_matches
coverage_valid_mask_matches
coverage_delta_finite
coverage_change_exceeds_repeat_noise
coverage_has_nonzero_change
coordinate_bridge_round_trip
provisional_marking
physically_validated_false
```

위 목록은 JSON에 기록된 check를 그대로 열거한 것이며 최종 `overall_success=true`였다.

## 테스트 상태

최종 코드 상태에서 범위를 명시해 실행한 결과다.

```text
pgsr Phase 2-B scenario suite: 83 passed, 1 skipped
pgsr Proxy Mesh + Phase 2-A + Phase 2-B regression: 171 passed, 2 skipped
sionna scenario suite with RUN_SIONNA_PHASE2B_INTEGRATION=1: 84 passed
gated Phase 2-A Sionna integration: 1 passed
Ruff / git diff check: clean
실제 run-ab: PASS (overall_success=true)
```

실행 명령은 [README의 테스트 절](README.md#테스트)을 따른다. 결합 회귀에는 `--import-mode=importlib`을 사용했다. 범위 없는 저장소 전체 `pytest`는 vendored COLMAP의 선택 `pycolmap` 의존성과 기존 동명 `test_config` 모듈 충돌 때문에 이 저장소의 적절한 판정 명령이 아니다. 이는 위의 범위 지정 regression 결과와 별개의 환경 제약이다.

## 생성 파일

주요 결과:

```text
outputs/sionna/pnu_classroom/phase2b/experiments/synthetic_blocker_ab/
├─ baseline/
├─ baseline_repeat_02/
├─ variant/
├─ coverage/
├─ previews/
├─ environment.json
├─ reproducibility.json
├─ path_comparison.json
├─ coverage_comparison.json
├─ experiment_validation.json
├─ resolved_experiment.yaml
└─ PHASE2B_AB_REPORT.md
```

별도 scenario build 결과도 다음에 생성됐다.

```text
outputs/sionna/pnu_classroom/phase2b/scenarios/empty/
outputs/sionna/pnu_classroom/phase2b/scenarios/synthetic_blocker/
```

파일별 schema와 전체 트리는 [README의 출력 파일 절](README.md#출력-파일)에 설명한다.

## 경고와 한계

- `blocker_panel_000`은 실제 강의실 물체가 아니며 결과의 변화량도 실제 물체 효과 예측값이 아니다.
- Metric scale은 provisional이고 현장 거리 측정으로 검증되지 않았다.
- Room concrete와 blocker wood는 Sionna ITU preset이며 실제 벽체·목재의 복합층, 수분, 두께를 측정하지 않았다.
- Path solver의 경로별 path gain field는 이번 추출 형식에 없고 amplitude만 비교했다.
- 고해상도 Radio Map, 실제 RSSI, 문 opening, 정밀 가구 mesh, Viewer/실시간 기능은 검증하지 않았다.
- `pnu_classroom_proxy_draft.yaml`의 책상, 칠판, 문, 대형 금속 물체는 모두 비활성이며 실제 좌표를 추정해 넣지 않았다.

## 실제 강의실 scenario에 필요한 정보

후속 실제 Proxy Object 배치에는 최소한 다음 측정값이 필요하다.

- 책상 군집, 칠판, 문, 대형 금속 물체의 Metric 위치와 bounds
- floor에 대한 배치 방식과 clearance, roll/pitch/yaw
- 문 상태와 panel thickness
- 물체별 실제 재질 category 또는 측정 기반 전자기 특성
- 측정 출처와 confidence

이 정보가 준비되기 전에는 draft obstacle을 활성화하거나 이번 synthetic 결과를 실제 강의실 모델로 승격하지 않는다.
