# Test_2_010416

네트워크·백엔드 파트가 생성한 측정 산출물.
생성 시각: 2026-07-27T16:14:03.827592+00:00

## 그래픽스 파트가 쓸 파일

| 파일 | 용도 |
|---|---|
| `processed/calibration_points.csv` | 보정 위치 1개. IDW / Residual IDW 입력 |
| `processed/test_points.csv` | Test 위치 6개. MAE·RMSE 평가 전용 |
| `processed/measurements_summary.csv` | 전체 위치 대표값 |
| `config/tx_rx.json` | TX(AP) 및 RX 좌표 |
| `config/device_offsets.json` | 장치별 RSSI 보정값 |
| `raw/measurements_raw.csv` | 전체 시계열 원본 |

## 사용할 RSSI 값

`corrected_rssi` 열을 사용한다.
= Filtered RSSI 의 30초 중앙값 + 해당 장치의 `device_offset_db`

`median_raw` 는 검증용으로만 보존되어 있으며 기본 실험값이 아니다.

## 주의

**`test_points.csv` 는 평가에만 사용한다.**
IDW / Residual IDW 생성이나 파라미터(p 등) 선택에 절대 넣지 않는다.
p 를 고르려면 `calibration_points.csv` 안에서 Leave-One-Out 으로만 선택한다.

## 좌표계

출입문 왼쪽 아래 바닥점이 원점.
+X = 오른쪽 벽 방향, +Y = 강의실 안쪽 깊이, +Z = 위쪽. 단위는 m.

## 품질 점검

상태: 문제 있음

### 문제
- 좌표 미등록 위치: calibration-01, offset-00, test-01, test-02, test-03, test-04, test-05, test-06

### 경고
- 보정 위치가 4개가 아닙니다 (현재 1개)
- Test 위치가 15개가 아닙니다 (현재 6개)

### 집계
```json
{
  "raw_rows": 1225,
  "summary_rows": 39,
  "calibration_points": 1,
  "test_points": 6,
  "registered_points": 0
}
```
