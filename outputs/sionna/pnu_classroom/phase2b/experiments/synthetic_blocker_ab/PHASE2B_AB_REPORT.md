# RFVisualizer Phase 2-B Synthetic Blocker A/B Report

> **SYNTHETIC / PROVISIONAL / NOT PHYSICALLY VALIDATED**  

> 이 결과는 장애물 계층과 A/B 파이프라인 검증용이며 실제 강의실 RSSI 정확도를 뜻하지 않습니다.

## Environment

- Python: `3.10.20`
- Sionna RT: `1.2.2`
- Mitsuba / Dr.Jit: `3.8.0` / `1.3.1`
- Mitsuba variant: `cuda_ad_mono_polarized`
- GPU: `NVIDIA GeForce RTX 4090`

## Baseline reproducibility

- Repeat count: `2`
- Path structure stable: `True`
- Coverage mean / p95 / max repeat delta: `7.92816e-07` / `2.35347e-06` / `5.19878e-06` dB
- Noise floor: `5.19878e-06` dB
- Within declared numerical tolerance: `True`

## Synthetic obstacle

- ID: `blocker_panel_000`
- Geometry: `box` / bounds `[-5.075, -6.25, 0.2598064196869294]` ~ `[-4.925, -3.75, 2.2598064196869294]` m
- Material: `wood` (`itu_wood_blocker_panel_000`)
- Minimum floor / ceiling / wall clearance: 0.0114919 / 0.141463 / 3.47648 m
- Configured LoS intersection: `True`

## Scene composition

- Baseline objects / triangles: `6` / `12`
- Variant objects / triangles: `7` / `24`
- Independent shapes (`merge_shapes=false`): `True`

## Path A/B

- Baseline `rx_los` LoS: `True` (1 path)
- Variant `rx_los` LoS: `False` (0 path)
- Total path count delta: `-18`
- Specular reflection path count delta: `-17`
- Blocker interaction path count: `0`
- Blocker-related evidence: `True` (`['los_presence_or_count_changed']`)

## Coverage A/B

- Grid / common valid cells: `[11, 15]` / `151`
- Mean / mean absolute delta: `-1.01171` / `1.01171` dB
- Minimum / maximum delta: `-8.42628` / `-8.31062e-05` dB
- `|delta| > 1 dB` / `> 3 dB`: `48` / `6` cells
- A/B change exceeds baseline noise: `True`

## Coordinate bridge

- Metric ↔ PGSR maximum round-trip error: `1.98603e-15`
- Obstacle metric and PGSR vertices: `variant/obstacles_metric.json`, `variant/obstacles_scene.json`

## Performance

- Baseline first path / coverage solve: `0.087678` / `0.00464486` s
- Variant path / coverage solve: `0.0598407` / `0.00283294` s
- Comparison compute / export: `0.0107193` / `1.16731` s
- Total before report: `2.20418` s

## Validation

- Overall success: `True`
- Detailed checks: `experiment_validation.json`
- Reproducibility: `reproducibility.json`
- Path comparison: `path_comparison.json`
- Coverage comparison: `coverage_comparison.json`

## Limitations

- 장애물은 검증 전용 synthetic box이며 실제 책상·칠판·문 위치를 나타내지 않습니다.
- Room scale과 RF material은 provisional이며 현장 실측으로 검증되지 않았습니다.
- 실제 RSSI, 고해상도 Radio Map, Viewer/실시간 기능은 이번 범위가 아닙니다.
