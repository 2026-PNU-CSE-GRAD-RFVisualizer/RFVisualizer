# PNU 4F Corridor Test 1·2 결과

## 한 줄 결론

회절+산란 Raw Sionna의 6개 Test 위치 MAE는 **15.12 dB**, 네 Calibration 위치를 모두 쓴 전역 편향 보정 후에는 **7.63 dB**다. Test 3은 철문 상태가 달라 제외했다.

## 최종 비교

| 결과 | MAE (dB) | RMSE (dB) | Pearson r |
|---|---:|---:|---:|
| 단순 Sionna RT: 회절+산란 | 15.12 | 15.83 | 0.962 |
| Calibration 보정: all-4 global bias | 7.63 | 8.84 | 0.962 |

- 주 평가는 Test 1·2의 같은 위치를 먼저 평균한 **6개 독립 위치** 기준이다.
- 보정 MAE의 위치 bootstrap 95% 구간은 **4.01–11.07 dB**다.
- 12개 반복 관측을 그대로 합친 MAE는 Raw **15.12 dB**, 보정 **8.50 dB**다.

## Held-out Test 실제값 vs 예측값

| 위치 | 실제 평균 (dBm) | Raw Sionna (dBm) | 보정 Sionna (dBm) | 보정 절대오차 (dB) |
|---|---:|---:|---:|---:|
| test-01 | -41.50 | -29.76 | -37.39 | 4.11 |
| test-02 | -38.00 | -30.78 | -38.41 | 0.41 |
| test-03 | -49.00 | -32.80 | -40.43 | 8.57 |
| test-04 | -58.00 | -42.25 | -49.88 | 8.12 |
| test-05 | -66.50 | -44.30 | -51.92 | 14.58 |
| test-06 | -64.25 | -46.63 | -54.25 | 10.00 |

## Solver 비교

| Solver | 방법 | 6개 위치 MAE (dB) | RMSE (dB) |
|---|---|---:|---:|
| doors_glass_base | raw_sionna | 13.20 | 13.66 |
| doors_glass_base | global_bias_all4 | 6.39 | 7.30 |
| doors_glass_diffraction | raw_sionna | 14.04 | 14.55 |
| doors_glass_diffraction | global_bias_all4 | 6.76 | 7.69 |
| doors_glass_diffraction_scattering_authored_100m_depth4 | raw_sionna | 15.12 | 15.83 |
| doors_glass_diffraction_scattering_authored_100m_depth4 | global_bias_all4 | 7.63 | 8.84 |

세 Solver의 차이는 반복 측정 오차와 함께 해석해야 하며, 작은 MAE 차이만으로 물리 모델의 우열을 단정할 수 없다.

## 신뢰도 제한

- 장치 보정 뒤 Calibration 반복 차이는 평균 **10.25 dB**, 최대 **16.00 dB**다. 5 dB 이내인 점은 `cal-04` 하나뿐이다.
- Test 1·2 동일 위치의 평균 절대 차이는 **6.08 dB**, 최대 **13.00 dB**다.
- 실측 TX x=3.13 m와 Sionna TX x=3.15 m 사이에 0.02 m 차이가 있다.
- 따라서 개별 위치의 절대 RSSI 신뢰도는 낮고, 큰 공간 경향의 신뢰도만 중간 수준으로 해석한다.
- Scene/Marker와 작성된 재질 계수는 아직 provisional이므로 확정된 물성값처럼 쓰지 않는다.
