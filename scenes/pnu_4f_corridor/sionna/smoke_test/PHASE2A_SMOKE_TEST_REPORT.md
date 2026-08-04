# Phase 2-A Sionna RT Empty-Room Smoke Test

> **PROVISIONAL — NOT PHYSICALLY VALIDATED**

## 결론

- 전체 상태: **통과**
- Sionna RT: `1.2.2`
- Mitsuba: `3.8.0` / variant: `cuda_ad_mono_polarized`
- GPU backend: `True`

## 장면

- 객체: `10` / 삼각형: `28`
- Bounds: `{'min': [-0.0, -0.0, 0.0], 'max': [11.8, 16.3424530981, 2.61411151404], 'extent': [11.8, 16.3424530981, 2.61411151404]}`
- 재질: `['itu_concrete_floor', 'itu_concrete_ceiling', 'itu_concrete_walls']`

## TX/RX

- `tx_01`: `[3.15, 0.5, 0.45]` — floor `0.450m`, ceiling `2.164m`, wall `0.500m` 여유
- `cal_rx_01`: `[3.13, 3.93, 0.45]` — floor `0.450m`, ceiling `2.164m`, wall `3.130m` 여유

## LoS

- Path count: `1` / LoS: `1`
- Euclidean: `3.43005831m` / Sionna: `3.43005816m`
- 거리 오차: `1.50356e-07m`

## Reflection

- Path count: `24` / reflection: `23`
- 최대 interaction: `2` / 상태: `pass`

## Coverage

- Grid: `[31, 22]` / cell: `[0.5, 0.5]`m
- Inside/valid: `628/617` / valid ratio: `98.25%`
- Path gain dB min/mean/max: `-82.667 / -61.016 / -15.682`

## 성능

- `environment_diagnosis`: `1.60621s`
- `scene_export`: `0.00253376s`
- `sionna_scene_load`: `0.0401364s`
- `los_path_solve`: `0.018834s`
- `reflection_path_solve`: `0.0141592s`
- `coverage_solve`: `0.00473882s`
- `total_before_report`: `2.00555s`

## 경고

- PROVISIONAL SCALE — NOT PHYSICALLY VALIDATED
- 현재 재질은 실제 강의실 측정값이 아닌 Sionna ITU concrete preset입니다.

## 생성 파일

- `environment_json`: `/data/RFVisualizer/outputs/sionna_smoke_test/pnu_4f_corridor/environment.json`
- `resolved_config_yaml`: `/data/RFVisualizer/outputs/sionna_smoke_test/pnu_4f_corridor/resolved_config.yaml`
- `resolved_positions_json`: `/data/RFVisualizer/outputs/sionna_smoke_test/pnu_4f_corridor/resolved_positions.json`
- `resolved_positions_scene_json`: `/data/RFVisualizer/outputs/sionna_smoke_test/pnu_4f_corridor/resolved_positions_scene.json`
- `materials_resolved_json`: `/data/RFVisualizer/outputs/sionna_smoke_test/pnu_4f_corridor/materials_resolved.json`
- `scene_manifest_json`: `/data/RFVisualizer/outputs/sionna_smoke_test/pnu_4f_corridor/scene_manifest.json`
- `scene_xml`: `/data/RFVisualizer/outputs/sionna_smoke_test/pnu_4f_corridor/scene/scene.xml`
- `scene_preview_png`: `/data/RFVisualizer/outputs/sionna_smoke_test/pnu_4f_corridor/scene_preview.png`
- `paths_los_json`: `/data/RFVisualizer/outputs/sionna_smoke_test/pnu_4f_corridor/paths/paths_los.json`
- `paths_los_csv`: `/data/RFVisualizer/outputs/sionna_smoke_test/pnu_4f_corridor/paths/paths_los.csv`
- `paths_reflection_json`: `/data/RFVisualizer/outputs/sionna_smoke_test/pnu_4f_corridor/paths/paths_reflection.json`
- `paths_reflection_csv`: `/data/RFVisualizer/outputs/sionna_smoke_test/pnu_4f_corridor/paths/paths_reflection.csv`
- `coverage_values_npy`: `/data/RFVisualizer/outputs/sionna_smoke_test/pnu_4f_corridor/coverage/coverage_values.npy`
- `coverage_values_csv`: `/data/RFVisualizer/outputs/sionna_smoke_test/pnu_4f_corridor/coverage/coverage_values.csv`
- `coverage_valid_mask_npy`: `/data/RFVisualizer/outputs/sionna_smoke_test/pnu_4f_corridor/coverage/coverage_valid_mask.npy`
- `coverage_metadata_json`: `/data/RFVisualizer/outputs/sionna_smoke_test/pnu_4f_corridor/coverage/coverage_metadata.json`
- `coverage_map_png`: `/data/RFVisualizer/outputs/sionna_smoke_test/pnu_4f_corridor/coverage/coverage_map.png`
- `coverage_points_metric_csv`: `/data/RFVisualizer/outputs/sionna_smoke_test/pnu_4f_corridor/coverage/coverage_points_metric.csv`
- `coverage_points_scene_csv`: `/data/RFVisualizer/outputs/sionna_smoke_test/pnu_4f_corridor/coverage/coverage_points_scene.csv`
- `smoke_test_validation_json`: `/data/RFVisualizer/outputs/sionna_smoke_test/pnu_4f_corridor/smoke_test_validation.json`
- `report_markdown`: `/data/RFVisualizer/outputs/sionna_smoke_test/pnu_4f_corridor/PHASE2A_SMOKE_TEST_REPORT.md`
