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

