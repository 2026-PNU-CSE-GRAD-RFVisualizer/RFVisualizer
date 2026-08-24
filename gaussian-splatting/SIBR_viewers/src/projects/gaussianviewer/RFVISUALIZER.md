# RFVisualizer 확장 (SIBR Gaussian Viewer)

공식 SIBR Gaussian Viewer에 두 가지를 더했다. 둘 다 **인자를 주지 않으면 꺼져 있고**,
껐을 때의 출력은 기존 Gaussian 결과와 byte 단위로 같다.

1. `RFVolumeRenderer` — RF dBm Volume을 반투명하게 합성한다.
2. `JpegStreamer` — 렌더 결과를 JPEG로 인코딩해 Network `image_relay`(TCP 9101)로 보낸다.

기존 `GaussianView`에는 연결 코드만 있고, 두 기능은 각각 독립 파일이다.

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

## 2. 실행 인자

| 인자 | 기본값 | 설명 |
|---|---|---|
| `--rf-volume <manifest.json>` | 없음 | `viewer_volume/manifest.json`. 없으면 heatmap 비활성 |
| `--rf-method <0\|1\|2>` | `2` | 0=Raw Sionna, 1=Plain IDW, 2=Residual IDW |
| `--rf-heatmap-off` | 꺼짐 | heatmap을 끈 상태로 시작 |
| `--stream-host <host>` | 없음 | 없으면 송신 비활성 |
| `--stream-port <port>` | `9101` | image_relay ingest |
| `--stream-fps <fps>` | `12` | 송신 목표 FPS |
| `--jpeg-quality <1-100>` | `80` | JPEG 품질 |
| `--run-seconds <n>` | `0` | 0은 종료 전까지 실행 |
| `--metrics-json <path>` | 없음 | 종료 시 송신 측정값을 남긴다 |

```bash
./install/bin/SIBR_gaussianViewer_app \
  -m PGSR/output/pnu_3f_corridor \
  --rendering-size 800 480 --force-aspect-ratio \
  --rf-volume <experiment>/analysis/viewer_volume/manifest.json \
  --stream-host 127.0.0.1 --stream-port 9101 --stream-fps 12 --jpeg-quality 80 \
  --run-seconds 330 --metrics-json /tmp/stream_metrics.json
```

로컬 ImGui에는 방식 선택, 표시 On/Off, 투명도, 공통 dBm 범위, Z 절단만 추가했다.

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

## 4. JpegStreamer

Render Thread는 GPU를 기다리지 않는다.

```text
Render Thread : glGetTextureImage -> PBO[i] -> glFenceSync
                (지난 Frame의 Fence가 끝났으면 그것만 CPU로 복사)
CPU Queue     : 항상 최신 Frame 1개 (오래된 Frame은 버린다)
Worker Thread : 범례 그리기 -> OpenCV JPEG -> RFJF Header + Payload 송신
```

- RFJF Header는 `INTERFACE.md` §12의 공통 계약(22 byte, big-endian, `flags=0`)이며 바꾸지 않는다.
- 범례는 Worker Thread가 OpenCV로 그린다. Viridis 색상 막대, dBm 양 끝값, 방식 이름,
  렌더 FPS, `PROVISIONAL` 표시.
- Relay가 끊기면 렌더링은 계속하고 1초마다 다시 붙는다. 다시 붙으면 **최신 Frame부터**
  보내고 밀린 Frame은 보내지 않는다.
- JPEG가 8 MiB를 넘으면 그 Frame만 버리고 `dropped_oversize` 로 센다.
- `--metrics-json` 은 송신측 통계다. 종단 지연과 수신 FPS는 받는 쪽에서 재야 한다.

## 5. 좌표계 주의

`calibration.json` 의 `T_scene_from_metric` 이 가리키는 "scene" 은 **SIBR Gaussian 좌표계가
아니다.** Proxy를 만든 `3f_corridor_blend.ply` 가 Blender로 Z-up 변환된 사본이기 때문이다.
PGSR 학습 좌표계는 **-Y 가 위**이고, 둘 사이는 `(x,y,z) -> (x,-z,y)` 축 교환이다.
Bundle의 `T_scene_from_metric` 에는 이 교환까지 곱한 행렬이 들어 있으므로 Renderer는
그대로 쓰면 된다. 확인 방법은 `cameras.json` 을 metric으로 옮겨 z 중앙값이 사람 키
높이(약 1.6 m)인지 보는 것이다.

## 6. 회귀 확인

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
