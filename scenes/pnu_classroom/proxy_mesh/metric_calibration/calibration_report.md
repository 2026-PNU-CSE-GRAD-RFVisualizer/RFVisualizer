# Phase 1.5-C Metric Calibration 결과

> **PROVISIONAL METRIC CALIBRATION - NOT VALIDATED BY ON-SITE MEASUREMENT**

## 결론

- 전체 검증: **통과**
- 상태: `provisional` / 신뢰도: `low`
- 단일 배율: `1.54362462312 m/scene unit`
- 기준 간 차이: `8.1512%` (`warning`)

## 표준 좌표 프레임

- 원점 corner: `0`
- X축 edge: `[2, 3]`
- 회전 행렬식: `1`
- 행렬 역변환 오차: `1.11022e-15`
- 점 왕복 오차: `2.9142e-15`

## 실제 크기 형상

- Bounds min: `[-15.314045186589079, -10.918306217554669, -6.613381096140029e-13]`
- Bounds max: `[0.2611781972069167, 0.18352873204145628, 2.9894680544053616]`
- 표면적: `441.537647 m²`
- 부피: `370.159239 m³`
- 높이 min/mean/max: `2.08040958 / 2.2868796 / 2.47915857 m`

## 기준별 오차

- `two_door_total_width`: `+0.0861438459 m` (`+4.3072%`)
- `door_height`: `-0.0849672193 m` (`-3.8621%`)

## 검증

- 최대 평면 오차: `3.55271e-15`
- 위상 보존: `True`
- 면적·부피 배율 검증: `True`
- OBJ 객체·그룹·재질·면 보존: `True`

## 경고

- PROVISIONAL METRIC CALIBRATION - NOT VALIDATED BY ON-SITE MEASUREMENT
- Scale reference spread가 warning 기준을 넘었습니다: 8.15%

## 생성 파일

- `metric_obj`: `/data/RFVisualizer/outputs/proxy_mesh/pnu_classroom/metric_calibration/room_envelope_metric.obj`
- `metric_mtl`: `/data/RFVisualizer/outputs/proxy_mesh/pnu_classroom/metric_calibration/room_envelope_metric.mtl`
- `metric_ply`: `/data/RFVisualizer/outputs/proxy_mesh/pnu_classroom/metric_calibration/room_envelope_metric.ply`
- `metric_coordinate_axes_ply`: `/data/RFVisualizer/outputs/proxy_mesh/pnu_classroom/metric_calibration/metric_coordinate_axes.ply`
- `metric_envelope_json`: `/data/RFVisualizer/outputs/proxy_mesh/pnu_classroom/metric_calibration/room_envelope_metric.json`
- `calibration_json`: `/data/RFVisualizer/outputs/proxy_mesh/pnu_classroom/metric_calibration/calibration.json`
- `calibration_report`: `/data/RFVisualizer/outputs/proxy_mesh/pnu_classroom/metric_calibration/calibration_report.md`
- `calibration_validation_json`: `/data/RFVisualizer/outputs/proxy_mesh/pnu_classroom/metric_calibration/calibration_validation.json`
