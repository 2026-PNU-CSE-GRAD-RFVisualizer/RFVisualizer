# AGENTS.md

이 문서는 `RFVisualizer` 그래픽스 저장소 전체에 적용된다.

## 1. 기본 원칙

작업 시작 시 `RFVisualizer-Docs` 전체를 읽지 않는다.

기본적으로 다음만 확인한다.

1. 이 `AGENTS.md`
2. 사용자가 지정한 파일
3. 수정 대상과 직접 연결된 코드·설정·테스트
4. 필요할 경우 해당 디렉터리 README의 관련 절

중앙 문서 저장소:

- GitHub: https://github.com/2026-PNU-CSE-GRAD-RFVisualizer/RFVisualizer-Docs
- 권장 로컬 위치: `../RFVisualizer-Docs`
- 저장소 내부 Submodule이 있다면: `./RFVisualizer-Docs`

Submodule은 최신 `main`보다 오래될 수 있으므로 Commit 상태를 확인한다.

## 2. 중앙 문서 선택 규칙

| 작업 상황 | 읽을 문서 | 범위 |
|---|---|---|
| 프로젝트 목표나 그래픽스 책임 판단 | `PROJECT.md` | 목표, 파트 책임, 설계 원칙 |
| 현재 완료 상태나 다음 단계 판단 | `CURRENT_STATUS.md` | 전체 요약과 그래픽스 절 |
| 좌표·CSV·RSSI·TX/RX·WebSocket 등 파트 간 계약 변경 | `INTERFACE.md` | 관련 인터페이스 절과 변경 절차 |
| 그래픽스 전체 구조나 장기 설계 파악 | `graphics/GRAPHICS.md` | 관련 기능 절만 |
| 내부 버그 수정·리팩터링·테스트 보강 | 중앙 문서 불필요 | 대상 코드와 테스트만 확인 |

다음 작업에서는 `INTERFACE.md` 확인이 필수다.

- 좌표 단위, 축, Transform 방향 변경
- Backend Export 구조나 CSV 열 변경
- `corrected_rssi` 사용 방식 변경
- TX/RX 형식 변경
- WebSocket Frame 또는 PositionEstimate 사용
- Handheld 제어 또는 RFJF Streaming 연결
- 다른 저장소도 함께 수정해야 하는 변경

문서는 관련 제목과 주변 절만 읽는다. 작업과 무관한 보고서·회의록·과거 계획서는 열지 않는다.

## 3. 판단 우선순위

1. 현재 동작 코드와 통과한 테스트
2. 공통 계약이 관련되면 `INTERFACE.md`
3. 현재 상태가 관련되면 `CURRENT_STATUS.md`
4. 그래픽스 설계가 관련되면 `graphics/GRAPHICS.md`
5. 이 저장소의 실행·테스트 문서
6. 과거 계획서·회의록·보고서

코드와 중앙 문서가 충돌하면 구현 결함인지 문서 미갱신인지 확인한다.

## 4. 그래픽스 파트 경계

이 저장소의 책임:

- PGSR Gaussian Scene과 Surface Mesh
- Plane/Wall Candidate와 Room Envelope
- Metric Calibration과 좌표 Transform
- Proxy Obstacle와 Material
- Sionna RT Scene, Path, Coverage, Radio Map
- Backend Export 기반 RSSI 분석
- SIBR RF Volume Viewer와 RFJF 영상 출력

임베디드 펌웨어, MQTT 수집 Backend, 실험 DB는 중복 구현하지 않는다.

## 5. 유지할 설계 기준

### 장면

- 화면 표시: PGSR Gaussian Scene
- RF 계산과 가림: Triangle Mesh 또는 Proxy Scene
- Gaussian 자체 RF Ray Tracing은 현재 구현 기반이 아니다.

### 좌표

- 단위: meter
- `+Z`: 위쪽
- `X`, `Y`: 바닥 평면
- 원점과 수평축: Scene 또는 Experiment별 설정
- 서로 다른 Experiment의 좌표와 Transform을 섞지 않는다.

### 측정 데이터

```text
x, y, z, corrected_rssi
```

```text
corrected_rssi = median_filtered + device_offset_db
```

- Calibration Point만 보정에 사용한다.
- Test Point는 평가에만 사용한다.
- Raw Sionna RT, Plain IDW, Residual IDW를 구분한다.

## 6. 상태 확인이 필요한 기능

다음 기능을 수정하거나 설명할 때만 `CURRENT_STATUS.md`의 그래픽스 절을 읽는다.

- SIBR Heatmap Viewer
- Mesh Depth-only Pass
- Offscreen 800×480 Rendering
- IMU Pose
- Position Update
- RFJF Encoding/Streaming (palette256/RGB332/JPEG)

계획, 부분 구현, 검증 완료를 구분한다.

## 7. 코드 변경 규칙

- 요청과 직접 관련된 범위만 수정한다.
- Scene별 측정값을 전역 상수로 하드코딩하지 않는다.
- 원본 PGSR 결과와 Metric/Proxy 사본을 구분한다.
- Placeholder Candidate를 실제 장애물로 자동 확정하지 않는다.
- 실제값·추정값·임의값을 Metadata에서 구분한다.
- Transform의 입력·출력 Frame과 단위를 기록한다.
- A/B 비교에서는 TX/RX, Seed, Solver, Grid를 고정한다.
- 자동 Cache와 대규모 실험 출력을 Source처럼 Commit하지 않는다.

## 8. 검증

변경 영역에 해당하는 검사만 수행한다.

### Geometry/좌표

- Room Envelope 닫힘
- Face Orientation과 Normal
- `+Z` Up
- Metric Scale
- Round-trip Transform
- TX/RX와 장애물 위치

### Sionna RT

- Scene Import
- 유한한 Path/Coverage 결과
- 동일 조건 Baseline
- 설정과 결과 Metadata

### RSSI 분석

- Calibration/Test 분리
- `corrected_rssi`
- 누락 좌표와 Invalid Sample
- MAE와 RMSE

### Viewer

- 기존 Gaussian Rendering 회귀
- Camera 좌표축
- Heatmap 위치와 Depth 가림
- 800×480 출력
- Frame Drop과 Memory 증가

실행하지 못한 검증은 완료로 표시하지 않는다.

## 9. 중앙 문서 갱신 조건

| 변경 | 갱신 문서 |
|---|---|
| 공통 좌표·데이터·프로토콜 | `INTERFACE.md` |
| 구현 상태나 다음 작업 | `CURRENT_STATUS.md` |
| 그래픽스 구조·설계 | `graphics/GRAPHICS.md` |
| 프로젝트 목표·파트 책임 | `PROJECT.md` |

단순 내부 버그 수정이나 동작이 변하지 않는 리팩터링은 중앙 문서를 수정하지 않는다.

## 10. 결과 보고

관련된 항목만 보고한다.

- 변경 파일과 이유
- 사용한 Scene/Experiment
- 좌표계와 단위
- 실행한 테스트
- 생성 결과
- 미검증 항목
- 중앙 문서 변경 여부
