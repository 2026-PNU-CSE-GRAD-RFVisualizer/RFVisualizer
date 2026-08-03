# AGENTS.md

이 문서는 `RFVisualizer` 그래픽스 저장소 전체에 적용된다.

AI Agent와 개발자는 작업을 시작하기 전에 중앙 문서 저장소인 `RFVisualizer-Docs`의 기준을 먼저 확인해야 한다. 이 저장소의 오래된 계획서, 회의록, 중간보고서, AI 작업 지시서는 현재 기준보다 우선하지 않는다.

## 1. 필수 문서

다음 순서로 읽는다.

1. `RFVisualizer-Docs/PROJECT.md`
2. `RFVisualizer-Docs/CURRENT_STATUS.md`
3. `RFVisualizer-Docs/INTERFACE.md`
4. `RFVisualizer-Docs/graphics/GRAPHICS.md`
5. 이 저장소의 `README.md`
6. 수정 대상 디렉터리의 README, 설정 파일, 테스트, 소스 코드

중앙 문서 저장소:

- GitHub: https://github.com/2026-PNU-CSE-GRAD-RFVisualizer/RFVisualizer-Docs
- 권장 로컬 위치: `../RFVisualizer-Docs`
- 이 저장소 안에 Submodule이 남아 있다면: `./RFVisualizer-Docs`

로컬 Submodule은 오래된 Commit을 가리킬 수 있다. Submodule이 존재한다는 이유만으로 최신 문서라고 가정하지 말고, 중앙 저장소의 현재 `main`과 일치하는지 확인한다.

중앙 문서에 접근할 수 없으면 공통 인터페이스나 프로젝트 범위를 추측해서 변경하지 않는다.

## 2. 문서와 코드의 우선순위

설명이 충돌하면 다음 순서로 판단한다.

1. 현재 동작하는 코드와 통과한 테스트
2. `RFVisualizer-Docs/INTERFACE.md`
3. `RFVisualizer-Docs/CURRENT_STATUS.md`
4. `RFVisualizer-Docs/graphics/GRAPHICS.md`
5. `RFVisualizer-Docs/PROJECT.md`
6. 이 저장소의 운영용 README와 Tool별 문서
7. 과거 계획서, 회의록, 중간보고서, AI 작업 지시서

코드가 중앙 문서와 다르면 코드만 임의로 정답이라고 간주하지 않는다. 의도된 변경인지 결함인지 확인하고, 필요한 문서 변경을 같은 작업 범위에 포함한다.

## 3. 이 저장소의 책임

그래픽스 파트의 주요 책임은 다음과 같다.

- PGSR 기반 Gaussian Scene과 Surface Mesh 생성
- Plane 및 Wall Candidate 추출
- 닫힌 Room Envelope 생성
- 실제 meter 단위 Metric Calibration
- Proxy Obstacle와 Material 배치
- Sionna RT Scene, Path, Coverage, Radio Map 생성
- Backend Export 데이터 입력
- 실제 RSSI와 시뮬레이션 결과 비교
- 향후 SIBR 기반 Heatmap Viewer와 영상 출력 구현

다른 파트의 펌웨어, MQTT 수집 Backend, 실험 DB를 이 저장소에서 중복 구현하지 않는다.

## 4. 현재 설계 기준

### 장면 표현

- 사용자에게 보여줄 시각 장면: PGSR Gaussian Scene
- 전파 계산과 가림 판정: Triangle Mesh 또는 Proxy Scene
- Gaussian 자체를 이용한 RF Ray Tracing은 현재 구현 기반이 아니라 Future Work다.

### 좌표계

- 공통 단위는 `meter`다.
- `+Z`는 위쪽이다.
- `X`, `Y`는 바닥 평면이다.
- 원점과 수평축은 Scene 또는 Experiment별 설정에 기록한다.
- 강의실과 복도 등 서로 다른 Experiment의 좌표와 Transform을 혼합하지 않는다.
- 원본 PGSR 좌표와 Metric 좌표 사이의 Transform 방향을 명시한다.

### RF 측정 데이터

Backend Export의 기본 입력은 다음 값이다.

```text
x, y, z, corrected_rssi
```

```text
corrected_rssi = median_filtered + device_offset_db
```

- `calibration_points.csv`: RF Field 보정에 사용
- `test_points.csv`: MAE와 RMSE 평가에만 사용
- Test Point를 보정 과정에 포함하지 않는다.
- Raw Sionna RT, Plain IDW, Sionna RT + Residual IDW를 구분한다.

### 실시간 Viewer

다음 항목은 중앙 `CURRENT_STATUS.md`에서 완료로 변경되기 전까지 계획 또는 미구현으로 취급한다.

- SIBR Heatmap Viewer
- Mesh Depth-only Pass
- Offscreen 800×480 Rendering
- IMU Pose 수신
- Position Update
- JPEG Encoding과 Streaming

계획된 기능을 구현 완료된 기능처럼 README, 보고서, 코드 주석에 서술하지 않는다.

## 5. 공통 인터페이스 변경 규칙

다음 항목은 이 저장소에서 단독으로 변경하지 않는다.

- 좌표 단위와 축
- TX/RX 좌표 형식
- Backend Export 폴더 구조
- CSV 열 이름
- `corrected_rssi` 계산
- WebSocket Frame
- PositionEstimate 형식
- Handheld Packet
- JPEG Streaming Protocol

변경이 필요하면 다음 순서로 처리한다.

1. `RFVisualizer-Docs/INTERFACE.md`의 현재 규격을 확인한다.
2. 영향받는 그래픽스·임베디드·네트워크 파트를 식별한다.
3. 중앙 문서 수정안을 먼저 제시하거나 같은 PR 범위에 포함한다.
4. 코드와 테스트를 수정한다.
5. 구현 상태가 바뀌면 `CURRENT_STATUS.md`와 `graphics/GRAPHICS.md`도 갱신한다.

## 6. 코드 변경 원칙

- 요청과 직접 관련된 범위만 수정한다.
- 대규모 구조 변경은 필요성과 영향 범위를 먼저 설명한다.
- 원본 PGSR, SIBR, Sionna 관련 외부 코드의 동작을 근거 없이 변경하지 않는다.
- 원본 장면과 생성된 Metric/Proxy 사본을 구분한다.
- 자동 생성 Cache와 실험 출력물을 Source처럼 Commit하지 않는다.
- Placeholder Candidate를 실제 장애물로 자동 확정하지 않는다.
- 실제 측정값, 추정값, 임의값을 Metadata에서 구분한다.
- Scene-specific 상수를 전역 기본값으로 하드코딩하지 않는다.
- 좌표 Transform, 단위, Frame ID를 출력 파일에 기록한다.
- Random Seed와 Solver 설정이 비교 결과에 영향을 주면 설정을 고정하고 기록한다.

## 7. 테스트와 검증

변경 유형에 따라 최소한 다음을 확인한다.

### Geometry 또는 Coordinate 변경

- Room Envelope의 닫힘 여부
- Face Orientation과 Normal 방향
- `+Z` Up 여부
- Metric Scale
- Original → Metric → Original Round-trip Error
- TX/RX와 장애물의 Scene 내부 위치
- Floor, Ceiling, Wall Clearance

### Sionna RT 변경

- Scene Import 성공
- Empty Room Baseline 재현
- 동일한 TX/RX, Seed, Solver, Grid에서 A/B 비교
- Path 또는 Coverage 결과가 유한한지 확인
- 실험 설정과 출력 Metadata 저장

### RSSI 분석 변경

- Calibration/Test 분리
- `corrected_rssi` 적용
- 누락 좌표와 Invalid Sample 처리
- MAE와 RMSE 계산
- 결과가 어떤 Experiment와 Scene에 속하는지 기록

### Viewer 변경

- 기존 Gaussian Rendering 회귀 여부
- Camera Pose와 좌표축
- Heatmap 위치와 Depth 가림
- 800×480 출력
- Frame Queue와 Drop 정책
- 장시간 실행 시 Memory 증가 여부

실행하지 못한 테스트는 완료된 것처럼 쓰지 말고, 미실행 이유와 필요한 환경을 결과에 남긴다.

## 8. 문서 갱신 기준

다음 경우 중앙 문서를 함께 갱신한다.

- 공통 데이터 형식 변경: `INTERFACE.md`
- 완료 상태 또는 다음 작업 변경: `CURRENT_STATUS.md`
- 그래픽스 구조와 설계 변경: `graphics/GRAPHICS.md`
- 프로젝트 목표 또는 파트 책임 변경: `PROJECT.md`

이 저장소의 README에는 설치, 실행, Tool, 테스트처럼 코드와 직접 연결된 내용만 유지한다. 프로젝트 전체 설명을 중앙 문서와 중복 작성하지 않는다.

## 9. 작업 결과 보고 형식

작업 완료 시 다음을 명시한다.

1. 변경한 파일
2. 변경 이유
3. 사용한 Scene과 Experiment
4. 좌표계와 단위
5. 실행한 명령과 테스트
6. 생성된 결과 파일
7. 확인하지 못한 항목
8. 중앙 문서 갱신 필요 여부

불확실한 내용을 임의로 확정하지 않는다.
