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

# 3. 오프라인 구축 단계

## 3.1 실제 공간 촬영

목표 장소를 여러 시점에서 촬영한다.

입력 데이터는 다음과 같다.

- RGB 이미지 또는 영상 프레임
- 카메라 내부 파라미터(Camera Intrinsics)
- 카메라 위치와 방향(Camera Extrinsics)

촬영 시 고려 사항은 다음과 같다.

- 인접 이미지 사이에 충분한 시야 중첩 확보
- 벽, 바닥, 천장, 가구를 다양한 각도에서 촬영
- 심한 흔들림과 모션 블러 방지
- 촬영 중 조명 변화 최소화
- 실제 길이를 알고 있는 기준 물체 또는 기준 구간 확보

마지막 항목은 재구성된 공간의 Scale을 실제 미터 단위로 맞추는 데 사용한다.

---

## 3.2 카메라 Pose 추정

촬영 이미지에서 각 카메라의 위치와 방향을 계산한다.

대표적인 처리 흐름은 다음과 같다.

```text
촬영 이미지
    ↓
특징점 매칭
    ↓
SfM(Structure from Motion)
    ↓
카메라 Pose + Sparse Point Cloud
```

추정된 카메라 Pose는 PGSR 학습 입력으로 사용된다.

---

## 3.3 PGSR 장면 생성

촬영 이미지와 Camera Pose를 이용하여 PGSR Gaussian Scene을 학습한다.

각 Gaussian은 일반적으로 다음 정보를 가진다.

- 3차원 위치
- Scale
- Rotation
- Opacity
- 색상 또는 Spherical Harmonics 계수

출력 예시는 다음과 같다.

```text
point_cloud.ply
cameras.json
transforms.json
surface_mesh.ply 또는 surface_mesh.obj
```

Gaussian Scene은 최종 1인칭 화면 렌더링에 사용하고, Surface Mesh는 Sionna RT 전파 계산과 Viewer의 Depth-only Pass에 사용한다.

### PGSR을 사용하는 이유

일반 3DGS는 Novel View Rendering에는 적합하지만, 표면 기하가 불규칙하고 Sionna RT가 요구하는 명확한 Triangle Mesh를 바로 제공하지 않는다. PGSR은 Gaussian을 평면에 가깝게 정렬하고 기하 일관성을 강화하므로 다음 산출물을 한 파이프라인에서 확보하기에 적합하다.

```text
PGSR 결과
    ├─ Gaussian Scene  → 화면 렌더링용
    ├─ Surface Mesh    → Sionna RT 및 Mesh Depth용
    └─ Unbiased Depth  → Mesh Depth 비교 실험 후보
```

GaussianRT-RF처럼 Gaussian 자체를 RF Ray Tracing 표현으로 사용하는 연구도 존재하지만, 현재 프로젝트에서는 구현 코드와 개발 리스크를 고려해 핵심 의존성으로 채택하지 않는다. 해당 방향은 향후 Mesh 전처리를 줄이고 시각·전파 표현을 통합하는 Future Work로만 다룬다.

## 3.4 Sionna RT용 Triangle Mesh 생성 및 재질 전처리

Sionna RT는 현재 프로젝트에서 Gaussian 자체가 아니라 Triangle Mesh 기반 장면을 사용해 전파 경로를 계산한다. 따라서 PGSR 결과에서 Surface Mesh를 추출한 뒤, 전파 계산에 적합하도록 정리한다.

전파 계산용 Mesh는 포토리얼한 외형보다 다음 요소가 중요하다.

- 벽·바닥·천장의 위치와 평면성
- 문과 큰 가구의 배치
- 기둥과 금속 구조물
- 전파를 차폐하거나 강하게 반사하는 주요 장애물
- 구멍, 뒤집힌 Normal, 중복 Face 등 Mesh 오류 제거

작은 장식물이나 미세한 표면은 초기 구현에서 생략할 수 있다.

### Mesh 정리 및 수동 재질 그룹 분리

PGSR Mesh는 자동으로 콘크리트·목재·유리·금속을 구분하지 않는다. 현재 프로젝트는 한 개의 고정 실내 공간을 대상으로 하므로, 완전 자동 Material Segmentation을 구현하지 않고 Blender 등의 도구로 주요 구조만 수동 분리한다.

권장 단계는 다음과 같다.

```text
PGSR Surface Mesh
    ↓
불필요한 Floating Geometry 및 작은 조각 제거
    ↓
Hole/Normal/중복 Face 점검
    ↓
주요 구조별 Object 또는 Material Group 분리
    ↓
Sionna RT Scene으로 Export
```

재질 복잡도는 단계적으로 높인다.

| 단계 | 재질 구성 | 목적 |
|---|---|---|
| M0 | 공간 전체 단일 근사 재질 | Sionna RT 연결과 좌표계 검증 |
| M1 | 벽·바닥·금속 3개 그룹 | 주요 반사·감쇠 차이 반영 |
| M2 | 벽·바닥·목재·금속·유리 5개 그룹 | 최종 시연용 재질 세분화 |

초기 목표는 정확한 자동 재질 인식이 아니라, 주요 구조와 재질 차이가 전파 결과에 반영되는 작동 가능한 프로토타입을 만드는 것이다.

## 3.5 좌표계 및 실제 Scale 정렬

다음 좌표계가 동일한 실제 공간을 가리키도록 정렬해야 한다.

1. 실제 공간 좌표계
2. Gaussian Scene 좌표계
3. Sionna RT Mesh 좌표계
4. 임베디드 위치 추적 좌표계
5. 실시간 렌더러 카메라 좌표계

예를 들어 실제 공간의 고정된 점을 원점으로 정의한다.

```text
실내 출입구의 왼쪽 아래 모서리 = (0, 0, 0)
```

그리고 각 시스템에서 해당 지점이 같은 위치가 되도록 변환한다.

### Scale 보정

3D 재구성 결과는 실제 길이와 다른 임의 단위를 가질 수 있다.

```text
실제 기준 거리: 5.0 m
재구성 결과 거리: 1.7 unit

scale = 5.0 / 1.7
```

이 Scale을 Gaussian Scene과 Mesh에 동일하게 적용한다.

Sionna RT는 거리, 주파수, 파장, 경로 손실을 계산하므로 미터 단위 정렬이 필수다.

### 좌표 변환

실시간 실행에서는 다음 변환을 사용한다.

```text
Pose_GS = T_tracking_to_GS × Pose_tracking
```

`T_tracking_to_GS`에는 다음 항목이 포함된다.

- 위치 Offset
- 축 방향 변환
- 회전 보정
- Scale 보정

---

## 3.6 Sionna RT Scene 구성

정리된 전파 계산용 Mesh를 Sionna RT Scene으로 불러온다. Blender 등에서 나눈 Object 또는 Material Group에 Radio Material을 지정한다.

예시는 다음과 같다.

| 공간 요소 | 초기 재질 예시 |
|---|---|
| 콘크리트·석고 벽/천장 | Concrete 또는 Plasterboard 계열 |
| 목재 문/가구 | Wood |
| 유리창 | Glass |
| 금속문/금속 구조 | Metal |
| 바닥 | Concrete 또는 Wood |

MVP 연결 시험에서는 전체 Mesh에 하나의 근사 재질을 적용해도 된다. 이후 M1·M2 단계에서 구조별 재질을 늘린다.

송신기(AP)에는 다음 정보를 설정한다.

- 위치
- 높이
- 주파수
- 송신 전력
- 안테나 패턴
- 안테나 방향

초기 프로토타입에서는 전파 현상을 다음과 같이 제한한다.

| 항목 | 초기 설정 |
|---|---|
| LoS | 활성화 |
| Specular Reflection | 활성화 |
| 최대 반사 횟수 | 1~2회 |
| Diffuse Reflection | 비활성화 |
| Diffraction | 비활성화 |
| Refraction/Penetration | 필요성과 지원 범위를 확인한 뒤 선택 |

실제 RSSI와의 오차가 발생하더라도 초기에는 Geometry, Scale, AP 위치, 송신 전력, 재질 설정 중 어느 요소가 원인인지 분리해 검증한다.

## 3.7 Radio Map 계산

Sionna RT의 RadioMapSolver를 이용하여 공간의 RSS 또는 Path Gain을 계산한다.

초기 구현에서는 사람이 장치를 들고 이동하는 높이를 기준으로 하나의 수평 평면을 사용한다.

```text
히트맵 높이: z = 1.2~1.5 m
Cell 크기: 0.1 m × 0.1 m부터 시작
출력 Metric: RSS 또는 Path Gain
```

출력 데이터는 다음과 같은 2차원 배열이다.

```text
radio_map[y][x] = RSS [dBm]
```

Radio Map 데이터와 함께 다음 Metadata를 저장한다.

```json
{
  "origin": [-5.0, -4.0, 1.3],
  "cell_size": [0.1, 0.1],
  "width": 100,
  "height": 80,
  "min_rss": -90,
  "max_rss": -30,
  "coordinate_system": "gaussian_scene"
}
```

### 2.5D MVP와 3D 확장

단일 높이의 2D Radio Map을 3D 장면에 배치하는 현재 표현은 엄밀한 의미의 Volume Rendering이 아니라 **2.5D Radio Map 시각화**다. 이 선택은 ESP32가 아니라 다음 구현 위험을 줄이기 위한 것이다.

- 여러 높이에서 Sionna RT Grid를 계산하는 비용
- 3D Texture 생성과 저장 형식
- Volume Transfer Function 및 투명도 설계
- 장면 Geometry와 Volume 사이의 가림 처리
- 졸업작품 일정 내 End-to-End 통합 위험

확장 단계에서는 여러 높이의 Radio Map을 계산해 Slice Stack으로 저장한다.

```text
z = 0.5 m → Radio Map
z = 1.0 m → Radio Map
z = 1.5 m → Radio Map
z = 2.0 m → Radio Map
```

이후 필요에 따라 높이별 Slice 선택, 다중 Plane 동시 표시, 3D Texture 기반 Volume Rendering 순서로 확장한다.

## 3.8 히트맵 렌더링 데이터 생성

Radio Map 값을 색상으로 변환한다.

예시는 다음과 같다.

```text
강한 신호 → 빨간색
중간 신호 → 노란색 또는 초록색
약한 신호 → 파란색
```

RSS를 일정 범위로 정규화한다.

```text
-90 dBm → 0.0
-30 dBm → 1.0
```

추천 표현 방식은 Radio Map을 2D Texture로 변환하여 실제 공간의 해당 높이에 Plane으로 배치하는 것이다.

```text
radio_map.npy
    ↓
Color Map 적용
    ↓
Heatmap Texture 생성
    ↓
3D 공간의 Heatmap Plane에 부착
```

---

# 4. 실시간 실행 단계

## 4.1 임베디드 장치의 역할

임베디드 시스템은 **고정 RSSI 측정 노드**와 **핸드헬드 표시 장치**로 역할을 구분한다.

### 고정 ESP32 RSSI 측정 노드

- 실내 여러 위치에 고정 배치
- 특정 AP의 실제 RSSI 측정
- Moving Average, Median Filter, 이상치 제거
- MQTT를 통한 측정값 및 상태 정보 전송
- Sionna RT 결과의 검증 또는 보정에 활용

### 핸드헬드 ESP32-S3 장치

- IMU 기반 장치 방향 추정
- 위치 갱신 버튼 입력 전송
- PC에서 렌더링된 JPEG Frame 수신
- JPEG 소프트웨어 디코딩
- RGB565 Framebuffer 생성
- 800×480 RGB LCD 출력
- 연결 상태 및 오류 표시

핸드헬드 장치는 Gaussian 렌더링이나 Sionna RT 계산을 직접 수행하지 않는 Thin Client로 동작한다.

> **향후 논의 필요:** 고정 ESP32 노드가 핸드헬드 위치추정에 필요한 RSSI까지 함께 측정할 수 있는지, 통신 채널과 측정 주기를 어떻게 분리할지는 추후 결정한다.

---


## 4.2 위치와 방향을 분리한 Camera 갱신

현재 구조에서는 자유로운 연속 6DoF Tracking을 바로 목표로 하지 않는다.

- **Orientation:** 핸드헬드 IMU에서 지속적으로 추정
- **Position:** 평상시에는 마지막 확정 위치를 유지
- **Position Update:** 사용자가 버튼을 눌렀을 때만 현재 추정 위치를 Camera Position에 적용
- **Height:** 초기 구현에서는 장치를 들고 있는 높이로 고정 가능

```text
평상시:
Camera Position 유지
+
IMU Orientation만 갱신

버튼 입력:
현재 위치 추정 요청
    ↓
추정 Position을 Camera에 적용
    ↓
해당 위치로 텔레포트
```

권장 패킷 초안은 다음과 같다.

```cpp
struct HandheldControlPacket
{
    uint64_t timestamp;

    float quaternion_x;
    float quaternion_y;
    float quaternion_z;
    float quaternion_w;

    bool request_position_update;
    bool recenter_orientation;
};
```

위치가 추정된 뒤 PC 내부 또는 백엔드에서 별도의 Position 결과를 Viewer에 전달한다.

```cpp
struct PositionEstimate
{
    uint64_t timestamp;

    float position_x;
    float position_y;
    float position_z;

    float confidence;
};
```

> **향후 논의 필요:** PositionEstimate를 고정 ESP32의 RSSI로 생성하는 구체적인 방식은 아직 확정하지 않는다. 단순 RSSI 거리 변환, 다변측량, Fingerprinting, 복도 구간 Snap 중 어떤 방법을 사용할지 비교가 필요하다.

---


## 4.3 제어 데이터와 영상 전송

데이터 종류에 따라 통신 채널과 처리 Thread를 분리한다.

| 데이터 | 우선 구현 방식 | 처리 원칙 |
|---|---|---|
| IMU Orientation 및 버튼 입력 | UDP | 최신 Packet 우선, 일부 손실 허용 |
| 위치 추정 결과 | PC 내부 전달 또는 UDP | Confidence 검사 후 적용 |
| 제어/상태 메시지 | TCP 또는 WebSocket | 신뢰성 우선 |
| 렌더링 영상 | JPEG Frame over TCP | Frame 경계와 무결성 보장 |

```text
[Control Channel]
Quaternion + Button
→ UDP
→ Pose Receiver Thread
→ Atomic/Mutex 기반 Latest Pose 갱신

[Video Channel]
Final Frame
→ Encoder Thread
→ [Frame Size Header + JPEG Payload]
→ Network Thread
→ TCP
```

Orientation은 과거 Packet을 순서대로 처리하지 않고 가장 최신 값을 Camera에 반영한다. 영상도 Network가 느릴 때 이전 Frame을 계속 쌓지 않고 오래된 Frame을 폐기해 입력 지연이 누적되지 않도록 한다.

> **향후 논의 필요:** 최초 구현은 길이 Header를 가진 JPEG Frame over TCP를 우선 사용한다. 표준 MJPEG 적용 여부와 세부 Frame Header는 ESP32-S3 단독 벤치마크 후 확정한다.

## 4.4 PC 초기화

실시간 프로그램 시작 시 PC는 다음 데이터를 한 번 로드한다.

- Gaussian Scene
- Radio Map
- Radio Map Metadata
- Heatmap Texture
- 좌표 변환 행렬
- 카메라 Intrinsics
- 영상 인코더 설정

장면, AP 위치, 재질, 주파수가 고정되어 있다면 Sionna RT 계산은 실시간 루프에서 반복하지 않는다.

```text
Sionna RT 계산 → 실행 전 1회
3DGS 렌더링 → 실행 중 매 Frame
```

---

## 4.5 PC에서 Camera 상태 갱신

PC는 IMU Orientation과 위치 추정 결과를 서로 다르게 적용한다.

```text
IMU Orientation 수신
    ↓
축 방향 및 초기 자세 보정
    ↓
Camera Orientation 갱신
```

Camera Position은 매 Packet마다 변경하지 않는다.

```text
위치 갱신 버튼 미입력
→ 이전 Camera Position 유지

위치 갱신 버튼 입력
→ 최신 PositionEstimate 요청
→ Tracking 좌표계를 Gaussian 좌표계로 변환
→ Camera Position 갱신
```

좌표 변환은 다음 형태를 사용한다.

```text
Position_GS =
T_tracking_to_GS × Position_tracking
```

Orientation은 장치 장착 방향과 Viewer Camera 축 규약을 고려해 별도 보정 행렬 또는 Quaternion을 적용한다.

> **향후 논의 필요:** IMU Yaw Drift 보정, Orientation 재중심화 방식, Position 갱신 버튼을 누른 뒤 측정값을 몇 초간 수집할지 등은 실제 센서 시험 후 결정한다.

---


## 4.6 SIBR Viewer Fork와 Gaussian 렌더링

실시간 Viewer는 공식 3DGS SIBR Real-time Viewer를 Fork하여 필요한 기능을 추가하는 방식을 1순위로 사용한다.

```text
공식 SIBR Real-time Viewer
    ↓ Fork
기존 Gaussian 렌더링·Camera·OpenGL Context 유지
    ↓ 기능 추가
Heatmap / Mesh Depth / Pose / Streaming 모듈 통합
```

처음부터 SIBR를 해체해 독립 C++/CUDA/OpenGL Viewer를 만드는 방식은 다음 위험이 크므로 MVP에서 채택하지 않는다.

- Gaussian Loader와 Camera 규약 재구현
- CUDA–OpenGL Interop 및 GPU Resource 동기화
- Tile Sorting과 Alpha Compositing 통합
- 독립 Build System과 의존성 관리
- `diff-gaussian-rasterization`의 PyTorch/CUDA 의존성 분리

### 우선 추가할 모듈

- PGSR Gaussian Scene 로딩 호환성 확인
- Offscreen Framebuffer와 최종 Color Texture
- OpenGL Heatmap Plane 및 Radio Map Texture
- PGSR Mesh Depth-only Pass
- Scene/Heatmap Composite Shader
- Dear ImGui 상태 UI
- UDP Pose Receiver
- 좌표계 변환
- JPEG Encoder 및 TCP Streaming

### 초기 기술 검증 기준

SIBR Fork를 최종 기반으로 확정하기 전에 다음을 확인한다.

1. PGSR Gaussian PLY가 SIBR Viewer에서 정상 렌더링되는가
2. SIBR Camera의 View/Projection Matrix를 Mesh와 Heatmap Pass에 동일하게 사용할 수 있는가
3. Gaussian 장면 위에 OpenGL 테스트 Plane을 합성할 수 있는가
4. Offscreen Final Frame을 JPEG Encoder 입력으로 전달할 수 있는가
5. 추가 모듈이 기존 Viewer의 입력·렌더링 루프를 과도하게 침범하지 않는가

이 검증에 실패할 경우에만 별도 Viewer 또는 다른 공개 Gaussian Viewer를 대안으로 검토한다.

### Gaussian Rendering Pass

PC는 변환된 Camera Pose로 Gaussian Scene을 렌더링한다.

```text
PGSR Gaussian Scene
+
Camera Pose
    ↓
SIBR Gaussian Renderer
    ↓
Scene Color Texture
```

목표 출력은 다음과 같다.

```text
해상도: 800 × 480
목표 Frame Rate: 10 FPS 이상
```

RTX 4090을 사용하는 PC에서는 렌더링 자체보다 GPU→CPU Readback, JPEG 인코딩, 네트워크 전송, ESP32 디코딩이 End-to-End 성능의 주요 병목 후보다.

## 4.7 OpenGL 기반 Radio Map 히트맵 합성

Sionna RT의 출력은 렌더링된 영상이 아니라 각 Grid Cell의 RSS 또는 Path Gain 값이다. 따라서 Radio Map을 색상 Texture로 변환하고, OpenGL에서 실제 공간의 지정 높이에 Plane으로 배치해 Gaussian Scene과 합성한다.

```text
radio_map.bin
+
metadata.json
    ↓
RSS 정규화 및 Colormap 적용
    ↓
OpenGL Heatmap Texture
    ↓
실제 공간 좌표의 Plane에 매핑
```

우선 렌더링 Pass는 다음과 같다.

```text
Pass 1: SIBR Gaussian Renderer
        → Scene Color

Pass 2: PGSR Mesh OpenGL Depth-only Pass
        → Scene Surface Depth

Pass 3: OpenGL Heatmap Plane
        → Heatmap Color + Heatmap Depth

Pass 4: OpenGL Composite Shader
        → Depth 비교 + Alpha Blending

Pass 5: Dear ImGui
        → 현재 RSS, FPS, 위치 신뢰도, Orientation, 지연시간 표시
```

### PGSR Mesh Depth 우선 사용

Gaussian Splatting은 반투명 Gaussian의 Alpha Compositing으로 화면을 구성하므로 일반적인 Expected Depth가 실제 표면과 일치하지 않을 수 있다. 초기 구현에서는 PGSR Surface Mesh를 화면에 표시하지 않고 Depth-only로 렌더링해 히트맵 가림 판정에 사용한다.

```text
PGSR Mesh
→ 동일한 Camera View/Projection 적용
→ OpenGL Depth-only Rendering
→ Scene Depth Texture
```

PGSR Mesh는 Sionna RT에도 사용되므로 좌표계를 공유하기 쉽고, OpenGL의 명확한 표면 Depth를 얻을 수 있다는 장점이 있다.

### PGSR Unbiased Depth 비교

여유가 있을 경우 비교 대상은 일반 Gaussian Expected Depth가 아니라 **PGSR Unbiased Depth**로 한다. PGSR Unbiased Depth는 Plane Normal과 Camera-to-Plane Distance를 이용해 Ray–Plane Intersection Depth를 계산하므로 Alpha 누적 Weight에 의한 편향을 줄이는 방식이다.

비교 순서는 다음과 같다.

```text
PGSR Mesh Depth 구현
    ↓
Gaussian Color와 Mesh 경계 비교
    ↓
Camera Intrinsics / View / Projection / Scale 일치 검증
    ↓
Mesh Hole·Floating Geometry·Normal 오류 점검
    ↓
PGSR Unbiased Depth와 비교
    ↓
필요한 경우에만 Depth Bias 또는 Mask Dilation 적용
```

Mesh와 Gaussian 경계의 불일치로 나타나는 문제는 전형적인 Z-Fighting보다 **Occlusion Boundary Mismatch** 또는 **Boundary Halo**로 정의한다. Depth Bias와 Dilation은 좌표계 및 Projection 오류를 가리기 위한 수단으로 사용하지 않는다.

### Depth 및 Alpha 기반 합성

```text
Heatmap Depth < Scene Depth
→ 히트맵 표시

Heatmap Depth ≥ Scene Depth
→ 장면에 의해 가려짐
```

```glsl
float sceneDepth = texture(sceneDepthTex, uv).r;
float heatDepth  = texture(heatDepthTex, uv).r;

vec4 sceneColor = texture(sceneColorTex, uv);
vec4 heatColor  = texture(heatColorTex, uv);

finalColor = (heatDepth < sceneDepth)
    ? mix(sceneColor, heatColor, heatColor.a)
    : sceneColor;
```

## 4.8 현재 위치의 RSS 표시

장치 위치를 Radio Map Grid 좌표로 변환한다.

```text
장치 위치 (x, y)
    ↓
Grid Index 계산
    ↓
현재 RSS 샘플링
```

화면에는 다음과 같이 표시할 수 있다.

```text
Current RSS: -54 dBm
```

인접 Cell 사이에서 값이 갑자기 변하지 않도록 Bilinear Interpolation을 사용할 수 있다.

이 보간은 새로운 전파장을 생성하는 IDW와 다르다. 이미 Sionna RT로 계산된 Grid 결과를 화면 표시를 위해 부드럽게 샘플링하는 과정이다.

---

## 4.9 JPEG 인코딩 및 비동기 영상 전송

핸드헬드 장치는 ESP32-S3이므로 H.264 하드웨어 디코딩을 전제로 하지 않는다. 최종 영상은 JPEG Frame 단위로 압축하여 전송한다.

RGB888 원본 영상 크기:

```text
800 × 480 × 3 byte
≈ 1.15 MB/frame
```

RGB565 Framebuffer 크기:

```text
800 × 480 × 2 byte
≈ 750 KiB/frame
```

렌더링 Thread에서 JPEG 인코딩과 TCP 송신을 동기적으로 수행하지 않는다. 기본 구조는 다음과 같다.

```text
[Render Thread]
Gaussian + Mesh Depth + Heatmap 합성
    ↓
최신 Final Frame을 공유 Buffer/Queue에 게시
    ↓
즉시 다음 Frame 렌더링

[Encoder Thread]
최신 Frame 획득
    ↓
GPU→CPU Readback 또는 Encoder 입력 변환
    ↓
JPEG 인코딩
    ↓
Encoded Frame Queue에 게시

[Network Thread]
최신 JPEG Frame 획득
    ↓
[Frame Size Header]
[JPEG Payload]
    ↓
TCP 전송
```

### Bounded Queue와 Frame Drop

Frame Queue는 1~2개로 제한한다.

```text
새 Frame 도착
+
Queue에 아직 처리되지 않은 이전 Frame 존재
    ↓
가장 오래된 Frame 폐기
    ↓
최신 Frame 유지
```

이 정책은 모든 Frame을 보존하는 대신 입력 지연 누적을 막고 핸드헬드 화면의 반응성을 유지한다. Network가 느려져도 Render Thread는 대기하지 않는다.

### 초기 목표

- 해상도: 800×480
- 출력 FPS: 10 FPS
- Codec: JPEG
- 전송: 길이 Header를 가진 JPEG Frame over TCP 우선
- 디코딩: ESP32-S3 Software JPEG Decoder
- 출력 형식: RGB565
- Frame Queue: 1~2개
- Queue 초과 시: 오래된 Frame Drop

PC 측 JPEG Encoder는 `libjpeg-turbo`, OpenCV, nvJPEG 등의 후보를 단독 벤치마크한 뒤 선택한다. GPU→CPU Readback 병목이 크면 PBO, 비동기 Readback, Double/Triple Buffer를 검토한다.

> **향후 논의 필요:** JPEG 품질, 목표 Bitrate, Encoder 라이브러리, TCP Frame Header, ESP32-S3 PSRAM Buffer 구조와 LCD Bounce Buffer는 단독 벤치마크 후 확정한다. Thread 분리와 오래된 Frame Drop 정책은 현재 아키텍처의 기본 원칙으로 확정한다.

## 4.10 임베디드 화면 출력

임베디드는 PC에서 받은 영상을 디코딩한 뒤 Framebuffer에 출력한다.

```text
영상 패킷 수신
    ↓
영상 디코딩
    ↓
800×480 Frame 생성
    ↓
LCD Framebuffer 출력
```


---

## 4.11 실시간 Viewer의 모듈 및 Thread 구조

SIBR Fork 내부에서 기존 Viewer 코드를 최대한 유지하고, 프로젝트 전용 기능을 별도 모듈로 추가한다.

```text
SIBR_viewers/
└─ gaussianViewer/
   ├─ 기존 SIBR Gaussian Viewer 코드
   │
   └─ project_extensions/
      ├─ heatmap/
      │  ├─ RadioMapLoader
      │  ├─ HeatmapRenderer
      │  └─ Colormap
      ├─ geometry/
      │  └─ MeshDepthRenderer
      ├─ rendering/
      │  ├─ OffscreenFramebuffer
      │  └─ HeatmapCompositor
      ├─ tracking/
      │  ├─ PoseReceiver
      │  └─ CoordinateMapper
      ├─ streaming/
      │  ├─ FrameQueue
      │  ├─ JpegEncoder
      │  └─ VideoStreamer
      └─ ui/
         └─ ProjectDebugUI
```

실제 파일 배치는 SIBR Build 구조를 확인한 뒤 조정하며, 위 구조는 기능 경계를 정의하기 위한 초안이다.

### Render Thread

```cpp
while (!viewer.shouldClose())
{
    const PoseState pose = poseState.latest();
    camera.applyOrientation(pose.orientation);

    if (pose.requestPositionUpdate)
    {
        const PositionEstimate estimate =
            positionProvider.latestEstimate();

        if (estimate.confidence >= positionThreshold)
        {
            camera.setPosition(
                coordinateMapper.toGaussianPosition(
                    estimate.position
                )
            );
        }
    }

    sibrGaussianRenderer.render(camera, sceneColorTexture);
    meshDepthRenderer.render(camera, pgsrMesh, sceneDepthTexture);
    heatmapRenderer.render(camera, radioMap,
                           heatmapColorTexture, heatmapDepthTexture);

    compositor.compose(sceneColorTexture,
                       sceneDepthTexture,
                       heatmapColorTexture,
                       heatmapDepthTexture,
                       finalTexture);

    ui.render(finalTexture);
    rawFrameQueue.publishLatest(finalTexture);
}
```

Render Thread는 `encodeAndSend()`를 호출하지 않는다.

### Encoder Thread

```cpp
while (running)
{
    RawFrame frame = rawFrameQueue.waitLatest();
    JpegFrame jpeg = jpegEncoder.encode(frame);
    encodedFrameQueue.publishLatest(std::move(jpeg));
}
```

### Network Thread

```cpp
while (running)
{
    JpegFrame jpeg = encodedFrameQueue.waitLatest();
    videoStreamer.sendFrame(jpeg);
}
```

### Pose Receiver Thread

```cpp
while (running)
{
    HandheldControlPacket packet = udpReceiver.receive();
    poseState.updateLatest(packet);
}
```

두 Frame Queue는 크기 1~2의 Bounded Queue로 구성하고, 생산 속도가 소비 속도보다 빠르면 가장 오래된 Frame을 제거한다.

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

# 11. 현재 확정된 아키텍처

| 구성 요소 | 현재 확정된 역할 |
|---|---|
| 고정 ESP32 노드 | 실제 AP RSSI 측정 및 MQTT 전송 |
| PGSR | Gaussian Scene, Surface Mesh, Unbiased Depth 후보 생성 |
| Blender 등 Mesh 도구 | Mesh 정리 및 주요 재질 그룹 수동 분리 |
| Sionna RT | Mesh 기반 단일 높이 Radio Map 사전 계산 |
| SIBR | Fork하여 확장할 3DGS 실시간 Viewer 기반 |
| SIBR Gaussian Renderer | Gaussian Scene Color 생성 |
| PGSR Mesh Renderer | Depth-only Pass의 1순위 Source |
| PGSR Unbiased Depth | Mesh Depth 비교 실험 후보 |
| OpenGL | Heatmap Plane, Depth Pass, Composite, UI |
| Dear ImGui | FPS, RSS, Orientation, Position Confidence, 지연시간 표시 |
| Render Thread | 장면 렌더링과 최신 Raw Frame 게시 |
| Encoder Thread | JPEG 인코딩과 최신 Encoded Frame 게시 |
| Network Thread | 최신 JPEG Frame TCP 전송 |
| Pose Receiver Thread | UDP Orientation/Control Packet 수신 |
| Frame Queue | 크기 1~2, 오래된 Frame Drop |
| 핸드헬드 ESP32-S3 | IMU/버튼 입력 및 JPEG 영상 표시 |
| 영상 Codec | JPEG Frame over TCP 우선 |
| 목표 화면 | RGB LCD 800×480 @ 10 FPS |
| GaussianRT-RF | 핵심 구현이 아닌 Future Work |

현재 Viewer의 핵심 원칙은 다음과 같다.

> **공식 SIBR Real-time Viewer를 1순위 구현 기반으로 Fork하고, 기존 Gaussian 렌더링 구조 위에 Heatmap, Mesh Depth, Pose, Streaming 기능을 추가한다.**

> **전파 계산용 PGSR Mesh는 Blender 등에서 주요 구조와 재질을 수동으로 정리하며, 완전 자동 Material Assignment를 목표로 하지 않는다.**

> **히트맵 Occlusion은 PGSR Mesh Depth를 우선 사용하고, 필요할 경우 PGSR Unbiased Depth와 비교한다.**

> **Render, JPEG Encode, TCP Send, Pose Receive는 독립 Thread로 분리하고, 크기 1~2의 Bounded Queue에서 오래된 Frame을 폐기한다.**

> **MVP의 히트맵은 단일 높이의 2.5D Radio Map Plane이며, 다중 Slice와 Volume Rendering은 확장 항목이다.**

아직 확정하지 않은 항목:

- 고정 ESP32 기반 핸드헬드 위치추정 알고리즘
- 실제 RSSI와 Sionna RT의 결합 강도
- PGSR Unbiased Depth의 최종 사용 여부
- JPEG 품질·Encoder·Readback·Buffer 세부 구조
- IMU Yaw Drift 대응 방식
- 여러 높이의 Radio Map 확장 여부

# 12. 핵심 정리

Sionna RT는 실제 RSSI 측정 파이프라인을 대체하는 것이 아니라, 실제 공간의 기하 구조를 반영한 전파 분포를 계산하는 모듈로 사용한다.

PGSR은 실시간 화면용 Gaussian Scene과 전파 계산·가림 판정용 Surface Mesh를 함께 생성한다. 추출된 Mesh는 Blender 등에서 정리하고, 한 개의 고정 실내 공간에 필요한 주요 구조만 3~5개 재질 그룹으로 수동 분리한다. 자동 Material Segmentation은 최소 구현 범위에 포함하지 않는다.

실시간 Viewer는 공식 SIBR Real-time Viewer를 Fork하여 확장하는 방식을 우선 검증한다. 기존 Gaussian Renderer와 Camera 구조를 유지한 채 Heatmap Plane, PGSR Mesh Depth-only Pass, UDP Pose Receiver, Offscreen Framebuffer, JPEG Streaming 모듈을 추가한다.

히트맵 가림 판정은 PGSR Mesh Depth를 우선 사용한다. Gaussian Color와 Mesh 경계가 일치하지 않는 문제는 Occlusion Boundary Mismatch로 정의하고, Camera·Projection·Scale·Mesh 오류를 먼저 확인한다. 이후 필요할 경우 PGSR Unbiased Depth 비교와 작은 후처리 보정을 수행한다.

핸드헬드 ESP32-S3는 IMU Orientation과 버튼 입력을 PC에 전달하고, PC에서 렌더링된 JPEG Frame을 수신·디코딩하여 800×480 RGB LCD에 목표 10 FPS로 표시한다. Render, Encoder, Network, Pose Receiver는 독립 Thread로 동작하며, Frame Queue는 1~2개로 제한하고 오래된 Frame을 폐기해 지연 누적을 막는다.

Camera Position은 연속 추적하지 않고 버튼을 눌렀을 때만 갱신하며, 버튼 미입력 중에는 마지막 Position을 유지한다.

MVP의 RF 시각화는 사람이 장치를 드는 높이의 단일 Radio Map Plane이다. 이는 2.5D 표현이며, 여러 높이의 Slice와 Volume Rendering은 기본 파이프라인이 안정화된 뒤 확장한다.

GaussianRT-RF는 연구적으로 유망하지만 현재 프로젝트의 구현 기반으로 사용하지 않는다. 최종 발표에서 Mesh 전처리 없이 Gaussian 표현으로 시각 렌더링과 RF Ray Tracing을 통합하는 Future Work로 제시한다.

현재 가장 중요한 미확정 문제는 다음과 같다.

1. 기존 고정 ESP32를 활용한 핸드헬드 위치추정 방식
2. 실제 RSSI와 Sionna RT 결과의 결합 방식
3. IMU Yaw Drift와 재중심화 처리
4. PGSR Mesh Depth와 Unbiased Depth 비교 결과
5. ESP32-S3 JPEG 품질·Buffer·Readback 세부 구현
6. Tracking 좌표계와 Gaussian/Sionna 좌표계의 정렬
7. 여러 높이 Radio Map 및 Volume Rendering 확장 여부

이 문서는 구현과 실험 결과에 따라 계속 수정한다.
