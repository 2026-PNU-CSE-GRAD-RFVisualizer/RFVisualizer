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


