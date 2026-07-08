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

