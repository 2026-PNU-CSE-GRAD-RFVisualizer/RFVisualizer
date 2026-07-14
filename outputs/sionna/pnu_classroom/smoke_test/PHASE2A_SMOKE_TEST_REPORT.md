# Phase 2-A Sionna RT Empty-Room Smoke Test

> **PROVISIONAL — NOT PHYSICALLY VALIDATED**

## 결론

- 전체 상태: **통과**
- Sionna RT: `1.2.2`
- Mitsuba: `3.8.0` / variant: `cuda_ad_mono_polarized`
- GPU backend: `True`

## 장면

- 객체: `6` / 삼각형: `12`
- Bounds: `{'min': [-15.3140451866, -10.9183062176, -6.61338109614e-13], 'max': [0.261178197207, 0.183528732041, 2.98946805441], 'extent': [15.575223383807, 11.101834949640999, 2.9894680544106613]}`
- 재질: `['itu_concrete_floor', 'itu_concrete_ceiling', 'itu_concrete_walls']`

## TX/RX

- `tx_test`: `[-7.0, -5.0, 1.5]` — floor `1.266m`, ceiling `1.009m`, wall `4.719m` 여유
- `rx_los`: `[-3.0, -5.0, 1.5]` — floor `1.314m`, ceiling `0.959m`, wall `3.127m` 여유
- `rx_reflection`: `[-10.0, -8.0, 1.5]` — floor `1.141m`, ceiling `1.243m`, wall `2.854m` 여유

## LoS

- Path count: `1` / LoS: `1`
- Euclidean: `4m` / Sionna: `3.99999991m`
- 거리 오차: `9.27644e-08m`

## Reflection

- Path count: `26` / reflection: `25`
- 최대 interaction: `2` / 상태: `pass`

## Coverage

- Grid: `[11, 15]` / cell: `[1.0, 1.0]`m
- Inside/valid: `151/151` / valid ratio: `100.00%`
- Path gain dB min/mean/max: `-61.064 / -58.664 / -20.772`

## 성능

- `environment_diagnosis`: `1.40537s`
- `scene_export`: `0.00179381s`
- `sionna_scene_load`: `0.164963s`
- `los_path_solve`: `0.0718094s`
- `reflection_path_solve`: `0.0934344s`
- `coverage_solve`: `0.00439507s`
- `total_before_report`: `2.02823s`

## 경고

- PROVISIONAL SCALE — NOT PHYSICALLY VALIDATED
- 현재 재질은 실제 강의실 측정값이 아닌 Sionna ITU concrete preset입니다.

## 생성 파일

- `environment_json`: `/data/RFVisualizer/outputs/sionna/pnu_classroom/smoke_test/environment.json`
- `resolved_config_yaml`: `/data/RFVisualizer/outputs/sionna/pnu_classroom/smoke_test/resolved_config.yaml`
- `resolved_positions_json`: `/data/RFVisualizer/outputs/sionna/pnu_classroom/smoke_test/resolved_positions.json`
- `resolved_positions_scene_json`: `/data/RFVisualizer/outputs/sionna/pnu_classroom/smoke_test/resolved_positions_scene.json`
- `materials_resolved_json`: `/data/RFVisualizer/outputs/sionna/pnu_classroom/smoke_test/materials_resolved.json`
- `scene_manifest_json`: `/data/RFVisualizer/outputs/sionna/pnu_classroom/smoke_test/scene_manifest.json`
- `scene_xml`: `/data/RFVisualizer/outputs/sionna/pnu_classroom/smoke_test/scene/scene.xml`
- `scene_preview_png`: `/data/RFVisualizer/outputs/sionna/pnu_classroom/smoke_test/scene_preview.png`
- `paths_los_json`: `/data/RFVisualizer/outputs/sionna/pnu_classroom/smoke_test/paths/paths_los.json`
- `paths_los_csv`: `/data/RFVisualizer/outputs/sionna/pnu_classroom/smoke_test/paths/paths_los.csv`
- `paths_reflection_json`: `/data/RFVisualizer/outputs/sionna/pnu_classroom/smoke_test/paths/paths_reflection.json`
- `paths_reflection_csv`: `/data/RFVisualizer/outputs/sionna/pnu_classroom/smoke_test/paths/paths_reflection.csv`
- `coverage_values_npy`: `/data/RFVisualizer/outputs/sionna/pnu_classroom/smoke_test/coverage/coverage_values.npy`
- `coverage_values_csv`: `/data/RFVisualizer/outputs/sionna/pnu_classroom/smoke_test/coverage/coverage_values.csv`
- `coverage_valid_mask_npy`: `/data/RFVisualizer/outputs/sionna/pnu_classroom/smoke_test/coverage/coverage_valid_mask.npy`
- `coverage_metadata_json`: `/data/RFVisualizer/outputs/sionna/pnu_classroom/smoke_test/coverage/coverage_metadata.json`
- `coverage_map_png`: `/data/RFVisualizer/outputs/sionna/pnu_classroom/smoke_test/coverage/coverage_map.png`
- `coverage_points_metric_csv`: `/data/RFVisualizer/outputs/sionna/pnu_classroom/smoke_test/coverage/coverage_points_metric.csv`
- `coverage_points_scene_csv`: `/data/RFVisualizer/outputs/sionna/pnu_classroom/smoke_test/coverage/coverage_points_scene.csv`
- `smoke_test_validation_json`: `/data/RFVisualizer/outputs/sionna/pnu_classroom/smoke_test/smoke_test_validation.json`
- `report_markdown`: `/data/RFVisualizer/outputs/sionna/pnu_classroom/smoke_test/PHASE2A_SMOKE_TEST_REPORT.md`
