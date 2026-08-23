# corridor3f_20260820 — 좌표 확정과 실험 준비

- 작성일: 2026-08-20
- 씬: `pnu_3f_corridor` (부산대 3층 ㅁ자 링 복도)
- 상태: **Marker 계약 `ready`** (2026-08-20 배치 확정), Scene 계약 `draft` (장애물 배치가 남음).
  좌표는 도면 기반이며 현장 줄자 실측으로 확정한 값은 아니다.

## 1. 왜 이 문서가 필요한가

이전 복도 실험(`Test_1_004838`, `Test_2_010416`)은 Backend Export의 `points.csv`에
좌표 행이 하나도 없어서 사후에 장치 배치 계약으로 좌표를 복원해야 했고, 원본 QC가
`ok=false`로 남았다. 이번에는 측정 전에 좌표계, 좌표값, 배율 근거를 먼저 동결한다.

## 2. 좌표계 (frame id `pnu_3f_corridor_metric_v1`)

| 항목 | 값 |
| --- | --- |
| 단위 | meter, 오른손 좌표계, up = `+Z` |
| 원점 | Proxy Mesh(`complex_envelope`) 점유 격자의 최소 모서리, 바닥면 `z=0` |
| `+X` | 도면에서 왼쪽. 계단실 쪽이 X가 크다 (0 ~ 44.91 m) |
| `+Y` | 도면에서 아래쪽. 좁은 복도(Y 작음) → 넓은 개방 복도(Y 큼) (0 ~ 20.92 m) |
| `+Z` | 위. 바닥 0.0, 천장 3.0 |
| RX 높이 | 0.45 m |
| TX 높이 | 0.80 m |

원점은 현장 말뚝이 아니라 Mesh에서 유도한 수학적 점이다. 현장 배치는 원점이 아니라
`references/floorplan_tx_calib_test_grid.png`의 도면 위치와 벽 기준 거리로 재현한다.

## 3. 미터 배율의 근거

- 층고 **3.0 m** 하나만으로 배율을 정했다 (`4.252497 m / 장면단위`).
- 이전 2.7 m 가정값으로 만든 Proxy Mesh는 2026-08-20에 3.0 m로 다시 만들었다.
  모든 좌표가 이전 값의 10/9배다. 2.7 m 기준으로 계산한 옛 수치와 섞지 않는다.
- 실측 길이 하나(예: 넓은 복도의 벽-벽 거리)를 얻으면
  `scripts/build_complex_proxy.py --ceiling-height-m`만 바꿔 다시 만들고 이 문서를 갱신한다.

## 4. 도면 ↔ Metric 정합

- 기준 도면: `references/floorplan_tx_calib_test_loop.png` (1774x887)
- 방법: 도면의 복도 자유공간 mask와 Proxy Mesh 점유 mask의 uniform-scale 정합 (회전 없음, 180도 방향 차이만 반영)
- 결과: `1 px = 0.03975 m`, IoU 0.74
  - `X_m = 56.6115 - 0.03975 * image_x`
  - `Y_m = -6.4145 + 0.03975 * image_row`
- 남은 차이는 촬영이 닿지 않은 넓은 복도 바깥쪽 약 1.2 m와 코어 주변 벽면이다.
  따라서 **개별 좌표의 실제 오차는 약 ±0.5 m**로 본다.

## 5. 확정 좌표 (`configs/tx_rx.json`)

`clear`는 Proxy Mesh 통행 가능 영역 기준 가장 가까운 벽까지 거리, `LOS`는 TX와의 2D 가시선이다.

| 표식 | point_id | 장치 | 역할 | X (m) | Y (m) | Z (m) | 벽 여유 (m) | TX 거리 (m) | 가시선 | 위치 |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| TX | — | ap-01 | transmitter | 21.37 | 17.83 | 0.80 | 3.10 | — | — | 넓은 복도 중앙 |
| C1 | cal-01 | node-01 | calibration | 34.90 | 18.70 | 0.45 | 2.25 | 13.56 | **LOS** | 넓은 복도 왼쪽 |
| C2 | cal-02 | node-03 | calibration | 24.02 | 6.31 | 0.45 | 0.85 | 11.82 | NLOS | 좁은 복도 중앙 |
| C3 | cal-03 | node-04 | calibration | 16.07 | 6.31 | 0.45 | 1.75 | 12.68 | NLOS | 좁은 복도, 코어 통로 부근 |
| C4 | cal-04 | gw-01 | calibration | 5.86 | 18.56 | 0.45 | 2.35 | 15.53 | **LOS** | 넓은 복도 오른쪽 |
| T1 | test-01 | node-02 | test | 12.57 | 17.83 | 0.45 | 3.10 | 8.80 | LOS | 넓은 복도 |
| T2 | test-02 | node-02 | test | 1.80 | 17.80 | 0.45 | 3.10 | 19.57 | LOS | 넓은 복도 오른쪽 끝 |
| T3 | test-03 | node-02 | test | 1.76 | 6.90 | 0.45 | 0.84 | 22.45 | NLOS | 오른쪽 짧은 복도 |
| T4 | test-04 | node-02 | test | 5.17 | 5.31 | 0.45 | 0.75 | 20.47 | NLOS | 좁은 복도 |
| T5 | test-05 | node-02 | test | 10.90 | 5.31 | 0.45 | 0.75 | 16.32 | NLOS | 좁은 복도 |
| T6 | test-06 | node-02 | test | 20.04 | 5.31 | 0.45 | 0.75 | 12.59 | NLOS | 좁은 복도 |
| T7 | test-07 | node-02 | test | 31.57 | 5.31 | 0.45 | 0.75 | 16.15 | NLOS | 좁은 복도 |
| T8 | test-08 | node-02 | test | 37.93 | 6.90 | 0.45 | 1.43 | 19.84 | NLOS | 왼쪽 짧은 복도 |
| T9 | test-09 | node-02 | test | 37.93 | 16.88 | 0.45 | 1.75 | 16.59 | LOS | 넓은 복도 왼쪽 끝 |
| T10 | test-10 | node-02 | test | 30.10 | 17.83 | 0.45 | 3.10 | 8.73 | LOS | 넓은 복도 |

구성: 보정 **LOS 2 + NLOS 2**, Test **LOS 4 + NLOS 6**. 보정-Test 최소 거리 3.53 m.

장치 배정: 보정점 4개는 고정 노드가 하나씩 맡고(C1 `node-01`, C2 `node-03`, C3 `node-04`,
C4 `gw-01`), Test 점 10개는 이동 노드 `node-02` 하나가 옮겨 다니며 측정한다.
`tx_rx.json`의 각 항목에 `node_id`로 기록했다. Backend Export의 `node_id`와 이 값이 같아야
측정 행을 좌표에 붙일 수 있다.
`scripts/make_markers.py`가 실행할 때마다 이 세 규칙(실내·벽 여유 0.5 m, 보정-Test 3 m,
보정 집합의 LOS/NLOS 혼합)을 검사하고 어기면 파일을 쓰지 않고 종료한다.

TX 주파수 2.4 GHz, 송신 세기 20 dBm은 명목값이며 실측이 아니다.

이 표와 `configs/tx_rx.json`, 좌표 표기 도면은 다음 한 줄로 다시 만든다.
표식을 도면에서 옮겼거나 배율을 바꿨으면 실행한 뒤 8절의 검증을 다시 돌린다.

```bash
python scenes/pnu_3f_corridor/experiments/corridor3f_20260820/scripts/make_markers.py
```

## 6. 보정점 배치 근거 (2026-08-20 수정)

처음에는 보정 RX 4개가 전부 좁은 복도(NLOS)에 있었다. Test 10개 중 4개는 LOS이므로,
NLOS에서만 구한 global bias를 LOS 지점에 적용하면 외삽이 되어 잘 맞던 LOS 지점이
오히려 나빠진다. Residual IDW도 넓은 복도에 보정점이 없으면 그 영역 전체가 외삽이다.

그래서 **C1과 C4를 넓은 복도 양끝으로 옮겼다.** 보정 집합이 Test 집합과 같은 조건
(LOS와 NLOS 둘 다)을 갖게 하는 것이 목적이다. 보정점 구성을 바꾸면 이 원칙을 깨지 않는지
확인한다. `make_markers.py`가 자동으로 검사한다.

C4를 옮기면서 T2가 2.67 m로 가까워져 held-out 독립성이 깨지므로 T2를
넓은 복도 오른쪽 끝 `(1.80, 17.80)`으로 옮겼다. 나머지 Test 점은 그대로다.

남은 한계: LOS 보정점이 TX에서 13.6 m와 15.5 m에 있어 T1(8.8 m)과 T10(8.7 m)은
거리로 보면 두 보정점보다 TX에 가깝다. 공간적으로는 C1과 C4 사이에 있어 내삽이므로
Residual IDW에는 문제가 없지만, 거리 기준 보정을 추가로 쓸 경우에는 감안해야 한다.

## 7. 현장에서 해야 할 일

2026-08-20 결정: **계획 좌표 그대로 측정하고, 안 잡히는 지점만 현장에서 옮긴다.**
예측이 ±3 dB 흔들리는 구간이라 지금 옮길 근거가 약하다. 실제 수신 여부가 답이다.

1. `references/floorplan_tx_calib_test_grid.png`를 출력해 표식 위치에 노드를 놓는다.
2. **cal-02와 cal-03을 가장 먼저 측정한다.** 예측이 -105 dBm대라 ESP32 감도 아래일 수 있다.
   - 잡히면 계획대로 진행한다.
   - 30초 이상 한 프레임도 못 잡으면 아래 예비 좌표로 옮기고, **옮긴 좌표를 그 자리에서 기록한다.**
3. test-05, test-06, test-07도 같은 방식으로 확인한다. Test 점은 미수신이어도
   "미수신"을 결과로 남길 수 있으므로 보정점보다 우선순위가 낮다.
4. **긴 거리 하나를 줄자로 실측한다** (예: 넓은 복도의 벽-벽 거리, 또는 T1-T10 사이 거리).
   이 값 하나로 3.0m 층고 가정에서 온 배율 오차를 잡을 수 있다.
5. Backend Export의 `points.csv`에 좌표 열과 Calibration/Test 역할이 실제로 기록되는지
   첫 세션 시작 직후에 확인한다. (이전 실험이 여기서 실패했다)
6. BSSID와 채널이 로그에 기록되는지 확인한다.

### 예비 좌표 (미수신일 때만 사용)

| 대상 | 좌표 | 예측 RSSI | 벽 여유 | 가장 가까운 Test 점 |
| --- | --- | ---: | ---: | --- |
| cal-02 대체 | (34.40, 6.60) | -75.3 | 0.60 m | T7까지 3.11 m |
| cal-03 대체 | (8.10, 6.60) | -91.3 | 0.60 m | T5까지 3.08 m |
| 둘 다 실패하면 | (37.40, 1.38) | -72.0 | 1.15 m | T8까지 5.55 m (계단실 가지) |

셋 다 NLOS를 유지하고 held-out 최소 거리 3 m 규칙을 만족한다.

좁은 복도의 예측값은 코어 뒤 한가운데가 가장 낮고 양끝으로 갈수록 올라간다.
즉석에서 옮겨야 하면 **가까운 링 모서리 쪽으로 걸어가면서 잡히는 지점**을 찾으면 된다.

| X 위치 | 예측 RSSI |
| ---: | ---: |
| 8.1 | -91 |
| 16.1 (cal-03) | -105 |
| 24.0 (cal-02) | -107 |
| 31.4 | -87 |
| 34.4 | -75 |

옮긴 뒤에는 `scripts/make_markers.py`의 `MARKERS` 표를 고치고 다시 실행한다.
배치 규칙 검사가 자동으로 돌고 도면과 JSON이 함께 갱신된다.

## 8. 검증 결과 (2026-08-20)

```bash
python -m tools.rf_experiment.main validate-contracts \
  --scene   scenes/pnu_3f_corridor/experiments/corridor3f_20260820/configs/scene.json \
  --markers scenes/pnu_3f_corridor/experiments/corridor3f_20260820/configs/tx_rx.json \
  --methods scenes/pnu_3f_corridor/experiments/corridor3f_20260820/configs/method_config.json
```
`success=true`, `ready=false` (장애물 배치가 남아 정상)

```bash
conda run -n pgsr python -m tools.proxy_placement_editor.main validate \
  --scenario    scenes/pnu_3f_corridor/configs/sionna/proxy.yaml \
  --candidates  scenes/pnu_3f_corridor/configs/proxy_editor/candidates.yaml \
  --room-json   scenes/pnu_3f_corridor/proxy_mesh/complex_envelope/room_envelope_metric.json \
  --calibration scenes/pnu_3f_corridor/proxy_mesh/complex_envelope/calibration.json \
  --markers     scenes/pnu_3f_corridor/experiments/corridor3f_20260820/configs/tx_rx.json \
  --output      scenes/pnu_3f_corridor/experiments/corridor3f_20260820/outputs/proxy_placement
```
`success=true`, TX 1 / calibration 4 / test 10, `enabled_errors` 없음. 15개 모두 방 안이다.
좌표 왕복 오차 5.03e-15 m. TX(`ap_tx_000`)는 바닥 0.775 m, 천장 2.175 m, 벽 3.00 m 여유로 VALID다.

같은 명령을 `--output scenes/pnu_3f_corridor/proxy_placement`로도 한 번 실행해
씬 기본 출력 폴더의 2.7 m 시절 좌표를 지웠다. 두 폴더 모두 지금 좌표를 가리킨다.

```bash
conda run -n sionna python -m tools.sionna_smoke_test.main run \
  --config scenes/pnu_3f_corridor/configs/sionna/smoke_test.yaml \
  --output scenes/pnu_3f_corridor/sionna/smoke_test
```
통과. LoS 오차 4.12e-07 m, 정반사 경로 205개, coverage 유효 70.8%.

## 9. Sionna 회절·산란 기본값 (2026-08-20)

코어 뒤 NLOS 지점은 정반사만으로는 경로가 0개다. 그래서 `smoke_test.yaml`과
`configs/sionna_solver.json` 모두 회절과 확산 반사를 기본으로 켰다.

| 항목 | 이전 | 지금 |
| --- | --- | --- |
| `max_depth` | 2 | **5** |
| `enable_diffraction` | false | **true** |
| `enable_scattering` | false | **true** |
| `materials.*.scattering_coefficient` | 없음(0.0) | **0.3** |

`scattering_coefficient`를 함께 넣은 이유가 중요하다. Sionna의 기본값은 0.0이고,
0이면 `enable_scattering`을 켜도 확산 경로가 하나도 생기지 않는다. 0.3은 거친 콘크리트
문헌값 범위(0.2~0.5)의 중간값이며 **실측이 아니다**. 재질 보정 단계에서 조정할 후보다.

이 값을 실제로 반영하려면 도구 쪽도 두 군데 고쳐야 했다.

- `tools/sionna_smoke_test/scene_exporter.py`: Sionna는 id가 `itu_`로 시작하는 BSDF를
  XML 단계에서 다시 쓰면서 type/thickness/color만 남기고 나머지 property를 버린다
  (`sionna/rt/scene_utils.py`). 그동안 재질 id가 `itu_concrete_floor`였기 때문에
  설정한 값이 조용히 무시되고 Sionna 기본값이 쓰였다. Phase 2-B와 같은 `radio_itu_`
  접두사로 바꿔서 해결했다.
- `tools/rf_experiment/sionna_rssi.py`: `hashlib.file_digest`는 Python 3.11+ 함수인데
  sionna 환경은 3.10이라 `run-sionna`가 시작하자마자 죽었다. 직접 읽는 방식으로 바꿨다.

효과 (`rx_nlos` = T6 위치, 코어 뒤):

| | 경로 수 |
| --- | ---: |
| 회절·산란 끄고 depth 2 | 0 |
| 회절·산란 켜고 depth 5 | 29 (정반사+확산 혼합) |

coverage 유효 셀 비율도 53.3% → 70.8%로 올랐다. 정반사만 쓰던 조건과 결과를 섞어 비교하지 않는다.

### 샘플 수와 경로 한도

`max_num_paths_per_src`를 함께 올리지 않고 `samples_per_src`만 2M으로 올렸더니
깊은 그림자 지점 5개(cal-02, cal-03, test-05~07)의 유효 경로가 **0개**가 됐다.
후보 경로가 한도(기본 1M)를 넘으면 약한 RX의 경로부터 잘려 나가기 때문이다.
두 값을 항상 같이 올린다. 지금은 8M 샘플 / 40M 한도다.

RTX 4090에서 지점 예측과 radio map을 합쳐 1초 미만이므로 샘플을 아낄 이유가 없다.

### 수렴 확인 (2026-08-20)

| 지점 | 200k | 500k | 2M | 8M | 스프레드 |
| --- | ---: | ---: | ---: | ---: | ---: |
| LOS 6개 | | | | | **0.1 dB 이내** |
| test-03 (얕은 그림자) | -70.81 | -69.83 | -69.63 | -69.38 | 1.43 dB |
| test-04 | -74.33 | -72.90 | -72.16 | -71.61 | 2.72 dB |
| cal-03 (깊은 그림자) | -105.17 | -104.59 | -108.01 | -105.30 | **3.43 dB** |
| test-06 | -105.19 | -105.73 | -107.99 | -106.70 | **2.80 dB** |

LOS 지점은 완전히 수렴했고, 코어 뒤 깊은 그림자 지점은 8M 샘플에서도 약 3 dB 흔들린다
(유효 경로가 900~1100개뿐이다). 이 지점들의 예측값은 ±3 dB 불확실성을 달고 봐야 한다.

Radio map도 같다. samples_per_tx 128M과 512M의 셀 값 차이는 중앙값 0.03 dB지만
상위 5%는 16 dB다. 밝은 영역은 믿을 수 있고 깊은 그림자 셀은 아직 아니다.

### 현장 실측으로 뒤집힌 예측 (2026-08-21) — 아래 절은 기록으로만 남긴다

**좁은 복도 안쪽에서 raw RSSI 약 -79 ~ -80 dBm이 실측됐다.** depth 5 예측(-105 dBm대)보다
25 dB 높다. 원인은 재질이 아니라 **경로 깊이**였다.

ㅁ자 링 복도에서는 신호가 코어를 뚫지 않고 **링을 빙 돌아온다.** TX에서 좁은 복도 안쪽까지
링을 따라 35~46 m이고, 자유공간 기준 -51~-53 dBm에 코너 2회 손실 약 27 dB를 더하면
-79 dBm으로 실측과 맞는다. 40 m 복도를 따라가려면 벽 반사가 5회로는 어림도 없다.

`max_depth`를 12로 올린 결과(다른 조건 동일):

| 지점 | depth 5 | **depth 12** | 변화 |
| --- | ---: | ---: | ---: |
| cal-02 | -106.7 | **-96.2** | +10.5 |
| cal-03 | -105.3 | **-97.6** | +7.7 |
| test-05 | -101.1 | **-84.6** | +16.5 |
| test-06 | -106.7 | **-94.3** | +12.4 |
| test-07 | -97.7 | **-81.4** | +16.3 |
| LOS 6개 | | | -1.4 ~ -3.1 |

유효 경로 수는 깊은 그림자 지점에서 약 1,000개 → 약 190,000개로 늘었다.
depth 16·20은 추가 이득이 없다(1 dB 이내). 샘플도 4M과 8M 차이가 1 dB 이내로 수렴했다.

**LOS 지점이 1~3 dB 내려간 것에 주의한다.** 이전 문서의 "LOS는 0.1 dB 이내로 수렴"은
depth 5 고정에서 샘플만 늘렸을 때의 이야기다. 깊이를 바꾸면 경로가 늘어 간섭 합이 달라진다.
현장 LOS 기준점 실측으로 확인한다.

`enable_refraction`(벽 투과)은 계속 끈다. 켜보면 cal-02가 -96 → -57로 **23 dB 과대평가**된다.
벽 두께·투과 손실을 실측하기 전에는 쓸 수 없다. 재질 보정 단계의 과제다.

수신 감도 걱정은 사라졌다. -79 dBm은 ESP32 감도(-95 ~ -100)보다 15 dB 이상 여유가 있어
**15개 지점 모두 측정 가능**하다. 7절 예비 좌표는 보험으로만 유지한다.

### (기록) 이전 예측값과 수신 감도 문제

현재 조건으로 계산한 15개 지점 예측값이다 (`processed/sionna_points.csv`).

| 지점 | 예측 RSSI | 지점 | 예측 RSSI |
| --- | ---: | --- | ---: |
| cal-01 | -37.99 | test-04 | -71.61 |
| cal-02 | **-106.67** | test-05 | **-101.13** |
| cal-03 | **-105.30** | test-06 | **-106.70** |
| cal-04 | -38.49 | test-07 | **-97.73** |
| test-01 | -35.79 | test-08 | -68.58 |
| test-02 | -39.55 | test-09 | -39.48 |
| test-03 | -69.38 | test-10 | -35.68 |

굵은 5개는 **일반적인 ESP32 수신 감도(약 -95 ~ -100 dBm) 아래이거나 경계**다.
현장에서 신호를 아예 못 잡을 수 있다. 이전 4층 실험에서 Sionna 원본이 실측보다
평균 14.9 dB 높게 나왔던 것을 감안하면 실제로는 더 낮을 가능성이 크다.

**결정(2026-08-20): 계획 좌표 그대로 측정하고 현장에서 확인한다.** 예비 좌표와
현장 절차는 7절에 있다. cal-02와 cal-03이 둘 다 미수신이면 보정이 NLOS 2개를 잃고
6절의 LOS/NLOS 혼합 원칙이 깨지므로, 그때는 반드시 예비 좌표로 옮긴다.

## 9-1. 측정 후 분석 방법 (2026-08-21 확정)

Backend Export 가 나오면 **Segment 단위**로 분석한다. 각 Test 를 같은 `segment_id`
(= 같은 2분 기록창)의 C1~C4 로만 예측하고, 정방향·역방향 지표를 따로 낸다.

```bash
python -m tools.rf_experiment.main analyze \
  --test-points        <export>/processed/test_points.csv \
  --calibration-window <export>/processed/calibration_by_test_window.csv \
  --sionna-points      scenes/pnu_3f_corridor/experiments/corridor3f_20260820/processed/sionna_points.csv \
  --sionna-grid        scenes/pnu_3f_corridor/experiments/corridor3f_20260820/processed/sionna_grid.csv \
  --methods            scenes/pnu_3f_corridor/experiments/corridor3f_20260820/configs/method_config.json \
  --output             scenes/pnu_3f_corridor/experiments/corridor3f_20260820
```

`--summary measurements_summary.csv` 경로는 실험 전체를 뭉갠 집계라 정·역방향이 합쳐진다.
진단용으로만 쓰고 논문 수치로 쓰지 않는다.

미수신 처리는 `configs/method_config.json` 의 `evaluation.missing_measurement_policy` 에
동결했다: **제외 후 보고(`exclude_and_report`), 값 대입 없음(`imputation: none`).**
제외한 Segment 는 `analysis_report.json` 의
`input_provenance.segments_without_test_measurement` 에 남는다.
Calibration 미수신은 제외 대상이 아니다 — 7절 예비 좌표로 옮긴다.

히트맵의 calibration 값은 지점별 전체 시간창 평균이다
(`heatmap_calibration_source = mean_of_test_segment_windows`). **그림 전용이며 MAE/RMSE 에 쓰이지 않는다.**

측정 좌표와 Sionna 예측 좌표가 1 µm 이상 다르면 분석이 즉시 멈춘다.
현장에서 예비 좌표를 썼다면 `make_markers.py` → `run-sionna` 를 다시 돌린 뒤 분석한다.

## 10. GUI에서 확인하려면

```bash
conda run -n pgsr python -m tools.proxy_placement_editor.main edit \
  --room-obj    scenes/pnu_3f_corridor/proxy_mesh/complex_envelope/room_envelope_metric.obj \
  --room-json   scenes/pnu_3f_corridor/proxy_mesh/complex_envelope/room_envelope_metric.json \
  --calibration scenes/pnu_3f_corridor/proxy_mesh/complex_envelope/calibration.json \
  --scenario    scenes/pnu_3f_corridor/configs/sionna/proxy.yaml \
  --candidates  scenes/pnu_3f_corridor/configs/proxy_editor/candidates.yaml \
  --markers     scenes/pnu_3f_corridor/experiments/corridor3f_20260820/configs/tx_rx.json \
  --pgsr-output-mesh PGSR/output/pnu_3f_corridor/mesh/3f_corridor_blend.ply \
  --pgsr-output-mesh-coordinate-space scene \
  --output      scenes/pnu_3f_corridor/experiments/corridor3f_20260820/outputs/proxy_placement
```

TX/RX는 이미 이 좌표에 놓여 있다. GUI는 확인용이며, 마우스로 옮기면 좌표가 흐트러진다.
값을 바꿀 때는 속성 패널의 숫자 입력을 쓰고 저장 후 위 검증 명령을 다시 돌린다.