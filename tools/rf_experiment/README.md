# RFVisualizer 논문 실험 도구

## 한 줄 결론

실측 좌표, TX/RX Marker, Backend CSV, 세 비교 방법이 같은 계약을 사용하는지 Sionna나 GUI를 실행하기 전에 검증한다.

## 현재 상태

씬마다 아래 항목을 확정해야 Scene/Marker 계약이 `draft`에서 `ready`로 바뀐다.

- 좌표계: 출입문 왼쪽 아래 바닥점을 원점으로 하는 `+X/+Y/+Z`, meter, 오른손 좌표계 (예시 기준. 씬마다 원점·축은 TUTORIAL.md 7.1을 따라 새로 정한다)
- 실측 가로·깊이·바닥 높이차를 반영한 양의 좌표 기본 Envelope
- 계단·문·책상·AP 등 실측 장애물 배치 (미완성이면 Scene은 `draft`)
- TX 1개, 보정 RX 4개, Test RX 15개의 실제 좌표 (비어 있으면 Marker 계약은 `draft`)

## 접근 방식

기존 Phase 2-A/B/C 장면·Sionna 코드를 유지하고 그 위에 실험 전용 계약과 분석 계층을 추가한다. 기존 장면 산출물을 직접 덮어쓰지 않으므로 이전 연결 시험을 재현할 수 있고, 새 실측 좌표가 준비되기 전의 임시값이 논문 결과에 섞이는 것을 막는다.

## 계약 검증

```bash
python -m tools.rf_experiment.main validate-contracts \
  --scene scenes/<scene_id>/experiments/<session_id>/configs/scene.json \
  --markers scenes/<scene_id>/experiments/<session_id>/configs/tx_rx.json \
  --methods scenes/<scene_id>/experiments/<session_id>/configs/method_config.json
```

현재 명령은 구조 검증에는 성공하지만, Metric Proxy Scene과 Marker가 미완성이므로 `ready: false`와 경고를 출력하는 것이 정상이다. 현장 실행 직전에는 `--require-ready`를 추가하고 exit code 0을 확인한다.

```bash
python -m tools.rf_experiment.main validate-contracts \
  --scene scenes/<scene_id>/experiments/<session_id>/configs/scene.json \
  --markers scenes/<scene_id>/experiments/<session_id>/configs/tx_rx.json \
  --methods scenes/<scene_id>/experiments/<session_id>/configs/method_config.json \
  --require-ready
```

## 실측 기본 Envelope 재생성

```bash
python -m tools.rf_experiment.main build-proxy-envelope \
  --scene scenes/<scene_id>/experiments/<session_id>/configs/scene.json \
  --output scenes/<scene_id>/experiments/<session_id>/outputs/proxy_scene
```

출력은 기존 사진 추정 Metric 장면을 덮어쓰지 않는다. 새 OBJ/JSON/Calibration과 Top/Perspective 미리보기, 남은 가정을 기록한 보고서를 별도 경로에 만든다. PGSR 참조 정렬은 기존 Room corner를 사용한 affine 근사이며 최대 약 0.25m 오차가 있으므로, 물체의 실측 좌표를 대체하지 않는다.

## CSV 계약

Backend 출력은 계획 문서와 동일한 열 이름을 사용한다.

```bash
python -m tools.rf_experiment.main validate-csv \
  --kind raw \
  --csv scenes/<scene_id>/experiments/<session_id>/raw/measurements_raw.csv \
  --require-rows

python -m tools.rf_experiment.main validate-csv \
  --kind summary \
  --csv scenes/<scene_id>/experiments/<session_id>/processed/measurements_summary.csv \
  --require-rows
```

Raw 행은 `valid=false`일 때 RSSI 값이 비어 있어도 보존할 수 있다. Summary 행은 MAE·RMSE 입력이므로 좌표, 통계값, 장치 offset, `corrected_rssi`가 모두 유한한 숫자여야 한다.

## Proxy Scene과 TX/RX 통합 편집

문·계단 단·책상·AP/TX·RX는 모두 기존 Open3D `Proxy Placement Editor` 한 창에서 배치한다. AP는 물리 장애물이자 TX이며, 자유로운 3차원 위치와 회전·크기, 주파수·송신 세기를 함께 가진다. RX는 여러 개를 추가하고 3차원 이동 기즈모 또는 숫자 좌표로 배치하며 `point_id`와 `calibration`/`test` 역할을 지정한다.

```bash
conda run -n pgsr python -m tools.proxy_placement_editor.main edit \
  --room-obj scenes/<scene_id>/experiments/<session_id>/outputs/proxy_scene/room_envelope_metric.obj \
  --room-json scenes/<scene_id>/experiments/<session_id>/outputs/proxy_scene/room_envelope_metric.json \
  --calibration scenes/<scene_id>/experiments/<session_id>/outputs/proxy_scene/calibration.json \
  --scenario scenes/<scene_id>/configs/sionna/proxy_draft.yaml \
  --candidates scenes/<scene_id>/configs/proxy_editor/candidates.yaml \
  --markers scenes/<scene_id>/experiments/<session_id>/configs/tx_rx.json \
  --reference-mesh PGSR/output/<scene_id>/mesh/tsdf_fusion_post.ply \
  --reference-coordinate-space scene \
  --output scenes/<scene_id>/experiments/<session_id>/outputs/proxy_placement
```

`저장` 한 번으로 Scenario YAML과 TX/RX JSON을 함께 갱신한다. 실제 좌표를 입력하기 전에는 Marker 상태를 `draft`로 유지한다. AP/TX 1개·보정 RX 4개·Test RX 15개가 모두 입력되고 검토된 뒤에만 Marker 상태를 `ready`로 바꾼다. GUI 없는 검토가 필요하면 통합 편집기의 `export-preview --markers ...`를 사용한다.

## 세 방법 비교 분석

Backend Summary CSV, 위치별 Sionna 예측, 2D Grid Sionna 예측이 준비되면 같은 명령으로 지표와 그림을 다시 만든다.

```bash
python -m tools.rf_experiment.main analyze \
  --summary scenes/<scene_id>/experiments/<session_id>/processed/measurements_summary.csv \
  --sionna-points scenes/<scene_id>/experiments/<session_id>/processed/sionna_points.csv \
  --sionna-grid scenes/<scene_id>/experiments/<session_id>/processed/sionna_grid.csv \
  --methods scenes/<scene_id>/experiments/<session_id>/configs/method_config.json \
  --output scenes/<scene_id>/experiments/<session_id>
```

예측값 fitting에는 `calibration` 행만 사용하고, `test` 행은 MAE·RMSE 평가에만 사용한다. 출력에는 방법별 비교 CSV, 지표 CSV, 측정점 그림, 예측-실측 산점도, 동일한 색상 범위를 쓰는 히트맵 3장이 포함된다.

## Sionna 지점·격자 RSSI

실제 실행은 저장소의 검증 환경인 Sionna RT 1.2.2를 사용한다. 기본 모드는 Metric Proxy Envelope를 Sionna Scene으로 내보낸 뒤, RX 지점에는 PathSolver, 평면에는 RadioMapSolver를 실행한다.

```bash
conda run -n sionna python -m tools.rf_experiment.main run-sionna \
  --scene scenes/<scene_id>/experiments/<session_id>/configs/scene.json \
  --markers scenes/<scene_id>/experiments/<session_id>/configs/tx_rx.json \
  --solver scenes/<scene_id>/experiments/<session_id>/configs/sionna_solver.json \
  --output scenes/<scene_id>/experiments/<session_id>/sionna
```

위 명령은 Scene과 Marker가 모두 `ready`가 아니면 중단한다. 파이프라인 연결만 확인할 때는 실제 파일과 구분된 합성 Marker에 `--allow-draft`를 명시한다.

```bash
conda run -n sionna python -m tools.rf_experiment.main run-sionna \
  --scene scenes/<scene_id>/experiments/<session_id>/configs/scene.json \
  --markers scenes/<scene_id>/experiments/<session_id>/configs/dry_run/tx_rx_synthetic.json \
  --solver scenes/<scene_id>/experiments/<session_id>/configs/sionna_solver.json \
  --output scenes/<scene_id>/experiments/<session_id>/outputs/sionna_dry_run \
  --allow-draft
```

지점 예측은 유효 경로의 복소 진폭에 대해 `sum(|a|²)`를 사용한다. 지점과 Grid 모두 `TX 출력(dBm) + 10log10(path gain)`으로 변환하며, Grid에서는 이 값이 Sionna의 `RadioMap.rss`와 허용 오차 안에서 같은지도 검사한다. 장애물 Scene이 완성되면 `--scene-xml`로 해당 Scene을 넘겨 같은 출력 계약을 유지한다.

전체 연결 시험은 4개 보정점과 15개 Test점을 가진 별도 합성 Marker로 수행한다. 다음 Summary 생성 명령은 Sionna 값에 고정 잔차를 더할 뿐이며, 출력 파일과 보고서 모두 논문 근거로 사용할 수 없다고 표시한다.

```bash
python -m tools.rf_experiment.main generate-synthetic-summary \
  --sionna-points scenes/<scene_id>/experiments/<session_id>/outputs/end_to_end_dry_run/sionna/processed/sionna_points.csv \
  --output scenes/<scene_id>/experiments/<session_id>/outputs/end_to_end_dry_run/measurements_summary_synthetic.csv
```

## 다음 연결

1. Proxy Placement Editor에서 기본 Envelope 위에 계단·문·주요 책상을 배치한다.
2. 같은 편집기에서 AP/TX와 현장 실측 RX 좌표를 입력하고 `ready`로 전환한다.
3. Sionna의 선형 path gain을 `송신 전력 + 10log10(path gain)`으로 dBm 예측값으로 변환한다.
4. 실제 Summary CSV와 예측값으로 분석 명령을 실행한다.
