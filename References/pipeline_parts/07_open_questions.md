# 10. 추가로 논의해야 할 사항

이 장의 항목은 현재 아키텍처에서 **의도적으로 미확정 상태로 유지**하며, 실험 결과에 따라 계속 수정한다.

## 10.1 실제 RSSI와 Sionna RT의 결합 방식

후보:

1. Sionna RT 결과와 실제 RSSI를 독립적으로 비교
2. 실제 측정값으로 Sionna 결과의 Global Offset 보정
3. 재질별 Parameter 또는 송신 전력 보정
4. 실제 측정값을 이용한 Hybrid Field Reconstruction

> **향후 논의 필요:** 초기 구현은 독립 비교부터 시작하며, Geometry와 Scale 검증 전에 복잡한 보정 모델을 추가하지 않는다.

## 10.2 핸드헬드 위치 추정 방식

현재 확정 사항:

- Orientation은 IMU로 추정
- Camera Position은 버튼을 누를 때만 갱신
- 버튼 미입력 시 이전 Position 유지

검토 후보:

- 기존 고정 ESP32와 핸드헬드 사이 RSSI를 이용한 다변측량
- RSSI Fingerprinting
- 복도 또는 지정 영역 기반 위치 Snap
- 위 방법들의 Hybrid

> **향후 논의 필요:** 기존 고정 노드의 AP RSSI 측정 업무와 위치추정 측정을 동시에 수행할 수 있는지 먼저 검증한다.

## 10.3 IMU Orientation 처리

검토 항목:

- 사용할 IMU 센서 모델
- Quaternion 계산 방식
- Complementary/Kalman/DMP 등 Filter
- 초기 Bias Calibration
- Yaw Drift
- 재중심화 버튼

> **향후 논의 필요:** 실제 장치에 부착한 상태에서 Drift와 지연시간을 측정한 뒤 확정한다.

## 10.4 Depth Source와 Occlusion Boundary

현재 우선순위:

1. PGSR Mesh Depth-only Pass
2. PGSR Unbiased Depth 비교
3. 필요할 경우 두 결과의 보완적 사용

검증 항목:

- Gaussian Color와 Mesh 경계 일치
- Camera Intrinsics와 Projection Matrix 일치
- Mesh Scale 및 좌표축 일치
- Mesh Hole, Floating Geometry, 뒤집힌 Normal
- 얇은 구조물과 물체 경계에서의 Occlusion Boundary Mismatch

> **향후 논의 필요:** 위 오류를 먼저 제거한 뒤에도 Boundary Halo가 남는 경우에만 작은 Depth Bias, Validity Mask, Mask Dilation을 검토한다. 일반 Gaussian Expected Depth는 우선 비교 대상이 아니다.

## 10.5 JPEG Streaming 세부 사양

현재 확정 사항:

- Render / Encoder / Network / Pose Thread 분리
- Frame Queue 크기 1~2
- Queue 초과 시 오래된 Frame 폐기
- TCP 기반 JPEG Frame 전송 우선

검토 항목:

- JPEG 품질
- Encoder 라이브러리
- GPU→CPU Readback 방식
- TCP Frame Header
- ESP32-S3 JPEG Decoder
- PSRAM Framebuffer/Double Buffer
- RGB LCD Bounce Buffer
- 목표 Bitrate 및 지연시간

> **향후 논의 필요:** 800×480 @ 10 FPS 단독 벤치마크를 먼저 수행한다.

## 10.6 실시간 성능 목표

측정 지표:

- IMU Orientation 전송 주기
- 버튼 입력부터 Camera Position 적용까지의 시간
- Gaussian 렌더링 FPS
- GPU→CPU Readback 시간
- JPEG 인코딩 시간
- Raw/Encoded Queue 체류시간
- Frame Drop 비율
- 네트워크 전송 시간
- ESP32-S3 JPEG 디코딩 시간
- LCD 출력 FPS
- Motion-to-Photon 또는 End-to-End 지연시간
- 위치 추정 오차
- 실제 RSSI와 Sionna 결과의 오차

## 10.7 GaussianRT-RF 활용 범위

GaussianRT-RF는 2D Gaussian에 직접 Ray 교차를 수행하고 시각적 장면 표현과 RF 경로 계산을 통합하는 유망한 연구 방향이다. 그러나 현재 프로젝트의 핵심 구현 경로로 사용하지 않는다.

배제 이유:

- 완성된 공개 구현에 대한 의존이 어려움
- Custom Hardware-accelerated Ray Tracer 필요
- Coarse Path Search, Path Refinement, Duplicate Pruning 구현 필요
- Gaussian별 Semantic/Material Label이 여전히 필요
- Sionna RT를 사용하는 것보다 구현 범위가 크게 증가

활용 방법:

- 관련 연구 및 설계 참고
- Semantic Material Labeling 아이디어 참고
- 최종 발표의 Future Work
- 향후 Mesh 전처리 없는 통합 RF Digital Twin 방향 제시

