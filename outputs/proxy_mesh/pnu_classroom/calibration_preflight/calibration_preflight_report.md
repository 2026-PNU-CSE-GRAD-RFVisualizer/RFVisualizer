# Metric Calibration Preflight 진단 보고서

## 결론

- Preflight 상태: **통과**
- Geometry 상하 관계: `geometry_internal_up_consistent`
- Scale 상태: `warning`

## Up 방향

- Scene up: `[0.09550108776358447, -0.9916112945169672, -0.0871009920859498]`
- Floor 중심: `[0.6584322631425849, 0.8833112256648098, 0.2958726163700762]`
- Ceiling 중심: `[0.6638645004924146, -0.5977787034324638, 0.15447893364037557]`
- 중심 높이 차이: `1.48149982`
- Corner 높이: `[1.347743194, 1.373235895, 1.606063113, 1.598957065]`
- MeshLab 진단: Geometry 내부 상하 관계는 정상입니다. MeshLab에서 뒤집혀 보인다면 viewer 축 convention과 scene up 축 차이일 가능성이 높습니다.

### 원인별 판정

- 형상 내부 상하 관계 정상: `True`
- 화면 도구의 축 기준 차이 가능성: `True`
- Scene up 부호 문제 의심: `False`
- 바닥·천장 또는 corner 대응 문제 의심: `False`

## Proper Rotation

- 회전 각도: `94.996851도`
- Determinant: `1`
- Up 정렬 오차: `2.0313e-16`
- 직교 오차: `1.11022e-16`
- 왕복 오차: `1.77982e-15`

## Provisional Scale

- `two_door_total_width`: `1.47988321 m/scene unit`
- `door_height`: `1.60563666 m/scene unit`

추천 배율을 적용했을 때의 기준별 오차:

- `two_door_total_width`: `+0.0861438459 m` (`+4.3072%`)
- `door_height`: `-0.0849672193 m` (`-3.8621%`)

- 추천 추정기: `weighted_least_squares`
- 추천 단일 축척: `1.54362462 m/scene unit`
- 기준 간 상대 차이: `8.1512%`

## 좌표 프레임 후보

- 추천 원점 corner: `0`
- 추천 X축 edge: `2 → 3`
- 추천 수평 방향: `[-0.7012134455380385, -0.12912166340165435, 0.7011613935728792]`

## 미해결 경고

- Scale references are estimated and must be replaced after on-site measurement.
- Scale reference spread가 warning 기준을 넘었습니다: 8.15%
- Geometry 내부 상하 관계는 정상입니다. MeshLab에서 뒤집혀 보인다면 viewer 축 convention과 scene up 축 차이일 가능성이 높습니다.

## 생성 파일

- `rotation_only_obj`: `/data/RFVisualizer/outputs/proxy_mesh/pnu_classroom/calibration_preflight/room_envelope_up_aligned.obj`
- `rotation_only_ply`: `/data/RFVisualizer/outputs/proxy_mesh/pnu_classroom/calibration_preflight/room_envelope_up_aligned.ply`
- `coordinate_axes_ply`: `/data/RFVisualizer/outputs/proxy_mesh/pnu_classroom/calibration_preflight/coordinate_axes.ply`
- `scale_analysis_csv`: `/data/RFVisualizer/outputs/proxy_mesh/pnu_classroom/calibration_preflight/scale_analysis.csv`
- `metric_calibration_draft`: `/data/RFVisualizer/outputs/proxy_mesh/pnu_classroom/calibration_preflight/pnu_classroom_metric_calibration_draft.yaml`
- `markdown_report`: `/data/RFVisualizer/outputs/proxy_mesh/pnu_classroom/calibration_preflight/calibration_preflight_report.md`
- `preflight_json`: `/data/RFVisualizer/outputs/proxy_mesh/pnu_classroom/calibration_preflight/calibration_preflight.json`
