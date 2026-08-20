# RFVisualizer 처음부터 끝까지 따라 하기

## 한 줄 결론

이 문서는 **실내 사진·영상 촬영 → PGSR 3차원 복원 → PGSR Mesh 생성 → 전파 계산용 Proxy Mesh 제작 → Proxy Placement Editor 배치 → 실제 RSSI 측정 → Sionna RT 계산 및 비교 결과 생성**까지 처음 사용하는 사람이 순서대로 따라 할 수 있게 정리한 실습 안내서다.

> 현재 RF 분석의 기준 예시는 `pnu_3f` 복도이며, 아직 PGSR 산출물만 준비된 초기 단계다. 이 문서의 명령 예시는 새 씬 이름을 `my_room`으로 두고 있다. 실제 작업할 때는 `my_room`을 그 씬의 실제 ID(예: `pnu_3f`)로 바꿔서 따라 한다. 씬마다 설정·산출물은 `scenes/<scene_id>/` 아래에 모으고 서로 섞지 않는다.

---

## 0. 먼저 알아둘 것

### 전체 흐름

```text
실내 사진 또는 영상에서 추출한 프레임
  ↓ COLMAP
카메라 위치·방향 + 희소 점구름
  ↓ PGSR 학습·렌더링
Gaussian Point Cloud + PGSR Surface Mesh
  ↓ 큰 평면 추출 + 실제 치수 반영
Metric Room Proxy Mesh
  ↓ Proxy Placement Editor
문·계단·책상·AP/TX·RX가 포함된 전파 장면
  ↓ 현장 RSSI 측정
Raw CSV + 위치별 Summary CSV
  ↓ Sionna RT + IDW 비교
MAE·RMSE 표 + 위치별 비교 CSV + 히트맵
```

### 비슷한 이름의 도구 구분

| 이름 | 역할 | 사용 시점 |
|---|---|---|
| PGSR | 사진으로 Gaussian 장면과 상세 Surface Mesh 생성 | 가장 먼저 |
| `proxy_mesh_editor` | PGSR Mesh에서 바닥·천장·벽 후보를 찾고 방 외곽 생성 | PGSR 이후 |
| `proxy_placement_editor` | 방 외곽 위에 문·책상·AP·측정점을 사람이 배치 | Proxy Mesh 이후 |
| `rf_experiment` | 입력 검증, Sionna 계산, 세 방법 비교와 그림 생성 | 실측 전후 |

### 이 프로젝트가 선택한 제작 방식

| 방법 | 장점 | 위험 | 권장 여부 |
|---|---|---|---|
| PGSR Mesh를 그대로 전파 계산에 사용 | 작업이 빠름 | 구멍·잡음·수백만 삼각형 때문에 계산과 재질 지정이 어려움 | 비권장 |
| 모든 구조를 Blender에서 수작업 | 원하는 모양을 정확히 만들 수 있음 | 시간이 오래 걸리고 재현하기 어려움 | 보조 수단 |
| **PGSR을 눈금·형상 참고로 쓰고 단순 Proxy를 실측값으로 보정** | 계산이 안정적이고 수정·검증이 쉬움 | 주요 치수를 사람이 재야 함 | **현재 권장 경로** |

즉, PGSR Mesh는 공간을 사실적으로 복원하고 물체 위치를 확인하는 기준이다. Sionna RT에는 벽·바닥·천장과 큰 장애물만 단순화한 Proxy Mesh를 사용한다.

---

## 1. 준비물과 실행 환경

### 하드웨어

- CUDA를 사용할 수 있는 NVIDIA GPU PC
- 사진 촬영용 카메라 또는 스마트폰
- 줄자 또는 레이저 거리 측정기
- 대상 AP 또는 전용 공유기
- RSSI 측정용 ESP32 장치
- AP·측정점·문·책상 위치를 기록할 현장 도면

### 소프트웨어

- Ubuntu 또는 이 저장소가 검증된 Linux 환경
- Conda
- CUDA에 맞는 PyTorch
- COLMAP
- PGSR용 `pgsr` Conda 환경
- Sionna RT용 `sionna` Conda 환경
- Mesh 확인용 Blender, MeshLab 또는 CloudCompare 중 하나

### 저장소 루트 확인

이 문서의 모든 명령은 특별한 설명이 없으면 저장소 루트에서 실행한다.

```bash
cd /data/RFVisualizer_Workspace/RFVisualizer
pwd
```

정상 출력:

```text
/data/RFVisualizer_Workspace/RFVisualizer
```

### 기존 환경 확인

```bash
conda env list
conda run -n pgsr python -c "import torch, open3d, yaml, numpy; print(torch.__version__, open3d.__version__)"
conda run -n sionna python -c "import sionna, mitsuba, drjit; print(sionna.__version__, mitsuba.__version__, drjit.__version__)"
```

현재 프로젝트의 Sionna 검증 환경은 Sionna RT 1.2.2, Mitsuba 3.8.0, Dr.Jit 1.3.1이다.

환경이 없다면 각 도구의 설치 문서를 먼저 따른다.

- PGSR: `PGSR/README.md`
- Proxy Mesh: `tools/proxy_mesh_editor/README.md`
- Sionna: `tools/sionna_scenario/README.md`

---

## 2. 사진 또는 영상 촬영

### 목표

COLMAP이 같은 벽과 물체를 여러 사진에서 찾을 수 있도록, **겹치는 사진 또는 영상 프레임을 흔들림 없이 충분히 촬영**한다.

### 촬영 전 고정할 것

- 카메라 렌즈와 해상도를 촬영 도중 바꾸지 않는다.
- 가능하면 자동 렌즈 전환, 디지털 줌, 인물 모드를 끈다.
- 조명을 켠 상태로 유지하고 창문 밝기가 크게 변하지 않는 시간에 촬영한다.
- 사람과 의자처럼 움직이는 물체를 줄인다.
- 실제 길이를 아는 구간을 최소 2개 정한다.
  - 예: 문 너비와 높이
  - 예: 방 가로와 깊이

### 권장 촬영 순서

1. 방 입구에서 전체를 천천히 촬영한다.
2. 벽을 따라 한 바퀴 돌며 전방·좌측·우측을 번갈아 촬영한다.
3. 방 중앙을 가로지르며 반대쪽 벽을 촬영한다.
4. 바닥과 천장이 각 사진에 일부 포함되게 한다.
5. 문, 계단, 칠판, 큰 책상과 금속 구조물을 가까이에서 추가 촬영한다.
6. 같은 위치에서 카메라만 크게 회전하기보다, 조금씩 이동하며 촬영한다.

### 촬영 품질 기준

- 인접 사진끼리 화면의 약 60~80%가 겹치게 한다.
- 흐릿한 사진, 초점이 나간 사진, 완전히 흰 벽만 담긴 사진은 제외한다.
- 유리·거울·반사 금속만 화면 대부분을 차지하지 않게 한다.
- 한쪽 방향만 찍지 말고 벽과 물체를 서로 다른 각도에서 본다.
- 사진 파일명은 영문·숫자로 단순하게 유지한다.

### 영상으로 촬영할 때

영상도 사용할 수 있다. 다만 영상 전체를 PGSR에 직접 넣는 것이 아니라, OpenCV로 일정한 시간 간격의 JPEG 프레임을 만든 뒤 사진과 같은 입력 폴더에 넣는다.

- 아이폰은 가능하면 `1080p / 30 FPS`로 촬영하고 `HDR 비디오`를 끈다.
- HDR을 켠 채 촬영했다면 프레임 추출 전에 HLG HDR 여부를 확인하고 SDR 변환을 적용한다.
- 4K도 사용할 수 있지만 프레임 수가 많으면 COLMAP과 PGSR 처리량이 크게 증가한다.
- 카메라를 빠르게 휘두르지 말고 천천히 걸으며 이동한다.
- 같은 자리에서 회전만 하지 말고 조금씩 위치를 바꾼다.
- 직선 복도에서는 정면만 계속 보지 말고 문·표지판·벽 모서리가 함께 보이도록 약간 비스듬히 촬영한다.
- 코너는 3~5초에 걸쳐 천천히 돌고, 회전 전후 장면이 충분히 겹치게 한다.
- 흔들림·모션 블러가 생기는 급회전 구간은 나중에 제외한다.
- 촬영 도중 렌즈, 줌 배율, 해상도와 프레임 속도를 바꾸지 않는다.
- 여러 영상으로 나눠 촬영해도 되지만, 영상 사이에 같은 벽이나 물체가 충분히 겹쳐야 한다.

복도처럼 이동과 회전 구간이 많은 영상은 기본 추출값으로 **10 FPS**를 권장한다. 예를 들어 2분 영상은 약 1,200장이 된다.

| 추출 FPS | 2분 영상의 프레임 수 | 사용 판단 |
|---:|---:|---|
| 2 FPS | 약 240장 | 매우 천천히 촬영했거나 빠른 시험 |
| 5 FPS | 약 600장 | 매우 천천히 촬영한 짧은 방 또는 빠른 시험 |
| **10 FPS** | **약 1,200장** | **일반적인 실내·복도 보행 촬영의 시작값** |
| 15 FPS | 약 1,800장 | 10 FPS에서 급회전 구간이 끊길 때만 시험 |

15 FPS가 항상 더 좋은 것은 아니다. 비슷한 프레임이 지나치게 많으면 COLMAP 특징점 매칭과 PGSR 학습 시간이 늘어난다. 10 FPS 결과에서 인접 프레임 사이 이동이 너무 크거나 급회전 구간이 끊길 때만 15 FPS를 시험한다. 가능하면 FPS를 높이기보다 촬영할 때 천천히 움직이고 긴 간격 매칭을 함께 사용하는 편이 낫다.

### 현장에서 함께 기록할 값

| 항목 | 예시 |
|---|---|
| 좌표 원점 | 출입문 왼쪽 아래 바닥점 |
| +X 방향 | 문 밖에서 안을 볼 때 오른쪽 |
| +Y 방향 | 출입문에서 방 안쪽 |
| +Z 방향 | 위쪽 |
| 방 가로·깊이 | 15.4m, 10.8m |
| 바닥 높이차 | 0.75m |
| 문 너비·높이 | 2.09m, 2.09m |
| AP 위치·높이 | `(x, y, z)` 미터 |

사진만으로 실제 크기를 정확히 알 수 없으므로 이 기록을 생략하면 안 된다.

---

## 3. 사진·영상을 PGSR 입력으로 준비

아래 예시는 새 장면 이름을 `my_room`으로 사용한다. 이름에는 공백 대신 영문 소문자와 밑줄을 권장한다.

### 3.1 입력 폴더 만들기

```bash
mkdir -p PGSR/data/tutorial/my_room/input
```

촬영 원본을 다음 위치에 복사한다.

```text
PGSR/data/tutorial/
└── my_room/
    └── input/
        ├── 0001.jpg
        ├── 0002.jpg
        └── ...
```

원본 사진은 이 폴더 외부에도 반드시 백업한다.

> 주의: 새 촬영본은 기존 장면 폴더에 덮어쓰거나 섞지 않는다. `my_room_v2`처럼 새 장면 이름을 사용하고, Mapper 검사를 통과한 결과만 최종 데이터셋으로 만든다.

### 3.2 영상에서 프레임 추출

사진만 입력할 때는 이 단계를 건너뛴다.

이 저장소의 `tools/extract_video_frames.py`는 OpenCV가 디코딩할 수 있는 `MP4`, `MOV`, `MKV`, `AVI` 등의 영상을 받는다. 한 번에 여러 영상을 넣을 수 있고, 원본 영상 번호와 시각이 겹치지 않는 파일명으로 저장된다. 실제 지원 코덱은 현재 OpenCV와 FFmpeg 설치 상태에 따라 달라질 수 있다.

먼저 영상 원본을 PGSR 입력 폴더 바깥에 보관한다.

```text
recordings/
├── my_room_part1.MP4
├── my_room_part2.MOV
└── my_room_detail.mkv
```

여러 SDR 영상에서 기본 10 FPS로 프레임을 추출한다.

```bash
conda run --no-capture-output -n pgsr \
  python tools/extract_video_frames.py \
  --video recordings/my_room_part1.MP4 \
          recordings/my_room_part2.MOV \
          recordings/my_room_detail.mkv \
  --output PGSR/data/tutorial/my_room/input \
  --fps 10
```

`--video` 뒤에는 영상 한 개 이상을 공백으로 구분해 적는다. 확장자가 대문자인 `.MP4`, `.MOV`도 사용할 수 있다.

기존 사진을 보호하기 위해 `--output` 폴더가 비어 있지 않으면 도구가 중단된다. 영상 프레임과 별도 촬영 사진을 함께 사용하려면 다음 순서를 따른다.

1. 빈 `input` 폴더에 영상 프레임을 먼저 추출한다.
2. 추가 사진을 서로 겹치지 않는 파일명으로 `input`에 복사한다.
3. `frames.csv`는 추출 기록이므로 그대로 보존한다.

특정 구간만 사용할 수도 있다.

```bash
conda run --no-capture-output -n pgsr \
  python tools/extract_video_frames.py \
  --video recordings/my_room_part1.MP4 \
  --output PGSR/data/tutorial/my_room/input \
  --fps 10 \
  --start-seconds 10 \
  --end-seconds 70
```

주요 결과:

```text
PGSR/data/tutorial/my_room/input/
├── video_001_my_room_part1_frame_000001_t000010000ms.jpg
├── video_001_my_room_part1_frame_000002_t000010200ms.jpg
├── video_002_my_room_part2_frame_000001_t000010000ms.jpg
└── frames.csv
```

`frames.csv`에는 다음 값이 기록된다.

| 열 | 의미 |
|---|---|
| `video_index` | 명령에 입력한 영상 순서 |
| `video_file` | 원본 영상 경로 |
| `source_frame` | 원본 영상 프레임 번호 |
| `timestamp_seconds` | 원본 영상의 시각 |
| `laplacian_variance` | 흐림 정도를 비교하기 위한 선명도 수치 |

`laplacian_variance`가 낮을수록 흐릴 가능성이 크지만, 모든 영상에 적용할 고정 합격값은 없다. 같은 영상 안에서 유난히 낮은 프레임을 실제 이미지와 함께 확인한 뒤 삭제한다. 자동으로 낮은 값 전체를 제거하면 약한 무늬의 벽 사진까지 사라질 수 있다.

추출된 사진 수를 확인한다.

```bash
find PGSR/data/tutorial/my_room/input \
  -maxdepth 1 -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' \) \
  | wc -l
```

프레임을 몇 장 직접 열어 다음을 확인한다.

- 영상 방향이 올바른가?
- 해상도가 유지됐는가?
- 인접 프레임이 충분히 겹치는가?
- 거의 같은 프레임만 반복되지 않는가?
- 급회전·초점 이동·심한 흔들림 구간이 포함되지 않았는가?

문제가 있으면 같은 출력 폴더를 덮어쓰지 말고 새 빈 폴더에 5, 10, 15 FPS 중 하나로 다시 추출해 비교한다.

#### 아이폰 HDR 영상 밝기 확인

OpenCV는 아이폰 HLG HDR 영상을 JPEG로 저장할 때 원본보다 밝게 보이게 만들 수 있다. 먼저 영상 메타데이터를 확인한다.

```bash
ffprobe \
  -v error \
  -select_streams v:0 \
  -show_entries stream=width,height,duration,avg_frame_rate,pix_fmt,color_space,color_transfer,color_primaries \
  -of default=noprint_wrappers=1 \
  recordings/my_room.MOV
```

- `color_transfer=bt709`: SDR 영상이므로 기존 추출 도구 또는 일반 FFmpeg 추출을 사용한다.
- `color_transfer=arib-std-b67`: HLG HDR 영상이므로 아래처럼 BT.709 SDR로 변환하면서 추출한다.

SDR 영상 한 개를 FFmpeg로 10 FPS 추출:

```bash
ffmpeg \
  -i recordings/my_room.MOV \
  -vf "fps=10" \
  -q:v 2 \
  -start_number 1 \
  PGSR/data/tutorial/my_room/input/frame_%06d.jpg
```

HLG HDR 영상을 BT.709 SDR JPEG로 변환하면서 10 FPS 추출:

```bash
ffmpeg \
  -i recordings/my_room.MOV \
  -vf "fps=10,zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p" \
  -q:v 2 \
  -start_number 1 \
  PGSR/data/tutorial/my_room/input/frame_%06d.jpg
```

FFmpeg는 `MOV`, `MP4`, `M4V`, `MKV`, `AVI` 등 설치된 디코더가 지원하는 여러 컨테이너를 받을 수 있다. 두 추출 명령은 동시에 사용하는 것이 아니라 영상의 `color_transfer`에 맞는 하나만 선택한다.

### 3.3 COLMAP 작업 경로 설정

이하 명령은 앞에서 이동한 저장소 루트에서 같은 터미널로 순서대로 실행한다.

```bash
REPO_ROOT="$(pwd)"
SCENE="$REPO_ROOT/PGSR/data/tutorial/my_room"
READY="$REPO_ROOT/PGSR/data/tutorial/my_room_ready"
COLMAP="$(conda run --no-capture-output -n pgsr which colmap)"

mkdir -p "$SCENE/sparse_raw"
```

`my_room_ready`는 COLMAP 카메라 왜곡 제거까지 끝낸 PGSR 전용 입력 폴더다. 기존 결과가 섞이지 않도록 작업 시작 시 `SCENE`과 `READY` 모두 새 이름을 사용한다.

### 3.4 특징점 추출

실제 카메라의 렌즈 왜곡을 먼저 추정하기 위해 `SIMPLE_RADIAL`을 사용한다. 이 모델을 PGSR에 직접 넣어서는 안 되며, 뒤의 `image_undistorter` 단계에서 `PINHOLE`로 변환한다.

```bash
"$COLMAP" feature_extractor \
  --database_path "$SCENE/database.db" \
  --image_path "$SCENE/input" \
  --ImageReader.single_camera 1 \
  --ImageReader.camera_model SIMPLE_RADIAL \
  --SiftExtraction.max_num_features 8192 \
  --SiftExtraction.use_gpu 1
```

촬영 도중 렌즈나 줌 배율을 바꿨다면 `single_camera 1`을 사용하면 안 된다. 이 경우 영상을 렌즈별로 분리해 다시 처리하는 편이 안전하다.

### 3.5 특징점 매칭

사진 묶음과 영상 프레임은 매칭 방법이 다르다. 아래 두 경로 중 입력에 맞는 하나를 선택한다.

#### 사진만 입력한 경우

사진 수가 많지 않고 파일 순서가 촬영 동선을 정확히 나타내지 않는 경우 exhaustive matcher를 사용한다.

```bash
"$COLMAP" exhaustive_matcher \
  --database_path "$SCENE/database.db" \
  --SiftMatching.guided_matching 1 \
  --SiftMatching.use_gpu 1
```

#### 영상 프레임을 입력한 경우

먼저 앞뒤 30프레임을 촘촘하게 매칭한다. 10 FPS 기준 약 3초 범위다.

```bash
"$COLMAP" sequential_matcher \
  --database_path "$SCENE/database.db" \
  --SequentialMatching.overlap 30 \
  --SequentialMatching.quadratic_overlap 0 \
  --SequentialMatching.loop_detection 0 \
  --SiftMatching.guided_matching 1 \
  --SiftMatching.use_gpu 1
```

이어서 같은 데이터베이스에 긴 베이스라인 매칭을 추가한다.

```bash
"$COLMAP" sequential_matcher \
  --database_path "$SCENE/database.db" \
  --SequentialMatching.overlap 7 \
  --SequentialMatching.quadratic_overlap 1 \
  --SequentialMatching.loop_detection 0 \
  --SiftMatching.guided_matching 1 \
  --SiftMatching.use_gpu 1
```

두 번째 명령은 `1, 2, 4, 8, 16, 32, 64프레임` 간격을 매칭한다. 직선 복도처럼 인접 프레임의 카메라 이동량이 작을 때 삼각측량을 안정시키기 위한 단계다.

올바른 옵션 이름은 `--SiftMatching.guided_matching`이다. `--FeatureMatching.guided_matching`은 현재 설치된 COLMAP 3.11.1에 없는 옵션이다.

### 3.6 Mapper 실행

```bash
"$COLMAP" mapper \
  --database_path "$SCENE/database.db" \
  --image_path "$SCENE/input" \
  --output_path "$SCENE/sparse_raw" \
  --Mapper.ba_global_function_tolerance 0.000001
```

Mapper가 끝나면 `sparse_raw/0`, `sparse_raw/1`처럼 하나 이상의 모델 폴더가 생길 수 있다.

### 3.7 Mapper 결과 합격 검사

PGSR을 실행하기 전에 모든 모델의 등록 이미지 수를 확인한다.

```bash
for MODEL in "$SCENE"/sparse_raw/*; do
  echo
  echo "===== $MODEL ====="
  "$COLMAP" model_analyzer --path "$MODEL" 2>&1 \
    | rg "Registered images|Points|Mean track length|Mean observations per image|Mean reprojection error"
done
```

합격 기준:

- 전체 입력 프레임의 90% 이상이 하나의 모델에 등록되어야 한다.
- 가장 큰 모델의 카메라 궤적이 촬영 동선을 따라 연속적이어야 한다.
- 거의 같은 연속 프레임 사이에서 카메라가 순간이동하면 안 된다.
- 평균 재투영 오차만 보고 성공으로 판단하지 않는다. 복도 반복 무늬에서는 오차가 작아도 잘못된 자세가 나올 수 있다.

예를 들어 입력이 2,500장이면 하나의 모델에 최소 약 2,250장이 등록되는 것을 목표로 한다. 여러 모델로 분리되고 가장 큰 모델이 90% 미만이면 PGSR 학습으로 넘어가지 않는다. 모델 폴더를 단순히 복사하거나 이름만 바꿔 합치지 않는다.

검사를 통과한 모델 번호를 지정한다. 아래 예시는 가장 큰 정상 모델이 `sparse_raw/0`인 경우다.

```bash
MODEL="$SCENE/sparse_raw/0"
```

가장 큰 정상 모델이 `1`이면 마지막 숫자를 `1`로 바꾼다.

### 3.8 필수 카메라 왜곡 제거

PGSR은 `PINHOLE` 또는 `SIMPLE_PINHOLE` 카메라만 지원한다. `SIMPLE_RADIAL` 모델을 직접 넣으면 다음 오류가 발생한다.

```text
AssertionError: Colmap camera model not handled: only undistorted datasets
(PINHOLE or SIMPLE_PINHOLE cameras) supported!
```

검사를 통과한 모델과 등록 이미지에 `image_undistorter`를 적용한다.

```bash
mkdir -p "$READY"

"$COLMAP" image_undistorter \
  --image_path "$SCENE/input" \
  --input_path "$MODEL" \
  --output_path "$READY" \
  --output_type COLMAP
```

최종 PGSR 입력은 다음 구조여야 한다.

```text
PGSR/data/tutorial/my_room_ready/
├── images/
│   └── *.jpg
└── sparse/
    ├── cameras.bin
    ├── images.bin
    └── points3D.bin
```

PGSR에는 원본 `my_room`이 아니라 왜곡 제거가 완료된 `my_room_ready`를 입력한다.

---

## 4. PGSR 학습과 Mesh 생성

### 4.1 PGSR 학습

```bash
cd PGSR
conda run --no-capture-output -n pgsr \
  python train.py \
  -s data/tutorial/my_room_ready \
  -m output/my_room \
  --max_abs_split_points 0 \
  --opacity_cull_threshold 0.05
cd ..
```

약한 무늬의 벽이 많은 실내에서는 `--max_abs_split_points 0`이 과적합을 줄이는 출발점이다. GPU 메모리가 부족하면 `-r 2`를 추가해 입력 해상도를 절반으로 낮춘다.

### 4.2 Surface Mesh 추출

```bash
cd PGSR
conda run --no-capture-output -n pgsr \
  python render.py \
  -m output/my_room \
  --max_depth 10.0 \
  --voxel_size 0.01 \
  --use_depth_filter
cd ..
```

`max_depth`는 카메라에서 가장 먼 벽보다 크게 잡되 불필요하게 키우지 않는다. `voxel_size`를 줄이면 Mesh가 세밀해지지만 메모리와 처리 시간이 증가한다.

### 필수 산출물

```text
PGSR/output/my_room/
├── point_cloud/iteration_30000/point_cloud.ply
├── mesh/tsdf_fusion_post.ply
├── cameras.json
└── cfg_args
```

### 육안 검사

`tsdf_fusion_post.ply`를 Blender, MeshLab 또는 CloudCompare에서 열고 확인한다.

- 방 전체가 한 덩어리로 연결되는가?
- 바닥·천장·주요 벽이 보이는가?
- 벽이 두 겹으로 심하게 갈라지지 않았는가?
- 카메라가 못 본 영역의 큰 구멍이 어디인가?
- 방 바깥의 떠 있는 조각이 너무 많지 않은가?

작은 잡음은 Proxy Mesh에서 생략할 수 있다. 바닥이나 주요 벽 자체가 사라졌다면 Proxy 단계에서 억지로 보완하지 말고 촬영 또는 COLMAP부터 다시 확인한다.

---

## 5. PGSR Mesh에서 Proxy Mesh 만들기

### 목표

수백만 삼각형의 상세 Mesh에서 바닥·천장·벽의 큰 평면을 찾아, Sionna RT가 안정적으로 사용할 수 있는 단순한 방 외곽을 만든다.

### 자동 실행 (선택)

PGSR output 폴더 하나만 지정하면 5.1~5.3(씬 폴더 생성, 설정 복사, 평면·벽 후보 추출)을 대신 실행하고 5.4 `pick-envelope` 명령까지 출력하는 스크립트가 있다. 이미 만든 결과가 있으면 각 단계를 건너뛴다.

```bash
conda run --no-capture-output -n pgsr \
  python scripts/init_proxy_mesh.py PGSR/output/my_room \
  --up-vector 0.0 0.0 1.0
```

`--up-vector`를 생략하면 자리표시자(Z-up)로 두고 직접 확인하라는 안내만 나온다. GUI가 없는 환경이면 `--skip-picker`를 붙여 5.4 명령만 출력하게 한다. `--scene-id`로 씬 이름을 PGSR 폴더 이름과 다르게 지정할 수 있고, `--force`로 이미 있는 결과를 다시 만들 수 있다. 5.4의 바닥·천장·벽 선택은 사람이 3D Viewer에서 직접 골라야 하므로 이 스크립트도 대신하지 않는다.

### 5.1 씬 폴더와 설정 복사

`scenes/_template/`에 장소에 매이지 않은 시작용 설정을 보관한다. 새 씬은 `scenes/<scene_id>/`에 그 씬만의 설정과 산출물을 모아 둔다.

```bash
mkdir -p scenes/my_room/configs/proxy_mesh
cp scenes/_template/configs/proxy_mesh/base.yaml \
  scenes/my_room/configs/proxy_mesh/base.yaml
cp scenes/_template/configs/proxy_mesh/envelope.yaml \
  scenes/my_room/configs/proxy_mesh/envelope.yaml
cp scenes/_template/configs/proxy_mesh/calibration_preflight.yaml \
  scenes/my_room/configs/proxy_mesh/calibration_preflight.yaml
cp scenes/_template/configs/proxy_mesh/metric_calibration.yaml \
  scenes/my_room/configs/proxy_mesh/metric_calibration.yaml
```

먼저 `scenes/my_room/configs/proxy_mesh/base.yaml`의 `scene.up_vector`를 장면의 실제 위쪽에 맞춘다. 템플릿 값(Z-up 가정)은 자리표시자일 뿐 새 장소의 정답이 아니다.

### 5.2 일반 평면 후보 추출

```bash
conda run --no-capture-output -n pgsr \
  python -m tools.proxy_mesh_editor.main extract \
  --mesh PGSR/output/my_room/mesh/tsdf_fusion_post.ply \
  --reference-point-cloud PGSR/output/my_room/point_cloud/iteration_30000/point_cloud.ply \
  --config scenes/my_room/configs/proxy_mesh/base.yaml \
  --output scenes/my_room/proxy_mesh/phase1
```

주요 결과:

```text
scenes/my_room/proxy_mesh/phase1/
├── plane_candidates.json
├── plane_candidates_colored.ply
└── candidate_meshes/
```

### 5.3 벽 후보만 별도 추출

```bash
conda run --no-capture-output -n pgsr \
  python -m tools.proxy_mesh_editor.main analyze-normals \
  --mesh PGSR/output/my_room/mesh/tsdf_fusion_post.ply \
  --reference-point-cloud PGSR/output/my_room/point_cloud/iteration_30000/point_cloud.ply \
  --config scenes/my_room/configs/proxy_mesh/base.yaml \
  --output scenes/my_room/proxy_mesh/normal_analysis

conda run --no-capture-output -n pgsr \
  python -m tools.proxy_mesh_editor.main extract-walls \
  --mesh PGSR/output/my_room/mesh/tsdf_fusion_post.ply \
  --reference-point-cloud PGSR/output/my_room/point_cloud/iteration_30000/point_cloud.ply \
  --config scenes/my_room/configs/proxy_mesh/base.yaml \
  --output scenes/my_room/proxy_mesh/wall_extraction
```

### 5.4 바닥·천장·벽 후보 선택

두 가지 방법 중 GUI 사용 가능 여부에 따라 하나를 고른다. 이 절의 예시는 벽 4개인 사각형 방을 기준으로 한다. 복도처럼 꺾이는 구간이 있는 비사각형 방은 후보 개수가 늘어나고 자동 추출이 부정확할 수 있어, 이 경우 씬별로 별도 스크립트를 작성해야 할 수 있다.

#### 방법 A: 3D Viewer에서 클릭으로 선택 (권장)

두 ply 파일을 따로 열어 번호를 눈으로 옮겨 적을 필요 없이, 뷰어 안에서 Floor·Ceiling·Wall을 직접 클릭해 고른다. `build-envelope`까지 한 번에 실행하므로 성공하면 5.4·5.5를 모두 마친 것이다.

```bash
conda run --no-capture-output -n pgsr \
  python -m tools.proxy_mesh_editor.main pick-envelope \
  --plane-candidates scenes/my_room/proxy_mesh/phase1/plane_candidates.json \
  --wall-candidates scenes/my_room/proxy_mesh/wall_extraction/wall_candidates.json \
  --envelope-config scenes/my_room/configs/proxy_mesh/envelope.yaml \
  --output scenes/my_room/proxy_mesh/room_envelope
```

`--envelope-config`에는 `floor`/`ceiling`/`ordered_walls`를 비운, validation·output 설정만 담은 YAML을 넘긴다. GUI가 열리지 않으면 6절의 GUI 문제 해결(`setup-gui-runtime`, `--software-rendering`)을 먼저 시도한다. 성공했다면 아래 방법 B와 5.5는 건너뛰고 5.6으로 이동한다.

#### 방법 B: 파일을 보고 YAML에 직접 적기 (GUI 없을 때)

다음 두 파일을 Mesh 뷰어에서 함께 확인한다.

- `scenes/my_room/proxy_mesh/phase1/plane_candidates_colored.ply`
- `scenes/my_room/proxy_mesh/wall_extraction/wall_candidates_colored.ply`

`plane_...` 또는 `wall_...` 번호를 기록한 뒤 `scenes/my_room/configs/proxy_mesh/envelope.yaml`을 수정한다.

```yaml
room_envelope:
  floor:
    candidate_id: plane_006
  ceiling:
    candidate_id: plane_005
  ordered_walls:
    - candidate_id: wall_008
    - candidate_id: wall_000
    - candidate_id: wall_001
    - candidate_id: wall_006
```

위 번호는 형식 예시일 뿐이다. 새 장면에서 나온 실제 번호를 사용한다.

벽은 방 둘레를 따라 이웃한 순서대로 적어야 한다. 순서가 뒤섞이면 교차된 방이 만들어지거나 검증이 실패한다.

### 5.5 닫힌 Room Envelope 생성

방법 A(`pick-envelope`)를 이미 실행했다면 이 단계는 끝난 것이다. 방법 B로 YAML을 직접 채웠을 때만 아래를 실행한다.

```bash
conda run --no-capture-output -n pgsr \
  python -m tools.proxy_mesh_editor.main build-envelope \
  --plane-candidates scenes/my_room/proxy_mesh/phase1/plane_candidates.json \
  --wall-candidates scenes/my_room/proxy_mesh/wall_extraction/wall_candidates.json \
  --envelope-config scenes/my_room/configs/proxy_mesh/envelope.yaml \
  --output scenes/my_room/proxy_mesh/room_envelope
```

필수 결과:

```text
scenes/my_room/proxy_mesh/room_envelope/
├── room_envelope.obj
├── room_envelope.ply
├── room_envelope.json
└── topology_report.json
```

`topology_report.json`에서 닫힌 단일 방인지 확인하고, `room_envelope.ply`를 열어 바닥·천장·벽 순서가 맞는지 육안으로 검사한다.

### 5.6 미터 단위 사전 진단

먼저 `scenes/my_room/configs/proxy_mesh/calibration_preflight.yaml` 안의 입력 경로와 실제 길이 참고값을 새 장면에 맞게 수정한다.

```bash
conda run --no-capture-output -n pgsr \
  python -m tools.proxy_mesh_editor.main calibration-preflight \
  --envelope-json scenes/my_room/proxy_mesh/room_envelope/room_envelope.json \
  --envelope-obj scenes/my_room/proxy_mesh/room_envelope/room_envelope.obj \
  --config scenes/my_room/configs/proxy_mesh/calibration_preflight.yaml \
  --output scenes/my_room/proxy_mesh/calibration_preflight
```

확인할 파일:

- `calibration_preflight_report.md`
- `scale_analysis.csv`
- `room_envelope_up_aligned.ply`
- 설정의 `output` 항목에 지정된 이름으로 생성된 보정 초안 YAML

두 기준 길이에서 얻은 배율 차이가 크면 측정한 실제 구간과 Mesh에서 선택한 구간이 같은지 먼저 확인한다.

### 5.7 미터 단위 Room 생성

`scenes/my_room/configs/proxy_mesh/metric_calibration.yaml`에서 다음을 실제 장면에 맞게 수정한다.

- `real_distance_m`
- 미터 원점으로 쓸 바닥 모서리
- `+X`로 쓸 바닥 모서리 방향
- 상태와 신뢰도

```bash
conda run --no-capture-output -n pgsr \
  python -m tools.proxy_mesh_editor.main calibrate-metric \
  --envelope-json scenes/my_room/proxy_mesh/room_envelope/room_envelope.json \
  --envelope-obj scenes/my_room/proxy_mesh/room_envelope/room_envelope.obj \
  --config scenes/my_room/configs/proxy_mesh/metric_calibration.yaml \
  --output scenes/my_room/proxy_mesh/metric_calibration
```

필수 결과:

```text
scenes/my_room/proxy_mesh/metric_calibration/
├── room_envelope_metric.obj
├── room_envelope_metric.json
├── calibration.json
├── calibration_report.md
└── calibration_validation.json
```

`calibration.json`은 PGSR 장면 좌표와 실제 미터 좌표를 서로 변환하는 핵심 파일이다.

### 5.8 (선택) 실측 치수로 최종 보정하기 — 사각형 방 전용

이 단계는 5.1~5.7을 건너뛰는 지름길이 아니다. 5.7까지 만든 `room_envelope_metric.json`·`calibration.json`을 `--legacy-metric-json`·`--legacy-calibration`으로 반드시 입력받아, 그 위에서 바닥 가로·깊이·높이차만 실측값으로 덮어쓴다. 즉 5.1~5.7이 먼저 끝나 있어야 하고, PGSR 결과는 천장 높이 분포·벽 순서 같은 형상 참고로 남는다.

또한 벽 4개인 사각형 방에서만 쓸 수 있다. 복도처럼 꺾이는 구간이 있는 비사각형 방은 이 단계를 쓰지 않고, 5.7의 `room_envelope_metric.*`을 그대로 Proxy Placement Editor에 사용한다.

사각형 방의 실측 가로·깊이·높이차가 준비됐다면 다음처럼 보정한다. `<scene_id>`와 `<session_id>`는 실제 씬·실험 세션 ID로 바꾸고, `scenes/<scene_id>/experiments/<session_id>/scene.yaml`의 `tools.rf_experiment.build-proxy-envelope`에 5.7 결과 경로(`--legacy-metric-json`, `--legacy-calibration`)를 미리 선언해 둔다.

```bash
python scripts/run_scene.py <session_id> rf_experiment build-proxy-envelope
```

결과는 다음 위치에 생긴다.

```text
scenes/<scene_id>/experiments/<session_id>/outputs/proxy_scene/
├── room_envelope_metric.obj
├── room_envelope_metric.json
├── calibration.json
├── preview_top.png
├── preview_perspective.png
└── PROXY_SCENE_BASE_REPORT.md
```

---

## 6. Proxy Placement Editor 사용

### 목표

미터 단위 Room 위에 전파에 큰 영향을 주는 구조와 AP/TX·RX 측정점을 배치한다.

### scene.yaml이 준비된 씬 실행

공용 런처는 `scenes/**/scene.yaml`을 검색한다. 방은 `scenes/<scene_id>/scene.yaml`, 날짜별 실험 세션은 `scenes/<room_id>/experiments/<session_id>/scene.yaml`에 입력·출력 경로가 선언되어 있다.

```bash
python scripts/run_scene.py <scene_id> proxy_placement_editor edit
```

이 명령은 다음 자료를 한 번에 연다.

- 실측 치수 기반 Room Proxy Mesh
- PGSR Gaussian Point Cloud
- PGSR Output Mesh
- 문·책상 등의 Scenario YAML
- AP/TX 및 RX Marker JSON

첫 실행에서 대형 PGSR Mesh를 읽는 시간이 걸릴 수 있다.

### GUI가 열리지 않을 때

RustDesk, Wayland 또는 XWayland에서 Open3D 창이 종료되면 전용 GUI 환경을 한 번 만든다.

```bash
conda run --no-capture-output -n pgsr \
  python -m tools.proxy_placement_editor.main setup-gui-runtime
```

그다음 같은 명령을 다시 실행한다. 그래도 실패하면 뒤에 소프트웨어 렌더링 플래그를 이어 붙인다.

```bash
python scripts/run_scene.py <scene_id> proxy_placement_editor edit --software-rendering
```

### 새 장면을 여는 기본 명령

새 씬은 아직 `scene.yaml`이 없으므로 처음에는 모든 경로를 직접 지정한다. 먼저 문·책상 같은 Obstacle 후보 라이브러리도 템플릿에서 복사해 온다.

```bash
mkdir -p scenes/my_room/configs/proxy_editor scenes/my_room/configs/sionna scenes/my_room/configs/rf_experiment
cp scenes/_template/configs/proxy_editor/candidates.yaml \
  scenes/my_room/configs/proxy_editor/candidates.yaml
```

```bash
conda run --no-capture-output -n pgsr \
  python -m tools.proxy_placement_editor.main edit \
  --room-obj scenes/my_room/proxy_mesh/metric_calibration/room_envelope_metric.obj \
  --room-json scenes/my_room/proxy_mesh/metric_calibration/room_envelope_metric.json \
  --calibration scenes/my_room/proxy_mesh/metric_calibration/calibration.json \
  --scenario scenes/my_room/configs/sionna/draft.yaml \
  --candidates scenes/my_room/configs/proxy_editor/candidates.yaml \
  --markers scenes/my_room/configs/rf_experiment/tx_rx.json \
  --point-cloud PGSR/output/my_room/point_cloud/iteration_30000/point_cloud.ply \
  --point-cloud-coordinate-space scene \
  --pgsr-output-mesh PGSR/output/my_room/mesh/tsdf_fusion_post.ply \
  --pgsr-output-mesh-coordinate-space scene \
  --output scenes/my_room/proxy_placement
```

새 장면에서는 먼저 기존 Scenario와 Marker 설정을 복사해 장면 ID, 좌표계 ID, 파일 경로를 맞춰야 한다. `scene.json`, Scenario YAML, `tx_rx.json`의 장면 ID가 서로 다르면 마지막 계약 검증에서 실패한다. 경로가 자리 잡으면 이 값들을 `scenes/my_room/scene.yaml`에 옮겨 적어 이후에는 `scripts/run_scene.py my_room proxy_placement_editor edit`만으로 열 수 있다.

### 화면 읽는 법

| 화면 요소 | 의미 |
|---|---|
| Point Cloud | 최종 화면용 Gaussian의 중심점 |
| Proxy Mesh | 전파 계산에 사용할 단순한 방 |
| PGSR Output Mesh | 사진에서 복원한 상세 표면 참고 |
| 장애물 객체 | 문·책상·칠판·금속 구조 등 |
| AP/TX | 실제 공유기 위치와 송신 설정 |
| 보정 RX | 보정값 학습에만 사용할 측정점 |
| Test RX | MAE·RMSE 평가에만 사용할 측정점 |

상단의 체크박스로 세 배경을 따로 켜고 끌 수 있다. Proxy와 PGSR이 심하게 어긋나면 물체 배치를 계속하지 말고 좌표 원점·축·배율부터 수정한다.

### 꼭 알아둘 조작

| 입력 | 동작 |
|---|---|
| 왼쪽 클릭 | 객체 선택 |
| 우클릭 드래그 + `W/A/S/D` | 1인칭 시점 이동 |
| `G` | 이동 |
| `R` | 회전 |
| `S` | 크기 조절 |
| `F` | 선택 객체 보기 |
| `1`, `3`, `7` | 정면·측면·윗면 |
| `Delete` | 선택 객체 삭제 |
| `Ctrl+D` | 비활성 복제 |
| `Ctrl+Z`, `Ctrl+Y` | 실행 취소·다시 실행 |
| `Ctrl+S` | 검증 후 Scenario와 Marker 저장 |

### 권장 배치 순서

1. Proxy Mesh와 PGSR Mesh의 바닥·벽이 맞는지 확인한다.
2. 문과 계단처럼 좌표 기준이 되는 구조를 먼저 배치한다.
3. 큰 책상 묶음, 칠판, 금속 구조를 배치한다.
4. 실제 AP를 `AP / TX` 객체로 추가한다.
5. 주파수와 송신 전력을 입력한다.
6. 보정 RX 4개를 추가하고 `point_id`를 고유하게 지정한다.
7. Test RX 15개를 추가하고 강의실 전체에 고르게 배치한다.
8. 각 객체의 위치·크기·방향·재질 근거를 현장 측정값과 대조한다.
9. 검증 오류를 모두 해결하고 저장한다.
10. `Build`를 눌러 Sionna Scene을 만든다.

### 가장 중요한 주의사항

Candidate를 추가하면 보이는 기본 크기는 **실제 치수가 아닌 임시값**이다.

- 실측하지 않은 객체는 `enabled`로 전파 계산에 넣지 않는다.
- `confidence: unset`, `measurement_source: unset`, `placement_status: provisional...`인 객체를 최종 결과로 해석하지 않는다.
- Test RX 값은 IDW나 Residual IDW 보정에 사용하지 않는다.
- Room·PGSR·TX/RX가 모두 같은 미터 좌표계를 쓰는지 확인한다.

### Editor 결과

```text
scenes/<scene_id>/experiments/<session_id>/outputs/proxy_placement/
├── editor_state.json
├── placement_validation.json
├── obstacles_metric.json
├── obstacle_vertices_metric.csv
├── preview/
│   ├── top_view.png
│   ├── front_view.png
│   ├── side_view.png
│   └── perspective_view.png
└── sionna_build/
    └── scene/
        └── scene.xml
```

`sionna_build/scene/scene.xml`이 장애물을 포함해 Sionna RT에 전달할 최종 장면 파일이다.

---

## 7. 현장 실측

실측은 두 부분으로 나눈다.

1. **공간 실측:** 방·문·계단·책상·AP·RX의 실제 좌표와 크기
2. **전파 실측:** 각 RX 위치에서 ESP32가 측정한 RSSI

### 7.1 공간 좌표 확정

현재 강의실 기준은 다음과 같다.

- 원점: 문 밖에서 강의실 안을 볼 때 출입문 왼쪽 아래 바닥점
- `+X`: 오른쪽 벽 방향
- `+Y`: 강의실 안쪽
- `+Z`: 위쪽
- 단위: 미터
- 좌표계: 오른손 좌표계

모든 측정은 같은 원점에서 잰 `(x, y, z)`로 기록한다. 벽마다 다른 기준점을 사용한 뒤 눈대중으로 합치지 않는다.

### 공간 실측 체크리스트

- 방 가로, 깊이, 바닥 높이차
- 문 너비, 높이, 위치
- 계단 각 단의 시작점, 폭, 깊이, 높이
- 큰 책상 묶음의 중심, 크기, 방향
- 금속 구조와 칠판의 위치, 크기
- AP 안테나 중심의 위치와 높이
- 각 RX의 안테나 중심 위치와 높이

편집기에서 임시 배치한 값과 다르면 실측값을 우선하고 다시 저장·Build한다.

### 7.2 RSSI 실험 구성

현재 논문 실험의 기본 구성은 다음과 같다.

| 구분 | 개수 | 목적 |
|---|---:|---|
| 장치 Offset 공통 위치 | 1곳 | ESP32 장치 간 편차 보정 |
| 보정 RX | 4곳 | Plain IDW와 Residual IDW 입력 |
| Test RX | 15곳 | MAE·RMSE 평가 |

각 위치는 30초 동안 측정하고, 약 1초 주기라면 위치당 약 30개 표본을 확보한다.

### 실험 전 고정

- 전용 AP의 BSSID
- Wi-Fi 채널
- AP 위치·높이·방향
- AP 송신 전력 설정
- ESP32 안테나 방향
- 측정 높이와 자세
- 문 개폐 상태
- 사람 출입 조건

### 장치 Offset 측정

1. ESP32 5대를 같은 책상 위에 나란히 둔다.
2. AP 거리, 높이, 방향을 같게 맞춘다.
3. 30초 동안 동시에 측정한다.
4. 각 장치의 Filtered RSSI 중앙값 `m_d`를 구한다.
5. 다섯 장치 중앙값의 중앙값을 `m_ref`로 정한다.
6. `device_offset_db = m_ref - m_d`로 계산한다.
7. 이후 `corrected_rssi = measured_rssi + device_offset_db`를 사용한다.

### 보정점과 Test점 측정

1. 보정점 4곳은 강의실 앞·중간·뒤와 서로 다른 높이를 포함하게 고른다.
2. Test점 15곳은 방 전체를 고르게 덮되 보정점과 겹치지 않게 한다.
3. 각 위치에서 30초 동안 장치를 움직이지 않는다.
4. 몸으로 AP를 가리지 않고 안테나 방향을 일정하게 유지한다.
5. 측정 직후 Backend에서 표본 수와 Node ID를 확인한다.
6. 누락 위치는 현장을 떠나기 전에 다시 측정한다.

### 7.3 CSV 만들기

Backend에서 다음 두 파일을 내보낸다. 현재 저장소는 이 파일들의 고정 보관 경로를 강제하지 않으므로, 아래 검증·분석 명령의 자리표시자를 실제 파일 경로로 바꾼다.

```text
<measurements_raw.csv>
<measurements_summary.csv>
```

Raw CSV 필수 열:

```text
experiment_id,session_id,point_id,point_role,node_id,timestamp,seq,
rssi_raw_dbm,rssi_filtered_dbm,sample_count,error_flags,device_offset_db,
pos_x,pos_y,pos_z,ap_bssid,ap_channel,valid
```

Summary CSV 필수 열:

```text
point_id,point_role,node_id,x,y,z,sample_count,median_raw,median_filtered,
mean_filtered,std_filtered,device_offset_db,corrected_rssi
```

위 두 줄은 보기 쉽게 줄을 나눈 것이다. 실제 CSV Header는 한 줄이어야 한다.

위치별 대표값은 유효한 30초 표본의 Filtered RSSI 중앙값에 장치 Offset을 더한 값으로 만든다. 현재 이 저장소의 `rf_experiment` 도구는 CSV 계약을 검증하고 분석하지만, Backend Raw CSV를 Summary CSV로 자동 집계하는 명령은 제공하지 않는다. Summary는 Backend 내보내기 또는 별도 전처리에서 위 규칙대로 생성해야 한다.

### CSV 검증

```bash
RAW_CSV=/absolute/path/to/measurements_raw.csv
SUMMARY_CSV=/absolute/path/to/measurements_summary.csv

python -m tools.rf_experiment.main validate-csv \
  --kind raw \
  --csv "$RAW_CSV" \
  --require-rows

python -m tools.rf_experiment.main validate-csv \
  --kind summary \
  --csv "$SUMMARY_CSV" \
  --require-rows
```

오류가 나면 분석을 강행하지 말고 누락 열, 빈 좌표, 잘못된 `point_role`, 숫자가 아닌 RSSI를 먼저 수정한다.

---

## 8. Sionna RT 결과 만들기

### 8.1 실행 전 계약 검사

```bash
python -m tools.rf_experiment.main validate-contracts \
  --scene scenes/<scene_id>/experiments/<session_id>/configs/scene.json \
  --markers scenes/<scene_id>/experiments/<session_id>/configs/tx_rx.json \
  --methods scenes/<scene_id>/experiments/<session_id>/configs/method_config.json
```

초안 단계에서 `ready: false`와 경고가 나오는 것은 정상이다. 현장 입력을 모두 확정한 뒤에는 다음 명령이 exit code 0으로 끝나야 한다.

```bash
python -m tools.rf_experiment.main validate-contracts \
  --scene scenes/<scene_id>/experiments/<session_id>/configs/scene.json \
  --markers scenes/<scene_id>/experiments/<session_id>/configs/tx_rx.json \
  --methods scenes/<scene_id>/experiments/<session_id>/configs/method_config.json \
  --require-ready
```

단순히 경고를 없애기 위해 `status`만 `ready`로 바꾸면 안 된다. TX 1개, 보정 RX 4개, Test RX 15개의 실제 좌표와 Proxy Scene 검증이 끝난 뒤 변경한다.

### 8.2 장애물 포함 Sionna 실행

Proxy Placement Editor에서 저장 후 `Build`를 눌러 `scene.xml`을 만든다.

```bash
conda run --no-capture-output -n sionna \
  python scripts/run_scene.py <session_id> rf_experiment run-sionna \
  --scene-xml scenes/<scene_id>/experiments/<session_id>/outputs/proxy_placement/sionna_build/scene/scene.xml
```

주요 결과:

```text
scenes/<scene_id>/experiments/<session_id>/outputs/sionna/
├── processed/
│   ├── sionna_points.csv
│   └── sionna_grid.csv
└── ...
```

- `sionna_points.csv`: 보정점과 Test점의 Sionna 예측 RSSI
- `sionna_grid.csv`: 2차원 히트맵용 격자 RSSI

`scene.xml`을 넘기지 않으면 기본 Metric Envelope만 사용하므로, 문·책상·AP 형상을 포함한 결과가 필요할 때는 `--scene-xml`을 생략하지 않는다.

---

## 9. 최종 비교 결과 만들기

세 방법을 비교한다.

| 방법 | 의미 |
|---|---|
| Raw Sionna RT | 물리 시뮬레이션 예측을 그대로 사용 |
| Plain IDW | 보정점 4개의 실측 RSSI만 거리 가중 보간 |
| Sionna RT + Residual IDW | Sionna 오차를 보정점에서 구해 공간 보간 |

Test점 15개는 평가에만 사용하며 보정값 계산에 섞지 않는다.

### 분석 실행

```bash
SUMMARY_CSV=/absolute/path/to/measurements_summary.csv

python scripts/run_scene.py <session_id> rf_experiment analyze \
  --summary "$SUMMARY_CSV" \
  --sionna-points scenes/<scene_id>/experiments/<session_id>/outputs/sionna/processed/sionna_points.csv \
  --sionna-grid scenes/<scene_id>/experiments/<session_id>/outputs/sionna/processed/sionna_grid.csv
```

### 확인할 결과

```text
scenes/<scene_id>/experiments/<session_id>/outputs/analysis/
├── processed/
│   ├── comparison_results.csv
│   ├── metrics.csv
│   ├── grid_predictions.csv
│   └── analysis_report.json
├── figures/
│   ├── measured_points.png
│   ├── prediction_vs_measurement.png
│   ├── raw_sionna_heatmap.png
│   ├── plain_idw_heatmap.png
│   └── residual_idw_heatmap.png
└── ...
```

실제 파일명은 분석 도구 버전에 따라 조금 다를 수 있으므로 명령 출력과 생성된 보고서도 함께 확인한다.

### 결과를 읽는 법

- MAE가 낮을수록 평균적인 예측 오차가 작다.
- RMSE가 낮을수록 큰 오차가 적다.
- 세 히트맵은 같은 색 범위를 사용해야 공정하게 비교할 수 있다.
- `Sionna RT + Residual IDW`가 항상 가장 좋다고 가정하지 않는다.
- 결과가 나쁘면 알고리즘을 먼저 바꾸지 말고 좌표축, 미터 단위, TX/RX 높이, Offset 부호, BSSID, Sionna dBm 변환을 먼저 검사한다.
- Test점 결과를 보고 IDW 파라미터를 맞추면 평가 데이터 누수가 된다.

---

## 10. 단계별 완료 기준

| 단계 | 완료로 볼 수 있는 증거 |
|---|---|
| 사진 촬영 | 흐림이 적고 방 전체를 겹쳐 찍은 원본과 실제 길이 기록 |
| COLMAP | 대부분의 사진이 하나의 Sparse Model에 등록 |
| PGSR | `point_cloud.ply`와 `tsdf_fusion_post.ply` 생성 |
| Proxy Mesh | 닫힌 Room OBJ·JSON과 정상 topology 보고서 |
| 미터 보정 | `calibration.json` 생성, 기준 길이 오차 허용 범위 통과 |
| Editor | 실측한 장애물·AP·RX 저장, 배치 검증 통과 |
| 실측 | Offset 1곳, 보정 4곳, Test 15곳의 Raw·Summary CSV |
| Sionna | 지점 예측 CSV와 Grid CSV 생성 |
| 최종 결과 | 세 방법의 MAE·RMSE, 위치별 비교표, 같은 색 범위의 히트맵 |

---

## 11. 자주 발생하는 문제

| 증상 | 먼저 확인할 것 | 조치 |
|---|---|---|
| COLMAP 등록 사진이 적음 | 겹침, 흔들림, 흰 벽, 반복 무늬 | 문제 사진 제거 또는 끊긴 구간 재촬영 |
| OpenCV가 MP4/MOV를 열지 못함 | 영상 코덱, OpenCV FFmpeg 지원 | 영상을 H.264 MP4로 변환하거나 OpenCV 환경 점검 |
| 영상 프레임이 너무 많음 | 추출 FPS와 촬영 시간 | 10 FPS를 기준으로 조정하고 중복·흐림 프레임 정리 |
| 영상 추출 결과가 원본보다 밝음 | 아이폰 HLG HDR, `color_transfer` | `ffprobe`로 확인하고 HLG이면 BT.709 SDR 톤 매핑 적용 |
| PGSR가 `camera model not handled`로 종료됨 | `SIMPLE_RADIAL`을 직접 학습에 사용 | `image_undistorter`를 실행하고 `_ready` 데이터셋으로 학습 |
| PGSR 벽이 찢어짐 | 카메라 Pose, 시점 부족, `max_depth` | COLMAP부터 확인하고 필요 시 재촬영 |
| 평면 후보가 엉뚱함 | `scene.up_vector`, 거리 임계값 | 위쪽 벡터를 먼저 수정한 뒤 재추출 |
| Room Envelope가 꼬임 | `ordered_walls` 순서 | 방 둘레의 실제 이웃 순서로 다시 지정 |
| Proxy와 PGSR가 어긋남 | 원점, 축, 배율, calibration | 물체 배치 전에 좌표 변환부터 재생성 |
| Editor 창이 바로 종료됨 | Open3D와 Wayland/XWayland | `setup-gui-runtime`, `--software-rendering` |
| 객체가 보이지만 결과에 없음 | `enabled: false` | 실측한 객체만 명시적으로 활성화 |
| Sionna가 실행을 거부함 | Scene/Marker `draft`, 개수 부족 | 실제 입력을 완료하고 계약 검증 |
| Sionna 결과가 터무니없음 | cm/m 혼동, TX 높이·출력, 좌표축 | 단위와 TX/RX 좌표부터 재검증 |
| 분석에서 점이 누락됨 | `point_id` 불일치 | Marker, Summary, Sionna CSV의 ID 통일 |
| Residual IDW가 더 나쁨 | 데이터 누수보다 좌표·Offset 오류 우선 | 점검 순서에 따라 원인을 분리 |

---

## 12. 이어서 작업할 때의 빠른 실행 요약

이미 PGSR 학습과 5.1~5.7의 기본 Proxy 결과가 있는 씬에서 이어서 작업할 때의 최소 순서다. `<scene_id>`·`<session_id>`를 실제 값으로 바꾼다. 1번은 사각형 방(5.8 대상)에만 해당하며, 비사각형 방은 5.7 결과를 그대로 쓰고 1번을 건너뛴다.

```bash
cd /data/RFVisualizer_Workspace/RFVisualizer

RAW_CSV=/absolute/path/to/measurements_raw.csv
SUMMARY_CSV=/absolute/path/to/measurements_summary.csv

# 1. (사각형 방만) 실측 치수로 기본 Room 재보정
python scripts/run_scene.py <session_id> rf_experiment build-proxy-envelope

# 2. 문·책상·AP·RX 배치
python scripts/run_scene.py <session_id> proxy_placement_editor edit

# 3. Scene/Marker/분석 설정 검사
python -m tools.rf_experiment.main validate-contracts \
  --scene scenes/<scene_id>/experiments/<session_id>/configs/scene.json \
  --markers scenes/<scene_id>/experiments/<session_id>/configs/tx_rx.json \
  --methods scenes/<scene_id>/experiments/<session_id>/configs/method_config.json

# 4. 현장 CSV 검사
python -m tools.rf_experiment.main validate-csv \
  --kind raw \
  --csv "$RAW_CSV" \
  --require-rows

python -m tools.rf_experiment.main validate-csv \
  --kind summary \
  --csv "$SUMMARY_CSV" \
  --require-rows

# 5. 장애물 포함 Sionna 계산
conda run --no-capture-output -n sionna \
  python scripts/run_scene.py <session_id> rf_experiment run-sionna \
  --scene-xml scenes/<scene_id>/experiments/<session_id>/outputs/proxy_placement/sionna_build/scene/scene.xml

# 6. 세 방법 비교와 최종 그림 생성
python scripts/run_scene.py <session_id> rf_experiment analyze \
  --summary "$SUMMARY_CSV" \
  --sionna-points scenes/<scene_id>/experiments/<session_id>/outputs/sionna/processed/sionna_points.csv \
  --sionna-grid scenes/<scene_id>/experiments/<session_id>/outputs/sionna/processed/sionna_grid.csv
```

---

## 마지막 정리

**기억할 것:** PGSR Mesh는 실제 공간을 보는 기준이고, 최종 전파 결과의 신뢰도는 단순한 Proxy Mesh를 실제 미터 좌표·AP·RX·주요 장애물 실측값으로 얼마나 정확히 맞췄는지에 달려 있다.
