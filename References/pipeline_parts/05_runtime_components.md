# 5. 실시간 반복 구조

실시간 처리는 하나의 직렬 루프가 아니라 여러 독립 Thread가 최신 상태를 공유하는 구조로 동작한다.

```text
[고정 ESP32 RSSI 측정]
① 실제 AP RSSI 측정
② MQTT/백엔드 수집·동기화
③ Sionna 결과 검증·보정용 데이터 갱신

[Pose Receiver Thread]
① 핸드헬드 IMU Orientation 및 버튼 Packet 수신
② Latest Pose State 갱신

[Render Thread]
① 최신 Orientation 적용
② 버튼 요청 시 PositionEstimate 적용
③ SIBR Gaussian Scene Color 렌더링
④ PGSR Mesh Depth-only Pass
⑤ Heatmap Plane 렌더링
⑥ Depth 비교 및 Alpha Composite
⑦ 최신 Final Frame 게시

[Encoder Thread]
① 최신 Raw Frame 획득
② JPEG 인코딩
③ 최신 Encoded Frame 게시

[Network Thread]
① 최신 JPEG Frame 획득
② TCP 전송

[핸드헬드 ESP32-S3]
① JPEG Frame 수신
② JPEG 디코딩
③ RGB565 Framebuffer 갱신
④ 800×480 RGB LCD 출력
```

버튼이 입력되지 않은 동안에는 Camera Position을 유지하고 Orientation만 갱신한다. 영상 처리 속도가 느려지면 오래된 Frame을 폐기하며, Pose와 Render Thread는 Network 상태를 기다리지 않는다.

> **향후 논의 필요:** PositionEstimate 생성 방식과 실제 RSSI 측정 파이프라인의 결합 방법은 별도로 확정해야 한다.

# 6. 파트별 구성 요소

## 6.1 그래픽스/PC

### 오프라인 도구

- PGSR 학습 및 Mesh 추출 파이프라인
- Blender 기반 Mesh 정리·주요 구조 분리
- Sionna RT Scene 생성 코드
- Radio Material 설정
- Radio Map 계산 및 저장 도구
- 좌표계 및 Scale 검증 도구

### 실시간 Viewer

- 공식 SIBR Real-time Viewer Fork
- 기존 SIBR Gaussian Renderer 및 Camera
- OpenGL Heatmap Plane Renderer
- PGSR Mesh Depth-only Renderer
- Scene/Heatmap Depth 기반 Compositor
- Offscreen Framebuffer
- Dear ImGui UI
- UDP Pose Receiver
- 좌표계 변환 모듈
- 비동기 JPEG Encoder
- TCP Video Streaming Server
- 크기 1~2의 Bounded Frame Queue
- 오래된 Frame Drop 정책

## 6.2 임베디드

### 고정 ESP32 노드

- AP RSSI 측정
- 필터링 및 이상치 제거
- MQTT 데이터 전송
- 상태 관리 및 Fault Tolerance
- 향후 핸드헬드 위치추정 보조 가능성 검토

### 핸드헬드 ESP32-S3

- IMU Orientation 추정
- Orientation 및 버튼 입력 전송
- JPEG Frame 수신
- JPEG 디코딩
- RGB565 Framebuffer 관리
- 800×480 RGB LCD 출력
- 연결 상태 및 오류 처리

> **향후 논의 필요:** IMU 센서 모델, Orientation Filter, Yaw Drift 대응 방식과 고정 노드 기반 위치추정 방식은 추후 결정한다.


## 6.3 네트워크/백엔드

- MQTT 기반 실제 RSSI 수집
- RSSI Time Window 동기화
- PositionEstimate 생성 인터페이스
- UDP Pose Packet 수신 경로
- JPEG Frame over TCP 전송
- 장치 연결 상태 관리
- 지연시간 측정
- 패킷 손실 및 Frame Drop 측정
- Queue 체류시간 측정
- 로그 수집
- 제어 메시지 전달

