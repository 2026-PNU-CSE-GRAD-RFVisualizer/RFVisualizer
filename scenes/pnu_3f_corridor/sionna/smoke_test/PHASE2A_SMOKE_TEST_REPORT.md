# Phase 2-A Sionna RT Empty-Room Smoke Test

> **PROVISIONAL — NOT PHYSICALLY VALIDATED**

## 결론

- 전체 상태: **통과**
- Sionna RT: `1.2.2`
- Mitsuba: `3.8.0` / variant: `cuda_ad_mono_polarized`
- GPU backend: `True`

## 장면

- 객체: `3` / 삼각형: `1640`
- Bounds: `{'min': [0.0, 0.0, 0.0], 'max': [44.906373, 20.922287, 3.0], 'extent': [44.906373, 20.922287, 3.0]}`
- 재질: `['radio_itu_concrete_floor', 'radio_itu_concrete_ceiling', 'radio_itu_concrete_walls']`

## TX/RX

- `tx_test`: `[21.37, 17.83, 0.8]` — floor `0.800m`, ceiling `2.200m`, wall `3.092m` 여유
- `rx_los`: `[12.57, 17.83, 0.45]` — floor `0.450m`, ceiling `2.550m`, wall `3.092m` 여유
- `rx_reflection`: `[30.1, 17.83, 0.45]` — floor `0.450m`, ceiling `2.550m`, wall `2.723m` 여유
- `rx_nlos`: `[20.04, 5.31, 0.45]` — floor `0.450m`, ceiling `2.550m`, wall `0.717m` 여유

## LoS

- Path count: `1` / LoS: `1`
- Euclidean: `8.80695748m` / Sionna: `8.80695789m`
- 거리 오차: `4.12275e-07m`

## Reflection

- Path count: `91811` / reflection: `206`
- 최대 interaction: `5` / 상태: `pass`

## Coverage

- Grid: `[20, 44]` / cell: `[1.0, 1.0]`m
- Inside/valid: `456/323` / valid ratio: `70.83%`
- Path gain dB min/mean/max: `-140.431 / -64.536 / -35.078`

## 성능

- `environment_diagnosis`: `1.41033s`
- `scene_export`: `0.00892532s`
- `sionna_scene_load`: `0.031866s`
- `los_path_solve`: `0.0253202s`
- `reflection_path_solve`: `0.315649s`
- `coverage_solve`: `0.0145748s`
- `total_before_report`: `7.32927s`

## 경고

- PROVISIONAL SCALE — NOT PHYSICALLY VALIDATED
- 현재 재질은 실제 강의실 측정값이 아닌 Sionna ITU concrete preset입니다.

## 생성 파일

- `environment_json`: `/data/RFVisualizer_Workspace/RFVisualizer/scenes/pnu_3f_corridor/sionna/smoke_test/environment.json`
- `resolved_config_yaml`: `/data/RFVisualizer_Workspace/RFVisualizer/scenes/pnu_3f_corridor/sionna/smoke_test/resolved_config.yaml`
- `resolved_positions_json`: `/data/RFVisualizer_Workspace/RFVisualizer/scenes/pnu_3f_corridor/sionna/smoke_test/resolved_positions.json`
- `resolved_positions_scene_json`: `/data/RFVisualizer_Workspace/RFVisualizer/scenes/pnu_3f_corridor/sionna/smoke_test/resolved_positions_scene.json`
- `materials_resolved_json`: `/data/RFVisualizer_Workspace/RFVisualizer/scenes/pnu_3f_corridor/sionna/smoke_test/materials_resolved.json`
- `scene_manifest_json`: `/data/RFVisualizer_Workspace/RFVisualizer/scenes/pnu_3f_corridor/sionna/smoke_test/scene_manifest.json`
- `scene_xml`: `/data/RFVisualizer_Workspace/RFVisualizer/scenes/pnu_3f_corridor/sionna/smoke_test/scene/scene.xml`
- `scene_preview_png`: `/data/RFVisualizer_Workspace/RFVisualizer/scenes/pnu_3f_corridor/sionna/smoke_test/scene_preview.png`
- `paths_los_json`: `/data/RFVisualizer_Workspace/RFVisualizer/scenes/pnu_3f_corridor/sionna/smoke_test/paths/paths_los.json`
- `paths_los_csv`: `/data/RFVisualizer_Workspace/RFVisualizer/scenes/pnu_3f_corridor/sionna/smoke_test/paths/paths_los.csv`
- `paths_reflection_json`: `/data/RFVisualizer_Workspace/RFVisualizer/scenes/pnu_3f_corridor/sionna/smoke_test/paths/paths_reflection.json`
- `paths_reflection_csv`: `/data/RFVisualizer_Workspace/RFVisualizer/scenes/pnu_3f_corridor/sionna/smoke_test/paths/paths_reflection.csv`
- `coverage_values_npy`: `/data/RFVisualizer_Workspace/RFVisualizer/scenes/pnu_3f_corridor/sionna/smoke_test/coverage/coverage_values.npy`
- `coverage_values_csv`: `/data/RFVisualizer_Workspace/RFVisualizer/scenes/pnu_3f_corridor/sionna/smoke_test/coverage/coverage_values.csv`
- `coverage_valid_mask_npy`: `/data/RFVisualizer_Workspace/RFVisualizer/scenes/pnu_3f_corridor/sionna/smoke_test/coverage/coverage_valid_mask.npy`
- `coverage_metadata_json`: `/data/RFVisualizer_Workspace/RFVisualizer/scenes/pnu_3f_corridor/sionna/smoke_test/coverage/coverage_metadata.json`
- `coverage_map_png`: `/data/RFVisualizer_Workspace/RFVisualizer/scenes/pnu_3f_corridor/sionna/smoke_test/coverage/coverage_map.png`
- `coverage_points_metric_csv`: `/data/RFVisualizer_Workspace/RFVisualizer/scenes/pnu_3f_corridor/sionna/smoke_test/coverage/coverage_points_metric.csv`
- `coverage_points_scene_csv`: `/data/RFVisualizer_Workspace/RFVisualizer/scenes/pnu_3f_corridor/sionna/smoke_test/coverage/coverage_points_scene.csv`
- `smoke_test_validation_json`: `/data/RFVisualizer_Workspace/RFVisualizer/scenes/pnu_3f_corridor/sionna/smoke_test/smoke_test_validation.json`
- `report_markdown`: `/data/RFVisualizer_Workspace/RFVisualizer/scenes/pnu_3f_corridor/sionna/smoke_test/PHASE2A_SMOKE_TEST_REPORT.md`
