# RFVisualizer 실험 분석 결과

## 한 줄 결론

**SYNTHETIC DRY RUN ONLY — 이 수치와 그림은 논문 근거로 사용할 수 없다.**

| 방법 | MAE (dB) | RMSE (dB) |
|---|---:|---:|
| raw_sionna | 4.000000 | 4.000000 |
| plain_idw | 2.277813 | 2.983448 |
| residual_idw | 0.000000 | 0.000000 |

## 검증

- IDW와 Residual IDW fitting에는 calibration 위치만 사용했다.
- Test 실제값은 지표 계산에만 사용했다.
- 세 히트맵은 `-112.028`–`17.725` dBm의 동일한 색상 범위를 사용했다.
