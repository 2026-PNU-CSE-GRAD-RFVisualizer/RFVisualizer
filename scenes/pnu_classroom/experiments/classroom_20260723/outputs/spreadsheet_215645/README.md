# 그래픽스 분석용 정제 데이터

## 한 줄 결론

원본 측정값에 공식 TX/RX 좌표와 확정된 노드 매핑을 결합했으며, 결측값을 임의로 보간하지 않고 13개 Test 지점을 주 평가 대상으로 분리했다.

## 파일

| 파일 | 용도 |
|---|---|
| `measurements_summary_primary_n13.csv` | 주 평가용: 보정점 3개와 Test 13개 |
| `measurements_summary_secondary_n14.csv` | 보조 평가용: 표본 8개인 `test-14` 포함 |
| `point_mapping_and_qc.csv` | 원본 지점 ID, 변환 ID, 포함 여부와 제외 사유 |
| `node_mapping.csv` | 확정된 ESP32 노드와 측정 지점 대응 |
| `tx_rx_used.json` | 좌표 병합에 사용한 공식 TX/RX 설정 |
| `device_offsets_used.json` | 적용한 장치별 offset과 가정 |
| `preparation_report.json` | 변환 규칙, 제외 지점, 원본 파일 해시 |
| `RESULTS_SUMMARY.md` | Sionna·IDW 정량 결과와 원인 진단 |
| `sionna/` | 지점 및 0.5m 격자 Sionna 예측 |
| `analysis_primary_n13/` | `p=2`, N=13 주 평가 결과 |
| `analysis_secondary_n14/` | 저표본 `test-14`를 포함한 보조 평가 |
| `analysis_primary_n13_p3/` | 보정점 Leave-One-Out으로 선택한 `p=3` 확인 결과 |
| `node02_offset_sensitivity.csv` | 이동 센서 offset 가정별 지표 변화 |
| `node02_offset_sensitivity.png` | Residual IDW와 Plain IDW의 offset 민감도 그림 |

## 적용한 매핑

```text
gw-01   -> cal-01
node-01 -> cal-02
node-03 -> cal-03
node-02 -> 이동식 Test 센서

offset-02 -> test-00
offset-03 -> test-01
...
offset-16 -> test-14
```

## 평가 정책

- `test-03`: 이동식 `node-02` 측정값이 없어 주·보조 평가에서 모두 제외한다.
- `test-14`: 8개 표본만 있어 주 평가에서 제외하고 보조 평가에만 포함한다.
- 결측 Test 값은 보간하거나 고정 노드 값으로 대체하지 않는다.
- Test 세션 중 함께 수집된 고정 노드 값은 Test 측정값으로 사용하지 않는다.

## 중요한 한계

`node-02`는 공통 위치 장치 offset 측정값이 없다. 현재 정제본에서는
`device_offset_db=0.0`을 임시로 적용했으므로 `corrected_rssi`가
`median_filtered`와 같다.

이 파일들은 파이프라인 실행과 예비 결과 생성에는 사용할 수 있지만,
논문 최종값으로 확정하기 전에는 `node-02` offset 가정에 대한 민감도
분석을 함께 제시해야 한다.
