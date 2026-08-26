# RFVisualizer 확장 (SIBR Gaussian Viewer)

공식 SIBR Gaussian Viewer에 세 가지를 더했다. 셋 다 **인자를 주지 않으면 꺼져 있고**,
껐을 때의 출력은 기존 Gaussian 결과와 byte 단위로 같다.

1. `RFVolumeRenderer` — RF dBm Volume을 반투명하게 합성한다.
2. `FrameStreamer` — 렌더 결과를 인코딩해 Network `image_relay`(TCP 9101)로 보낸다.
   기본은 RGB332+zlib(`flags=1`), 예비는 JPEG(`flags=0`)이다.
3. `HandheldControlClient` — Backend WebSocket `/handheld/control`을 구독해 Camera를 움직인다.

기존 `GaussianView`에는 연결 코드만 있고, 세 기능은 각각 독립 파일이다.

## 1. Build

기존 `build/` Cache는 다른 Checkout(`/data/RFVisualizer/...`)을 가리키므로 재사용하지 않는다.

```bash
cmake -B build-rfviewer -DCMAKE_BUILD_TYPE=Release
cmake --build build-rfviewer -j "$(nproc)" --target install
```

설치된 실행 파일의 RUNPATH는 `$ORIGIN`이라 Embree/TBB를 같은 폴더에 둬야 한다.
이걸 빼면 `ldd`에 `libembree3.so.3 => not found`가 뜬다.

```bash
cp embree-3.13.5.x86_64.linux/lib/libembree3.so.3 embree-3.13.5.x86_64.linux/lib/libtbb.so.12* install/bin/
```

새 `.cpp`를 추가하면 CMake가 `file(GLOB ...)`로 소스를 모으므로 **반드시 configure를 다시**
돌려야 한다. 안 그러면 조용히 예전 목록으로 빌드된다.

Test는 CTest로 돈다. GL도 CUDA도 필요 없다.

```bash
cmake --build build-rfviewer --target SIBR_handheld_control_test SIBR_frame_codec_test -j2
ctest --test-dir build-rfviewer --output-on-failure
```

## 2. 실행 인자

| 인자 | 기본값 | 설명 |
|---|---|---|
| `--rf-volume <manifest.json>` | 없음 | `viewer_volume/manifest.json`. 없으면 heatmap 비활성 |
| `--rf-method <0\|1\|2>` | `2` | 0=Raw Sionna, 1=Plain IDW, 2=Residual IDW |
| `--rf-heatmap-off` | 꺼짐 | heatmap을 끈 상태로 시작 |
| `--stream-host <host>` | 없음 | 없으면 송신 비활성 |
| `--stream-port <port>` | `9101` | image_relay ingest |
| `--stream-fps <fps>` | `10` | 송신 목표 FPS |
| `--stream-format <fmt>` | `rgb332-zlib` | `rgb332-zlib` 또는 `jpeg` |
| `--jpeg-quality <1-100>` | `80` | `--stream-format jpeg`일 때만 쓴다 |
| `--run-seconds <n>` | `0` | 0은 종료 전까지 실행 |
| `--metrics-json <path>` | 없음 | 종료 시 송신 측정값을 남긴다 |
| `--handheld-host <host>` | 없음 | Backend WebSocket host. 없으면 Handheld 비활성 |
| `--handheld-port <port>` | `8000` | Backend WebSocket port |

```bash
./install/bin/SIBR_gaussianViewer_app \
  -m PGSR/output/pnu_3f_corridor \
  --rendering-size 800 480 --force-aspect-ratio \
  --rf-volume <experiment>/analysis/viewer_volume/manifest.json \
  --stream-host 127.0.0.1 --stream-port 9101 --stream-fps 10 \
  --stream-format rgb332-zlib \
  --run-seconds 330 --metrics-json /tmp/stream_metrics.json
```

로컬 ImGui에는 방식 선택, 표시 On/Off, 투명도, 공통 dBm 범위, Z 절단만 추가했다.

`--stream-format rgb332-zlib`은 렌더 해상도가 정확히 800×480이어야 한다. 다르면
Frame을 조용히 버리지 않고 **시작 오류로 멈춘다**. 다른 해상도로 보려면 `--stream-format jpeg`을 쓴다.

`--handheld-host`는 `--rf-volume`이 있어야 쓸 수 있다. Position Update를 검증·변환할
manifest의 `frameId`와 `T_scene_from_metric`이 없으면 시작 오류로 멈춘다.

## 3. RFVolumeRenderer

Bundle은 `tools/rf_experiment` 의 `export-viewer-volume` 이 만든다. Renderer는 manifest를
검증하고 맞지 않으면 **빈 화면 대신 시작 오류로 멈춘다**(schema version, `zyx` 저장 순서,
`float32 little-endian`, `nx*ny*nz*4*4` byte 수, 가림용 Mesh 존재).

- RGBA32F `GL_TEXTURE_3D` 하나로 세 방식과 Valid Mask를 한 번만 Upload한다.
- dBm 채널은 Valid Mask로 premultiply되어 있어 `GL_LINEAR` 로 읽은 뒤 Alpha로 나눈다.
  경계에서 빈 칸 값이 섞이지 않고, invalid voxel은 완전히 투명하다.
- 가림용 Proxy Mesh는 metric 좌표라 `T_scene_from_metric` 으로 옮겨 Depth-only Pass에 쓴다.
  `core/renderer/DepthRenderer` 를 그대로 쓴다(NDC depth를 Lum32F에 쓴다).
- Ray Marching은 **metric 좌표에서** 한다. Volume이 축 정렬인 좌표계가 metric 하나뿐이라
  Texture 좌표가 한 번의 affine 변환으로 나온다. Sampling step 0.25 m, 누적 Alpha 0.98에서
  조기 종료, Proxy Depth 뒤는 폐기.
- 투명도는 voxel당이 아니라 **1 m당 흡수 계수**다(`1 - exp(-k * step)`).
  Sampling step을 바꿔도 밝기가 변하지 않는다.

## 4. FrameStreamer

Render Thread는 GPU를 기다리지 않는다.

```text
Render Thread : glGetTextureImage -> PBO[i] -> glFenceSync
                (지난 Frame의 Fence가 끝났으면 그것만 CPU로 복사)
CPU Queue     : 항상 최신 Frame 1개 (오래된 Frame은 버린다)
Worker Thread : 상하 반전 -> 범례 그리기 -> 형식별 인코딩
                -> RFJF Header + Payload 송신
```

형식 변환과 Header packing은 `FrameCodec.hpp` 하나에 있다. GL·OpenCV에 의존하지 않으므로
`SIBR_frame_codec_test`가 이 Header만 들고 컴파일한다.

- RFJF Header는 `INTERFACE.md` §12의 공통 계약(22 byte, big-endian)이며 바꾸지 않는다.
  `flags`만 형식을 따라 `0`(JPEG) 또는 `1`(RGB332+zlib)이 된다.
- `rgb332-zlib`: Readback Buffer는 BGR 순서라 Red는 offset 2, Blue는 offset 0이다.
  픽셀당 1 byte `RRRGGGBB` 384,000 byte로 옮긴 뒤 표준 `zlib`(`Z_BEST_SPEED`)으로 압축한다.
  Handheld가 10 fps마다 inflate해야 하므로 압축률보다 속도를 택했다.
- 범례는 Worker Thread가 OpenCV로 그린다. Viridis 색상 막대, dBm 양 끝값, 방식 이름,
  렌더 FPS, `PROVISIONAL` 표시. 범례는 인코딩 전에 그리므로 두 형식에 똑같이 들어간다.
- Relay가 끊기면 렌더링은 계속하고 1초마다 다시 붙는다. 다시 붙으면 **최신 Frame부터**
  보내고 밀린 Frame은 보내지 않는다.
- 인코딩에 실패하거나 Payload가 8 MiB를 넘으면 그 Frame만 버리고 `dropped_encode`,
  `dropped_oversize` 로 센다. 렌더링은 멈추지 않는다.
- 5초마다 최근 `seq`, 입력·Payload 크기, encode/send 시간, drop/reconnect 누계를 한 줄로 남긴다.
- `--metrics-json` 은 송신측 통계(schema `2.0`)다. 종단 지연과 수신 FPS는 받는 쪽에서 재야 한다.
  받는 쪽은 `measure_stream.py`가 `flags`를 그대로 보고하고, `flags=1`이면 표준 `zlib`로 풀어
  정확히 384,000 byte인지 확인한 뒤 `--save-dir`에 PNG로 남긴다.

## 5. HandheldControlClient

Path는 `/handheld/control` 고정이고 plain `ws://`만 쓴다. Graphics는 아무것도 보내지 않는다.
Backend 계약은 `INTERFACE.md` §11.6이며 여기서 바꾸지 않는다.

```text
Worker Thread : DNS/connect/handshake/read (Boost.Beast)
                계약 검증 -> Session/Sample/Event 방어 -> Mailbox
Mailbox       : Mutex 하나 아래 최신 Pose 1개 + Event Edge 최대 16개
                + Position 짝 대기 최대 16개 (가득 차면 가장 오래된 것부터 버린다)
Render Thread : drain -> stale/timeout -> Event 적용 -> Camera pose
                -> fromTransform(..., false, false) -> onUpdate -> render
```

WebSocket은 순서·중복·재연결을 보장하지 않는다. 방어는 전부 Graphics 쪽에 있다.

- 새 sample은 `0 < (seq - prev) mod 2^32 < 2^31`일 때만 Camera에 반영한다. uint32 wrap은 정상이다.
- `stale=true`는 같은 `sample_seq`여도 먼저 처리해 즉시 FPS로 되돌린다.
- Session이 바뀌면 이전 Session을 물러나게 하고, 늦게 온 옛 Packet은 영구 거부한다.
- Recenter와 Position은 종류별로 `event_seq`를 따로 기억한다. 버튼 3회 반복, stale snapshot,
  재접속 snapshot에서 **최대 한 번만** 적용한다.
- 재접속만으로 Session/Sample/Event 상태를 초기화하지 않는다.

Camera는 다음 식으로만 움직인다. 논리축은 `+X=right`, `+Y=up`, `-Z=forward`다.

```text
q_camera = q_camera_anchor * inverse(q_device_anchor) * normalize(q_device)
```

첫 유효 자세와 Recenter에서 기준(anchor) 두 개를 다시 잡는다. **그 Frame에서는 돌리지 않으므로
화면이 튀지 않는다.** 실제 센서 장착 보정 `q_mount`는 Embedded 책임이라 여기엔 없다.

Position은 `position_update` 응답과 `position_update_event=true` state가 같은 연결 안에서
`(connection_epoch, device_id, event_seq)`로 짝지어지고, `accepted=true`이고 숫자가 finite이며
`position.frame_id`가 manifest의 `frameId`와 정확히 같을 때만 적용한다. 도착 순서는 어느 쪽이든
지원한다. 적용할 때 translation만 바꾸고 rotation은 보존한다.

```text
scene_position = T_scene_from_metric * [x, y, z, 1]
```

Handheld가 Camera를 잡는 동안 Handler는 `NONE`이다. 아니면 FPS Handler가 매 Frame 외부 자세를
덮어쓴다. 다음 경우에는 마지막 Camera transform을 그대로 둔 채 `FPS`로 돌아간다.

- `--handheld-host` 없음, 연결 전, WebSocket 단절
- Backend `stale=true`
- 마지막 유효 자세 이후 750 ms 경과

### 제한

- 연결이 끊긴 순간 놓친 Position은 **복구할 수 없다.** Backend가 `position_update`를
  cache/replay하지 않기 때문이다. 가짜 복구 로직을 만들지 않았다.
- 실제 BNO085 축은 **미검증**이다. Yaw·Pitch·Roll 90도 실물 시험으로 확정해야 한다.
- 현재 Embedded 버튼 송신은 미구현이라 Recenter/Position은 Fake Backend로만 확인했다.

## 6. 좌표계 주의

`calibration.json` 의 `T_scene_from_metric` 이 가리키는 "scene" 은 **SIBR Gaussian 좌표계가
아니다.** Proxy를 만든 `3f_corridor_blend.ply` 가 Blender로 Z-up 변환된 사본이기 때문이다.
PGSR 학습 좌표계는 **-Y 가 위**이고, 둘 사이는 `(x,y,z) -> (x,-z,y)` 축 교환이다.
Bundle의 `T_scene_from_metric` 에는 이 교환까지 곱한 행렬이 들어 있으므로 Renderer는
그대로 쓰면 된다. 확인 방법은 `cameras.json` 을 metric으로 옮겨 z 중앙값이 사람 키
높이(약 1.6 m)인지 보는 것이다.

## 7. 회귀 확인

고정 Camera 기준 이미지는
`scenes/pnu_3f_corridor/experiments/corridor3f_20260820/outputs/viewer_baseline/` 에 있다.

```bash
./install/bin/SIBR_gaussianViewer_app -m PGSR/output/pnu_3f_corridor \
  --rendering-size 800 480 --force-aspect-ratio \
  --pathFile <...>/viewer_baseline/fixed_camera.lookat --outPath /tmp/regress
sha256sum /tmp/regress/00000000.png <...>/viewer_baseline/baseline_out/00000000.png
```

`--rf-volume` 없이, 또는 `--rf-volume ... --rf-heatmap-off` 로 돌린 결과는 기준 이미지와
**byte 단위로 같아야 한다.**
