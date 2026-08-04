# RFVisualizer 중간 논문 실험 결과 요약

## 한 줄 결론

현재 N=13 주 평가에서는 Plain IDW가 가장 낮은 MAE·RMSE를 기록했으며,
Sionna RT + Residual IDW는 사전 정의한 최소 성공 조건을 충족하지 못했다.
단, Sionna 입력 계약과 이동 센서 offset이 아직 확정되지 않아 결과는
논문 최종값이 아닌 예비 결과다.

## 주 평가 결과

조건:

- Calibration: `cal-01`~`cal-03` 3개
- Test: 유효 표본을 확보한 13개
- 제외: `test-03` 측정 누락, `test-14` 표본 8개
- IDW power: 사전 기본값 `p=2`
- Test 데이터는 fitting에 사용하지 않음

| 방법 | MAE (dB) | RMSE (dB) |
|---|---:|---:|
| Raw Sionna RT | 7.6870 | 9.0662 |
| Plain IDW | **6.5564** | **7.2619** |
| Sionna RT + Residual IDW | 6.5881 | 7.5265 |

Residual IDW는 Plain IDW보다 MAE가 0.0317 dB, RMSE가 0.2645 dB 높다.

## 보조 평가 결과

표본이 8개인 `test-14`를 포함한 N=14 결과다.

| 방법 | MAE (dB) | RMSE (dB) |
|---|---:|---:|
| Raw Sionna RT | 7.4504 | 8.8143 |
| Plain IDW | **6.3973** | **7.0928** |
| Sionna RT + Residual IDW | 7.0699 | 8.0808 |

저표본 지점을 포함해도 방법 순위는 바뀌지 않는다.

## IDW power 검증

Test 값을 보지 않고 보정점 3개만 Leave-One-Out으로 비교했을 때
`p=3`의 오차가 후보 `p=1,2,3` 중 가장 낮았다. 그러나 N=13 Test
평가에서도 Residual IDW가 Plain IDW를 넘지는 못했다.

| 방법 (`p=3`) | MAE (dB) | RMSE (dB) |
|---|---:|---:|
| Raw Sionna RT | 7.6870 | 9.0662 |
| Plain IDW | **6.5016** | **7.2101** |
| Sionna RT + Residual IDW | 6.5578 | 7.4583 |

따라서 power 선택만으로 현재 결론을 뒤집을 수 없다.

## 원인 진단

보정점에서 측정값과 Raw Sionna RT의 잔차는 다음과 같다.

| 지점 | 측정 RSSI (dBm) | Sionna RSSI (dBm) | 잔차 (dB) |
|---|---:|---:|---:|
| `cal-01` | -47.0 | -33.10 | -13.90 |
| `cal-02` | -47.0 | -42.79 | -4.21 |
| `cal-03` | -50.0 | -32.90 | -17.10 |

세 잔차의 범위가 약 12.9 dB로 크다. 보정점이 3개뿐인 상태에서 이
잔차를 공간 보간하면 일부 영역에서 과도한 보정이 발생한다.

N=13, `p=2`에서 Residual IDW는 7개 지점에서 세 방법 중 가장 작은
절대 오차를 기록했지만, 일부 지점의 큰 오차 때문에 전체 MAE·RMSE가
Plain IDW보다 높아졌다.

## 이동 센서 offset 민감도

`node-02`의 공통 위치 장치 offset을 측정하지 못해 현재는 0 dB로
가정했다.

- `p=2`: offset이 약 +1.025 dB 이상일 때 Residual IDW가 Plain IDW보다
  MAE·RMSE 모두 낮아짐
- `p=3`: 약 +0.878 dB 이상에서 두 지표 모두 낮아짐

이 값은 장치 offset의 추정값이 아니라, 결론이 바뀌는 경계다. Test
성능이 좋아지는 값을 사후 선택해 장치 offset으로 사용하면 안 된다.

## 현재 결과를 논문 최종값으로 쓰지 않는 이유

1. `node-02`의 장치 offset이 실측되지 않았다.
2. `test-03`이 누락됐고 `test-14`는 표본이 8개뿐이다.
3. RF 실험 `scene.json`과 `tx_rx.json` 상태가 아직 `draft`다.
4. Sionna 장면 생성 자체는 성공했지만 빌드 Manifest가
   `physically_validated=false`다.

## 주요 산출물

- `analysis_primary_n13/processed/metrics.csv`
- `analysis_primary_n13/processed/comparison_results.csv`
- `analysis_primary_n13/figures/`
- `analysis_secondary_n14/processed/metrics.csv`
- `analysis_primary_n13_p3/processed/metrics.csv`
- `calibration_loo_power_selection.csv`
- `node02_offset_sensitivity.csv`
- `node02_offset_sensitivity.png`
- `sionna/sionna_rssi_report.json`
