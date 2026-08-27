# RFVisualizer 확장 (SIBR Gaussian Viewer)

공식 SIBR Gaussian Viewer에 다섯 가지를 더했다. 모두 **인자를 주지 않으면 꺼져 있고**,
껐을 때의 출력은 기존 Gaussian 결과와 byte 단위로 같다.

1. `RFVolumeRenderer` — RF dBm Volume을 반투명하게 합성한다.
2. `FrameStreamer` — 렌더 결과를 인코딩해 Network `image_relay`(TCP 9101)로 보낸다.
   기본은 RGB332+zlib(`flags=1`), 예비는 JPEG(`flags=0`)이다.
3. `HandheldControlClient` — Backend WebSocket `/handheld/control`을 구독해 Camera를 움직인다.
4. `GroundedFPSController` — `--grounded-fps`에서만 FPS Camera를 바닥에 세우고 벽에 막는다.
5. `ArcTeleportController` + `TeleportOverlayRenderer` — 같은 Mode에서 `R` 포물선 텔레포트.

기존 `GaussianView`에는 연결 코드만 있고, 다섯 기능은 각각 독립 파일이다.

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

Test는 CTest로 돈다. CUDA는 필요 없다. `grounded_camera`만 실제 `FPSCamera`를 돌리려고
`sibr_view`를 링크하지만 Window도 GL Context도 만들지 않는다.

```bash
cmake --build build-rfviewer --target SIBR_handheld_control_test SIBR_frame_codec_test \
  SIBR_grounded_motion_test SIBR_grounded_camera_test SIBR_arc_teleport_test -j2
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
| `--stream-format <fmt>` | `rgb332-zlib` | `rgb332-zlib`, `palette256-zlib`, `jpeg` |
| `--stream-dither <0-1>` | `0.4` | RGB332 Bayer 디더링 강도. `0`이면 끔 |
| `--stream-palette-frames <n>` | `20` | `palette256-zlib`에서 팔레트 표본을 모을 Frame 수 |
| `--jpeg-quality <1-100>` | `80` | `--stream-format jpeg`일 때만 쓴다 |
| `--run-seconds <n>` | `0` | 0은 종료 전까지 실행 |
| `--metrics-json <path>` | 없음 | 종료 시 송신 측정값을 남긴다 |
| `--handheld-host <host>` | 없음 | Backend WebSocket host. 없으면 Handheld 비활성 |
| `--handheld-port <port>` | `8000` | Backend WebSocket port |
| `--grounded-fps` | 꺼짐 | 바닥을 걷는 FPS + `R` 텔레포트. `--rf-volume` 필요 |

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

`--stream-format`의 `rgb332-zlib`과 `palette256-zlib`은 렌더 해상도가 정확히 800×480이어야 한다. 다르면
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
`SIBR_frame_codec_test`가 이 Header만 들고 컴파일한다. 팔레트 **선정**만 OpenCV가 필요해
`PaletteChooser.cpp`로 갈라 두었고, 이것도 GL 없이 테스트한다.

실측(pnu_3f_corridor 렌더 8장, 800×480):

| 형식 | 평균 payload | 인코딩 |
|---|---|---|
| RGB332 | 47.6 KB | 1.94 ms |
| RGB332 + dither 0.4 | 78.3 KB | 2.76 ms |
| 팔레트256 | 105.3 KB | 2.32 ms |

팔레트256의 워밍업 1회 비용은 kmeans 약 105 ms + LUT 약 7 ms다. Worker Thread에서만
일어나므로 렌더는 멈추지 않고, 그동안 송신만 잠깐 끊긴다.

- RFJF Header는 `INTERFACE.md` §12의 공통 계약(22 byte, big-endian)이며 바꾸지 않는다.
  `flags`만 형식을 따라 `0`(JPEG) 또는 `1`(RGB332+zlib)이 된다.
- `rgb332-zlib`: Readback Buffer는 BGR 순서라 Red는 offset 2, Blue는 offset 0이다.
  픽셀당 1 byte `RRRGGGBB` 384,000 byte로 옮긴 뒤 표준 `zlib`(`Z_BEST_SPEED`)으로 압축한다.
  Handheld가 10 fps마다 inflate해야 하므로 압축률보다 속도를 택했다.
- 디더링은 고정 4×4 Bayer Ordered Dithering이다. **상하 반전과 범례가 끝난 최종 화면**에
  걸므로 Bayer 좌표가 LCD의 `x, y`와 일치하고, Frame마다 패턴을 바꾸지 않으므로 움직여도
  반짝이지 않는다. Blue는 2 bit라 계단이 커서 `DITHER_BLUE_SCALE`(0.75)로 약하게 준다.
  강도는 **반올림 경계 근처에서만** 작동한다. 밴딩이 생기는 지점이 정확히 거기라서
  0.4로도 색 띠가 풀리고, 평평한 면에는 불필요한 잡음이 끼지 않는다.
- 디더링은 **Wire 형식을 바꾸지 않는다.** 여전히 `flags=1`, 384,000 byte라 Relay와
  Embedded는 고칠 것이 없다. `--stream-dither`는 RGB332에만 적용된다.
- `palette256-zlib`(`flags=2`)은 장면에서 고른 256색을 쓴다. 계약은 `INTERFACE.md` §12.3이다.
  Payload는 512 byte 팔레트(RGB565 big-endian) + 384,000 byte 인덱스 = 384,512 byte다.
  - 픽셀 매핑은 32×32×32 색 큐브 LUT 조회 한 번이다. 픽셀마다 256색을 뒤지면 10 fps를
    못 맞춘다. LUT는 팔레트가 정해질 때 한 번만 만든다(약 7 ms).
  - 시작 후 `--stream-palette-frames` 동안 표본을 모아 `cv::kmeans`로 고른다.
    Frame마다 다시 계산하면 정지 화면에서도 색이 일렁이므로 평소에는 고정한다.
  - 다만 **heatmap On/Off, 방식, dBm 범위가 바뀌면 다시 고른다.** 화면에 없던 색이
    갑자기 등장하는데 이전 팔레트에는 그 색을 담을 칸이 없기 때문이다. 실측에서
    히트맵을 나중에 켰을 때 히트맵 영역의 평균 색오차가 dE 1.87에서 12.02로 뛰었다.
    표본을 다시 모으는 동안에는 **직전 팔레트를 계속 쓴다**. 기본 팔레트로 되돌리면
    화면이 한 번 더 튄다. 재계산 횟수는 측정 JSON의 `palette_rebuilds`에 남는다.
  - 워밍업 동안에는 **RGB332와 같은 256색**을 실어 보낸다. Frame 0부터 형식상 유효하고
    화면도 `flags=1`과 같아 보인다. 색이 바뀌는 순간은 시작 직후 한 번뿐이다.
  - 팔레트 선정이 실패해도 기본 팔레트로 계속 돈다. 화면이 죽지 않는다.
  - 팔레트 선정은 `PaletteChooser`(OpenCV만 사용, GL 없음)에 있어
    `SIBR_palette_chooser_test`로 Viewer 없이 검증한다.
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

## 6. GroundedFPSController (`--grounded-fps`)

인자를 주지 않으면 기존 자유 비행(noclip) 그대로다. Mesh를 읽지도, Camera에 손대지도 않는다.

켜면 FPS Camera에 **위치 제약 callback 하나만** 걸린다. 새 Camera Class도, 범용 Character
Controller도, 물리 엔진도 없다.

| 조작 | Grounded |
|---|---|
| `W`/`A`/`S`/`D` | 시점의 수평면 이동. 위를 보든 아래를 보든 속도가 같다 |
| `Q`/`E` | **무시한다** (수직 이동 없음) |
| 왼쪽·가운데 버튼 Pan | **무시한다** |
| 오른쪽 버튼 드래그 | 그대로 시점 회전 (Pitch 제한 유지) |
| 오른쪽 버튼 + 휠 | 그대로 이동 속도 조절 |
| `I`/`J`/`K`/`L`/`U`/`O` | 그대로 시점 회전 |

- 눈높이는 metric `z = 1.7 m` 고정, 몸체는 반경 `0.25 m` 원이다.
- 충돌은 metric XY 평면의 2D로만 푼다. 이동을 최대 `0.125 m` 씩(반경보다 작게) 쪼개
  얇은 벽도 지나치지 않는다.
- 정면으로 부딪히면 벽 앞 `0.25 m` 에서 멈추고, 비스듬히 부딪히면 법선 성분만 지워
  접선 방향으로 미끄러진다.
- 모서리에서 수렴하지 않거나, 한 Frame에 `8 m` 를 넘거나, 좌표가 NaN이면 **마지막 안전
  위치에 남는다.** 어떤 경우에도 벽을 통과하거나 NaN pose를 만들지 않는다.

Navigation Mesh는 Bundle의 `occlusion_meshes` 중 **파일명이 정확히
`room_envelope_metric.obj`인 하나**다. manifest 순서에 기대지 않고, 0개거나 2개 이상이면
시작 오류다. AP/측정점 marker(`proxy_objects_metric.obj`)는 장애물이 **아니다.**

그 Mesh에서 `|normal.z| <= 0.1` 인 수직면 중 Z 범위가 `[0, 1.7]` 과 겹치는 것만 벽으로 쓰고,
`|normal.z| >= 0.9` 이면서 모든 vertex가 `|z| <= 0.05` 인 면만 바닥으로 쓴다. 천장과 찌그러진
삼각형은 빠진다.

```bash
./install/bin/SIBR_gaussianViewer_app \
  -m PGSR/output/pnu_3f_corridor \
  --rendering-size 800 480 --force-aspect-ratio \
  --rf-volume <experiment>/analysis/viewer_volume/manifest.json \
  --grounded-fps
```

`--grounded-fps`는 `--rf-volume` 이 있어야 쓸 수 있다. 바닥·벽 Mesh와
`T_scene_from_metric` 이 그 manifest에 있기 때문이다. 다음은 모두 **noclip으로 되돌아가지
않고 시작 오류로 멈춘다**: `--rf-volume` 없음, room envelope 없음/중복, 벽이나 바닥이
하나도 안 나옴, 좌표 변환이 특이하거나 왕복 오차가 `1e-4 m` 초과.

### 시작 위치

시작 Camera는 가장 가까운 입력 카메라라 복도 밖이거나 벽에 붙어 있을 수 있다. 그때는
**멈추지 않고 가장 가까운 유효 위치로 옮긴다.** 유효 위치는 바닥 삼각형 안이면서 모든
벽에서 `0.25 m` 이상 떨어진 지점이다. 옮겼으면 시작 Log에 이렇게 남는다.

```
[Grounded] 시작 Camera가 바닥 밖이거나 벽에 박혀 있어 가장 가까운 유효 위치로
옮겼습니다: metric XY (-500, -500) -> (0.25, 4.8427).
```

바닥 삼각형마다 "그 삼각형에서 시작점에 가장 가까운 점"을 구하고, 벽에 너무 붙었으면
무게중심 쪽으로 당겨 몸이 들어가는 첫 지점을 찾는다. 그중 시작점에 가장 가까운 것을 쓴다.
실제 corridor Bundle(바닥 604장, 벽 864개)에서 `0.1 ms` 미만이고 시작할 때 한 번만 돈다.

**주의: "가장 가까운"은 직선 거리다.** 시작점이 건물 밖이면 원래 있어야 할 방이 아니라
벽 하나 너머의 다른 공간으로 옮겨질 수 있다. 바닥 어디에도 반경 `0.25 m` 가 들어갈 자리가
없을 때만 시작 오류로 멈춘다.

### 포물선 텔레포트 (`R`)

Grounded FPS를 켜면 **자동으로 함께 켜진다.** 별도 인자는 없다.

| 조작 | 동작 |
|---|---|
| `R` 누름 | 조준 시작. 카메라 정면으로 포물선이 나타난다 |
| `R` 유지 | 마우스로 조준. 포물선이 시선을 따라온다 |
| `R` 유지 중 `W`/`A`/`S`/`D` | **막힌다.** 조준하는 동안 위치는 고정이다 |
| `R` 유지 중 우클릭 드래그 | 그대로 시점 회전 |
| `R` 해제 | 유효하면 이동, 무효하면 **아무 일도 없다** |

- **초록 포물선 + 고리**: 유효한 착지점. 고리는 몸 반경 `0.25 m` 그대로다.
- **빨강 포물선 + X**: 무효. 벽·장애물에 막혔거나, 바닥 밖이거나, 벽에서 `0.25 m` 이내다.

유효한 착지는 **위치만** 바꾼다. 시선 방향과 FOV는 그대로 유지되고 눈높이는 다시 `1.7 m`다.
무효한 지점에서 손을 떼도 **가까운 바닥으로 몰래 옮기지 않는다.** 그냥 취소된다.

포물선은 metric 좌표에서 `p(t) = origin + v·t + ½·g·t²` 로 계산한다. 속도 `8 m/s`,
중력 `9.81 m/s²`, 최대 `1.5` 초를 65개 점으로 샘플링하고 누적 길이 `8 m` 에서 자른다.
첫 벽·proxy 충돌이나 내려가면서 만나는 `z = 0` 지점에서 끝난다. 벽은 room envelope,
장애물은 기존 Raycaster의 proxy mesh다.

수평으로 조준하면 사거리는 약 `4.7 m` 다. **위로 15도쯤을 넘게 조준하면 착지점이
사라진다** — 8 m 길이 상한에 먼저 걸리기 때문이다. 이때는 빨강 X만 보인다.

조준은 다음 경우 즉시 취소된다: Handheld가 카메라를 가져갈 때, FPS mode가 아닐 때,
카메라 경로를 재생 중일 때, ImGui에 글자를 입력 중일 때. 취소된 뒤에는 `R`을 **다시
눌러야** 시작한다.

포물선은 Gaussian → RF Volume **다음, 송신 캡처 앞**에 그린다. 그래서 로컬 화면과
`--stream-host` 로 보내는 영상에 똑같이 나타난다.

임베디드 버튼은 **아직 연결되어 있지 않다.** 내부에는 입력원과 무관한
`TeleportAction {pressed, active, released}` 만 있고, 지금은 키보드 `R` 이 그 값을 채운다.
후속 작업에서 버튼이 같은 값을 채우면 상태기계는 그대로 쓴다.

### 제한

바닥이 metric `z = 0` 인 **평지**라고 가정한다. 계단·경사·중력·점프·웅크리기·움직이는
장애물은 다루지 않는다. 벽은 정적 Mesh 하나뿐이다. 텔레포트에도 화면 페이드나 시점 회전은
없고, 착지 지점을 자동으로 보정하지 않는다.

## 7. 좌표계 주의

`calibration.json` 의 `T_scene_from_metric` 이 가리키는 "scene" 은 **SIBR Gaussian 좌표계가
아니다.** Proxy를 만든 `3f_corridor_blend.ply` 가 Blender로 Z-up 변환된 사본이기 때문이다.
PGSR 학습 좌표계는 **-Y 가 위**이고, 둘 사이는 `(x,y,z) -> (x,-z,y)` 축 교환이다.
Bundle의 `T_scene_from_metric` 에는 이 교환까지 곱한 행렬이 들어 있으므로 Renderer는
그대로 쓰면 된다. 확인 방법은 `cameras.json` 을 metric으로 옮겨 z 중앙값이 사람 키
높이(약 1.6 m)인지 보는 것이다.

## 8. 회귀 확인

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

`--grounded-fps` 를 주지 않으면 Camera 경로도 기존과 같다. 이 기준 이미지 비교는 고정
Camera 경로를 쓰므로 grounded 여부와 무관하게 통과해야 한다.
