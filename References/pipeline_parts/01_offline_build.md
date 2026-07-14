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

PGSR 메시의 큰 평면을 단순한 Proxy Geometry로 바꾸는 현재 도구는 일반 평면 추출과 벽 전용 추출을 분리한다. 벽 전용 경로는 일반 추출의 잔여점에 의존하지 않고, 같은 전처리 원본에서 점 법선이 수직면에 가까운 점만 골라 별도 RANSAC을 실행한다. 이 벽 추출 단계 자체는 후보 회수까지만 담당하고, 방 외곽 생성은 다음 Room Envelope 단계가 담당한다.

선택된 바닥·천장·벽 후보로 Room Envelope를 만들 때는 후보 사각형을 연결하지 않고 무한 평면 교점으로 공통 아래·위 모서리를 계산한다. 통합 OBJ는 모든 면이 전역 꼭짓점을 공유하는 닫힌 manifold이며, 외곽 벽 후보와 순서는 별도 설정에서 사람이 지정한다. 문 구멍과 실제 길이 보정은 이 단계에 포함하지 않는다.

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

Proxy Mesh Editor는 사전 진단 뒤 닫힌 Room Envelope의 별도 미터 좌표 사본을 만든다. 설정에 고정한 바닥점을 원점, 선택한 바닥 모서리의 수평 투영을 `+X`, `scene.up_vector`를 `+Z`로 사용하고, 하나의 양수 배율과 순수 회전만 적용한다. 정방향·역방향 4×4 행렬도 함께 저장한다. 원본 장면과 Room Envelope는 수정하지 않으며, 바닥·천장 경사를 강제로 평탄화하지 않는다. 현재 사진 기반 문 크기는 임시 추정치이므로 현장 실측 뒤 이 단계만 다시 실행해야 한다.

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

Phase 2-A 연결 시험에서는 미터 단위 Room Envelope를 객체별 PLY와 Mitsuba XML로 변환하고, Sionna RT의 공식 ITU concrete preset으로 빈 방을 구성했다. 2.4GHz에서 LoS 거리, 최대 2회 정반사, 높이 1.5m의 1m 격자 path-gain 지도가 실제 solver로 계산되는 것을 확인했다. 이 결과는 좌표·장면·API 연결 검증이며 실제 재질이나 RSSI 정확도를 입증하지 않는다.

Phase 2-B에서는 Room Envelope를 수정하지 않고 큰 장애물을 별도 Proxy Obstacle shape로 추가하는 경로를 검증했다. 검증 전용 synthetic wood blocker로 동일한 TX/RX·solver·seed·격자를 사용한 A/B 실험을 수행해 `rx_los` 직접 경로가 사라지고 Coverage가 baseline 반복 noise보다 크게 달라지는 것을 확인했다. 실제 책상·칠판·문은 위치와 크기를 측정하기 전까지 비활성 template로만 유지하며, 이 결과 역시 실제 강의실 재질이나 RSSI 정확도를 뜻하지 않는다.

Phase 2-C의 Proxy Placement Editor는 이 비활성 template와 Phase 2-B schema를 그대로 사용한다. 미터 좌표의 Room Envelope와 선택적 PGSR/TSDF reference를 함께 표시하고 사람이 box·thin panel의 위치·yaw·크기·재질 근거를 입력한다. 경사진 바닥에서는 회전된 bottom vertex 전체의 최소 여유를 맞출 수 있으며, Room과 calibration 원본은 읽기 전용이다. Candidate 기본 크기는 UI placeholder이고 사용자가 명시적으로 활성화하기 전에는 Sionna 장면에 포함하지 않는다.

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
