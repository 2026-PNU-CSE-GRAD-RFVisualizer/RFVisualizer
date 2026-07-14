# 7. 권장 구현 순서

전체 기능을 순차적으로 길게 구현하기 전에, 실패 가능성이 큰 연결부를 **Feasibility Spike**로 먼저 검증한다.

## 1단계: PGSR → Sionna RT 연결 검증

```text
작은 실내 장면 PGSR 학습
→ Surface Mesh 추출
→ Blender에서 오류 정리
→ 단일 재질 또는 벽/바닥 분리
→ Sionna RT Import
→ LoS Radio Map 하나 생성
```

검증 항목:

- Mesh Import 성공 여부
- 실제 Scale과 축 방향
- AP 및 Receiver Plane 위치
- Radio Map 출력 형식
- Material Group 적용 가능 여부

Phase 2-A에서 미터 단위 닫힌 Room Envelope를 Sionna/Mitsuba 장면으로 변환해 LoS·정반사·저해상도 path-gain 지도를 생성했다. 이어 Phase 2-B에서 Room Envelope와 분리된 synthetic blocker를 추가하고 같은 설정의 empty/variant A/B 실험을 수행해 LoS 차단, 다중 재질 등록, 재현성 noise floor, Coverage delta 계산까지 검증했다. Phase 2-C에서는 Open3D 기반 편집기로 Metric Room과 PGSR reference를 보면서 기존 scenario schema의 box·thin panel을 배치하고 검증·미리보기·저장하는 경로를 추가했다. 현재 배율과 재질은 임시값이며, 다음 입력은 실제 책상 군집·칠판·문 등의 측정 위치·크기·방향이다.

## 2단계: SIBR Fork 확장 가능성 검증

```text
PGSR Gaussian 로드
→ SIBR에서 정상 렌더링
→ OpenGL 테스트 Plane 추가
→ Gaussian 장면 위 반투명 합성
→ Offscreen Final Texture 획득
```

검증에 실패할 경우에만 별도 Viewer 또는 다른 Gaussian Viewer를 검토한다.

## 3단계: ESP32-S3 영상 표시 단독 벤치마크

```text
PC Test Frame
→ JPEG 인코딩
→ TCP 전송
→ ESP32-S3 JPEG 디코딩
→ RGB LCD 800×480 @ 10 FPS
```

측정 항목:

- JPEG 품질별 Frame 크기
- 인코딩 시간
- 전송 시간
- 디코딩 시간
- LCD 출력 FPS
- PSRAM 사용량

## 4단계: 비동기 Streaming 구조 구현

- Render / Encoder / Network / Pose Thread 분리
- 크기 1~2의 Bounded Queue
- 오래된 Raw/Encoded Frame Drop
- Queue 체류시간 및 End-to-End 지연 측정
- Network 지연 중 Render Thread 비차단 확인

## 5단계: 실제 Radio Map Heatmap 적용

- `radio_map.bin` 및 `metadata.json` 로드
- RSS Colormap 적용
- 실제 좌표와 Plane 좌표 정렬
- 현재 위치 RSS 조회
- 2.5D Heatmap Plane 표시

## 6단계: PGSR Mesh Depth-only Pass

- PGSR Mesh 로드
- SIBR Camera Matrix 공유
- Depth-only Framebuffer 구성
- Heatmap Occlusion 검증
- Occlusion Boundary Mismatch 확인

> **향후 논의 필요:** Mesh Depth가 충분하지 않을 때 PGSR Unbiased Depth를 비교한다. Camera/Scale/Projection과 Mesh 오류를 먼저 점검한 뒤에만 Depth Bias 또는 Mask Dilation을 적용한다.

## 7단계: IMU Orientation 연결

- IMU Quaternion 수신
- Camera Orientation 반영
- 재중심화 기능
- Yaw Drift 측정

> **향후 논의 필요:** IMU Filter와 Yaw Drift 대응 방식은 센서 실험 후 확정한다.

## 8단계: 버튼식 Position Update

- 버튼 입력 수신
- 버튼 미입력 시 Camera Position 유지
- PositionEstimate Confidence 검사
- 버튼 입력 시 Camera Position 갱신

> **향후 논의 필요:** 기존 고정 ESP32를 위치추정에 재사용하는 방식과 위치 알고리즘은 별도 검토한다.

## 9단계: 전체 시스템 통합

- 실제 RSSI 측정
- Sionna RT Radio Map
- IMU Orientation
- 버튼식 Camera Position Update
- Gaussian Scene + Heatmap 합성
- 비동기 JPEG Streaming
- LCD 출력
- End-to-End 지연시간 측정
- 실제 RSSI와 Sionna 결과 비교

## 10단계: 선택적 확장

- 재질 그룹 M1 → M2 확장
- 여러 높이의 Radio Map Slice
- PGSR Unbiased Depth 비교
- 실제 RSSI 기반 Offset 또는 Material 보정
- GaussianRT-RF 방식의 장기 적용 가능성 분석

# 8. 기존 기획서에서 변경되는 핵심 사항

기존 기획안의 **여러 고정 ESP32를 이용한 실제 RSSI 수집과 MQTT/백엔드 파이프라인은 유지한다.** Sionna RT는 이 구조를 제거하는 것이 아니라, 기하 구조를 반영한 전파 분포를 계산하고 실제 측정값과 비교·보정하기 위한 그래픽스/전파 계산 모듈로 추가한다.

| 구분 | 기존 기획 | 현재 제안 |
|---|---|---|
| 실제 데이터 | 여러 ESP32의 AP RSSI 측정 | 기존 측정 파이프라인 유지 |
| 전파 Field | IDW 등 측정값 보간 | PGSR Mesh + Sionna RT 기반 기하 전파 계산 |
| 재질 처리 | 별도 정의 없음 | Blender에서 주요 구조를 3~5개 그룹으로 수동 분리 |
| 고정 ESP32 | RSSI 측정 노드 | RSSI 측정 유지, 위치추정 보조 가능성 검토 |
| 핸드헬드 | 현장 상태 표시 | IMU 방향 입력, 위치 갱신 버튼, JPEG 영상 표시 |
| Camera 방향 | 별도 정의 없음 | IMU Orientation 연속 반영 |
| Camera 위치 | 별도 정의 없음 | 버튼을 눌렀을 때만 갱신 |
| Viewer | 일반 3D Viewer | SIBR Real-time Viewer Fork 확장 |
| 히트맵 표현 | 3D Volume 중심 | MVP는 단일 높이 2.5D Radio Map Plane |
| 가림 처리 | 별도 정의 없음 | PGSR Mesh Depth 우선, Unbiased Depth 비교 후보 |
| 영상 처리 | 별도 정의 없음 | Render/Encode/Send/Pose Thread 분리 |
| 지연 제어 | 별도 정의 없음 | Bounded Queue + 오래된 Frame Drop |
| 영상 Codec | 별도 정의 없음 | JPEG Frame over TCP 우선 |
| 화면 출력 | 일반 모니터 중심 | ESP32-S3 + RGB LCD, 800×480 @ 10 FPS |
| 최신 Gaussian RF 연구 | 별도 정의 없음 | GaussianRT-RF는 Future Work로만 활용 |

> **향후 논의 필요:** 실제 RSSI와 Sionna RT 결과를 단순 비교에만 사용할지, Offset 보정이나 Material Parameter 보정까지 수행할지는 추후 결정한다.

# 9. 현재 기준 권장 최소 구현 범위

- 한 개의 고정 AP
- 한 개의 고정 실내 공간
- 여러 고정 ESP32의 실제 AP RSSI 측정
- MQTT/백엔드 수집 및 동기화
- PGSR 기반 Gaussian Scene 및 Surface Mesh 생성
- Blender 기반 Mesh 정리
- 단일 재질 또는 벽·바닥·금속 수준의 수동 Material Group
- Sionna RT 기반 단일 높이 Radio Map
- LoS + 1~2회 정반사
- 공식 SIBR Real-time Viewer Fork
- PC의 800×480 Gaussian 실시간 렌더링
- OpenGL 2.5D Heatmap Plane 합성
- PGSR Mesh Depth-only Pass
- 핸드헬드 IMU Orientation 입력
- 버튼식 Camera Position 갱신 인터페이스
- Render / Encoder / Network / Pose Thread 분리
- 크기 1~2의 Bounded Frame Queue
- 오래된 Frame Drop
- JPEG Frame over TCP
- ESP32-S3 JPEG 디코딩
- RGB565 기반 800×480 RGB LCD 출력
- 목표 10 FPS
- End-to-End 지연시간 및 Frame Drop 측정

다음 항목은 최소 구현 이후 또는 실험 결과에 따라 확정한다.

- 고정 ESP32를 이용한 핸드헬드 위치추정 알고리즘
- 실제 RSSI와 Sionna RT 결과의 보정 방식
- PGSR Unbiased Depth 비교
- JPEG 품질 및 세부 Buffer 구조
- 여러 높이의 Radio Map Slice
- 자동 Semantic/Material Assignment
- GaussianRT-RF 기반 직접 RF Ray Tracing
