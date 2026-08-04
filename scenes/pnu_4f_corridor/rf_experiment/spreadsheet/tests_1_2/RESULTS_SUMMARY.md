# PNU 4F Corridor Test 1·2 결과

## 한 줄 결론

회절+산란 Raw Sionna의 6개 Test 위치 MAE는 **13.60 dB**, 네 Calibration 위치를 모두 쓴 전역 편향 보정 후에는 **8.08 dB**다. Test 3은 철문 상태가 달라 제외했다.

## 최종 비교

| 결과 | MAE (dB) | RMSE (dB) | Pearson r |
|---|---:|---:|---:|
| 단순 Sionna RT: 회절+산란 | 13.60 | 14.03 | 0.972 |
| Calibration 보정: all-4 global bias | 8.08 | 8.78 | 0.972 |

- 주 평가는 Test 1·2의 같은 위치를 먼저 평균한 **6개 독립 위치** 기준이다.
- 보정 MAE의 위치 bootstrap 95% 구간은 **5.14–10.68 dB**다.
- 12개 반복 관측을 그대로 합친 MAE는 Raw **13.60 dB**, 보정 **8.53 dB**다.

## Held-out Test 실제값 vs 예측값

| 위치 | 실제 평균 (dBm) | Raw Sionna (dBm) | 보정 Sionna (dBm) | 보정 절대오차 (dB) |
|---|---:|---:|---:|---:|
| test-01 | -41.50 | -30.01 | -35.53 | 5.97 |
| test-02 | -38.00 | -30.59 | -36.10 | 1.90 |
| test-03 | -49.00 | -34.35 | -39.87 | 9.13 |
| test-04 | -58.00 | -41.52 | -47.04 | 10.96 |
| test-05 | -66.50 | -48.49 | -54.01 | 12.49 |
| test-06 | -64.25 | -50.72 | -56.24 | 8.01 |

## Solver 비교

| Solver | 방법 | 6개 위치 MAE (dB) | RMSE (dB) |
|---|---|---:|---:|
| base | raw_sionna | 13.29 | 13.69 |
| base | global_bias_all4 | 7.85 | 8.51 |
| diffraction | raw_sionna | 13.72 | 14.17 |
| diffraction | global_bias_all4 | 8.12 | 8.85 |
| diffraction_scattering_s020 | raw_sionna | 13.60 | 14.03 |
| diffraction_scattering_s020 | global_bias_all4 | 8.08 | 8.78 |

회절·산란은 유효 경로와 격자 범위를 늘렸지만 Test 정확도는 Base보다 근소하게 낮았다. 그 차이는 반복 측정 오차보다 훨씬 작아 우열 근거로 쓰기 어렵다.

## 신뢰도 제한

- 장치 보정 뒤 Calibration 반복 차이는 평균 **10.25 dB**, 최대 **16.00 dB**다. 5 dB 이내인 점은 `cal-04` 하나뿐이다.
- Test 1·2 동일 위치의 평균 절대 차이는 **6.08 dB**, 최대 **13.00 dB**다.
- 실측 TX x=3.13 m와 Sionna TX x=3.15 m 사이에 0.02 m 차이가 있다.
- 따라서 개별 위치의 절대 RSSI 신뢰도는 낮고, 큰 공간 경향의 신뢰도만 중간 수준으로 해석한다.
- Scene/Marker와 산란계수 0.20은 아직 provisional이므로 논문 확정 수치로 사용하지 않는다.
