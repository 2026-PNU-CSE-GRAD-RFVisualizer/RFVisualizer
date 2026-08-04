# Phase 1.5-C Metric Calibration 결과

> **PROVISIONAL METRIC CALIBRATION - NOT VALIDATED BY ON-SITE MEASUREMENT**

## 결론

- 전체 검증: **통과**
- 상태: `provisional` / 신뢰도: `medium`
- 단일 배율: `1.48459329525 m/scene unit`
- 기준 간 차이: `0.0000%` (`pass`)

## 표준 좌표 프레임

- 원점 corner: `0`
- X축 edge: `[3, 4]`
- 회전 행렬식: `1`
- 행렬 역변환 오차: `1.16573e-15`
- 점 왕복 오차: `2.67377e-15`

## 실제 크기 형상

- Bounds min: `[-3.1136113215661213e-12, -16.34245309810102, -1.2568618442363706]`
- Bounds max: `[11.800000000004248, 1.911553178683967e-12, 2.630153839305454]`
- 표면적: `439.485969 m²`
- 부피: `382.491383 m³`
- 높이 min/mean/max: `2.56265891 / 2.61411151 / 2.69369317 m`

## 기준별 오차

- `floorplan_bottom_corridor_length`: `+1.77635684e-15 m` (`+0.0000%`)
- `floorplan_top_corridor_length`: `+8.8817842e-16 m` (`+0.0000%`)
- `floorplan_bottom_corridor_width`: `+8.8817842e-16 m` (`+0.0000%`)

## 검증

- 최대 평면 오차: `3.55271e-15`
- 위상 보존: `True`
- 면적·부피 배율 검증: `True`
- OBJ 객체·그룹·재질·면 보존: `True`

## 경고

- PROVISIONAL METRIC CALIBRATION - NOT VALIDATED BY ON-SITE MEASUREMENT

## 생성 파일

- `metric_obj`: `/data/RFVisualizer/outputs/proxy_mesh/4f_corridor/floorplan_aligned/metric_calibration/room_envelope_metric.obj`
- `metric_mtl`: `/data/RFVisualizer/outputs/proxy_mesh/4f_corridor/floorplan_aligned/metric_calibration/room_envelope_metric.mtl`
- `metric_ply`: `/data/RFVisualizer/outputs/proxy_mesh/4f_corridor/floorplan_aligned/metric_calibration/room_envelope_metric.ply`
- `metric_coordinate_axes_ply`: `/data/RFVisualizer/outputs/proxy_mesh/4f_corridor/floorplan_aligned/metric_calibration/metric_coordinate_axes.ply`
- `metric_envelope_json`: `/data/RFVisualizer/outputs/proxy_mesh/4f_corridor/floorplan_aligned/metric_calibration/room_envelope_metric.json`
- `calibration_json`: `/data/RFVisualizer/outputs/proxy_mesh/4f_corridor/floorplan_aligned/metric_calibration/calibration.json`
- `calibration_report`: `/data/RFVisualizer/outputs/proxy_mesh/4f_corridor/floorplan_aligned/metric_calibration/calibration_report.md`
- `calibration_validation_json`: `/data/RFVisualizer/outputs/proxy_mesh/4f_corridor/floorplan_aligned/metric_calibration/calibration_validation.json`
