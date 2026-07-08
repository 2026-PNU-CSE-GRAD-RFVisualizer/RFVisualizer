# 3DGS 기반 전파 히트맵 실시간 시각화 파이프라인

## 1. 문서 목적

이 문서는 실제 공간을 Planar-based Gaussian Splatting Reconstruction(PGSR)으로 재구성하고, Sionna RT로 계산한 전파 히트맵을 Gaussian 장면에 합성한 뒤, 핸드헬드 장치의 위치와 보는 방향에 맞는 1인칭 화면을 PC에서 렌더링하여 임베디드 디스플레이로 전송하는 전체 파이프라인을 정리한다.

실시간 Viewer는 **공식 3DGS SIBR Real-time Viewer를 Fork하여 확장하는 방식을 1순위 구현 경로**로 사용한다. SIBR의 기존 Gaussian 렌더링과 Camera 구조를 유지한 상태에서 Heatmap Plane, PGSR Mesh Depth Pass, UDP Pose 수신, Offscreen Framebuffer, JPEG Streaming 모듈을 추가한다. 초기 기술 검증 결과 SIBR 확장이 구조적으로 불가능하거나 지나치게 불안정할 경우에만 별도 Viewer 또는 다른 Gaussian Viewer를 대안으로 검토한다.

핸드헬드 장치는 ESP32-S3 + PSRAM + 800×480 RGB LCD를 사용하며, 목표 출력은 10 FPS다. 장치의 방향은 IMU로 추정하고, 위치는 매 Frame 연속 반영하지 않고 사용자가 버튼을 눌렀을 때만 갱신하는 구조를 우선 고려한다.

전체 시스템은 다음 두 단계로 구분한다.

1. **오프라인 구축 단계**
   - 실제 공간 촬영 및 Camera Pose 추정
   - PGSR 장면 재구성
   - 전파 계산용 Mesh 추출·정리
   - Blender 등에서 주요 구조를 3~5개 재질 그룹으로 수동 분리
   - Sionna RT Scene 구성 및 단일 높이 Radio Map 계산
   - 좌표계 정렬 및 데이터 저장

2. **실시간 실행 단계**
   - 고정 ESP32 노드의 실제 RSSI 측정
   - 핸드헬드 IMU의 방향 추정
   - 버튼 입력 시 위치 갱신 요청
   - PC에서 Gaussian 장면과 2.5D Radio Map 렌더링
   - 렌더링·JPEG 인코딩·TCP 송신·Pose 수신을 독립 Thread로 처리
   - ESP32-S3에서 JPEG 디코딩 후 RGB LCD 출력

현재 최소 구현(MVP)은 **사람이 장치를 드는 높이의 단일 2D Radio Map을 3D 공간에 배치하는 2.5D 시각화**다. 이는 임베디드 성능 때문이 아니라 Sionna RT 계산 범위와 3D Volume 시각화 구현 위험을 줄이기 위한 범위 조정이다. 여러 높이의 Slice 또는 Volume Rendering은 확장 단계로 남긴다.

> **향후 논의 필요:** 핸드헬드 위치를 추정할 때 기존 고정 ESP32 노드를 어떤 방식으로 재사용할지, 그리고 RSSI 다변측량·Fingerprinting·구간 기반 위치 추정 중 어떤 알고리즘을 채택할지는 아직 확정하지 않는다.

## 2. 전체 시스템 구조

```text
                         [오프라인 구축]

실제 공간 촬영
    ↓
Camera Pose 추정
    ↓
PGSR 학습
    ├─ Gaussian Scene ──────────────────────────────────────┐
    │                                                       │
    ├─ Unbiased Depth 출력 후보                             │
    │                                                       │
    └─ Surface Mesh                                         │
            ↓                                               │
   Mesh 정리·단순화                                         │
            ↓                                               │
Blender 등에서 주요 구조 수동 분리                          │
(벽/바닥/목재/금속/유리 중 필요한 3~5개 그룹)               │
            ↓                                               │
       Sionna RT                                             │
            ↓                                               │
단일 높이 2D Radio Map 생성                                 │
            ↓                                               │
 radio_map.bin + metadata.json                              │
            │                                               │
            └──────────────────────────┐                    │
                                       ↓                    ↓
                         [PC 실시간 Viewer]

[고정 ESP32 RSSI 측정 노드]
실제 AP RSSI 측정
    ↓
MQTT/백엔드 수집·동기화
    ↓
실측 데이터 검증·보정 입력
    └───────────────────────────────────────────────────────┐
                                                            │
[핸드헬드 ESP32-S3]                                        │
IMU 방향 추정 + 위치 갱신 버튼                             │
    ↓                                                       │
Orientation/Control Packet 전송                             │
    ↓                                                       │
┌───────────────────────────────────────────────────────────────┐
│ SIBR Real-time Viewer Fork                                  │
│                                                               │
│ 버튼 미입력: Camera Position 유지                            │
│ 버튼 입력: 추정된 Position을 Camera에 적용                   │
│ Orientation: 최신 IMU 방향을 지속 반영                       │
│                                                               │
│ Gaussian Scene → 기존 SIBR Gaussian Renderer → Scene Color   │
│ PGSR Mesh      → OpenGL Depth-only Pass    → Scene Depth     │
│ Radio Map      → OpenGL Heatmap Plane       → Heatmap Layer   │
│                                                               │
│ Scene Depth 비교 + Alpha Composite + Dear ImGui               │
└───────────────────────────────────────────────────────────────┘
    ↓
[Render Thread] 최신 Final Frame 게시
    ↓
크기 1~2의 Bounded Queue / 오래된 Frame Drop
    ↓
[Encoder Thread] JPEG 인코딩
    ↓
[Network Thread] TCP 전송
    ↓
[핸드헬드 ESP32-S3]
JPEG 디코딩 → RGB565 Framebuffer → 800×480 RGB LCD 출력
```

실시간 경로에서 Sionna RT를 매 Frame 실행하지 않는다. 장면 구조, AP 위치, 주파수, 재질 설정이 고정된 동안 Radio Map은 실행 전에 계산하고 Viewer는 저장된 Grid를 Texture로 읽어 시각화한다.

> **향후 논의 필요:** 고정 ESP32 RSSI 측정 노드가 기존 AP 측정과 핸드헬드 위치추정용 측정을 동시에 수행할지, 또는 위치추정을 별도의 측정 흐름으로 분리할지는 추가 설계가 필요하다.

