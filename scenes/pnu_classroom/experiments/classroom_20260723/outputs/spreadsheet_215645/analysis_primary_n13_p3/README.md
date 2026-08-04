# RFVisualizer 실험 분석 결과

## 한 줄 결론

**DRAFT SIONNA INPUT — 초안 Scene 결과이므로 논문 근거로 사용할 수 없다.**

| 방법 | MAE (dB) | RMSE (dB) |
|---|---:|---:|
| raw_sionna | 7.687015 | 9.066212 |
| plain_idw | 6.501562 | 7.210067 |
| residual_idw | 6.557850 | 7.458272 |

## 검증

- IDW와 Residual IDW fitting에는 calibration 위치만 사용했다.
- Test 실제값은 지표 계산에만 사용했다.
- 세 히트맵은 `-93.021`–`-11.731` dBm의 동일한 색상 범위를 사용했다.
