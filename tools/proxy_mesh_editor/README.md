# PGSR 평면 Proxy Mesh 기술 검증 도구

PGSR의 삼각형 메시에서 큰 평면 후보를 찾고, 사람이 선택한 후보를 단순 메시로 바꾸는 도구다. Phase 1의 일반 평면 추출, Phase 1.5-A의 법선 분석·벽 전용 추출, Phase 1.5-B의 닫힌 Room Envelope 생성, Phase 1.5-C의 사전 진단과 실제 크기 표준 좌표 사본 생성을 제공한다. 자동 분류 결과는 제안일 뿐이며 최종 의미와 방 둘레 순서는 설정에서 사람이 지정한다.

## 이번 단계에서 하는 일

```text
PGSR PLY 메시
  → 삼각형 표면에서 점을 고르게 뽑음
  → 선택적 전처리
  → 반복 RANSAC 평면 검출
  → 후보별 통계·색상 PLY·사각형 PLY
  → 사용자가 후보 선택
  → 객체별 OBJ + 통합 OBJ + MTL + JSON
```

문·칠판·책상용 이름은 자료 구조와 OBJ 출력에서 받을 수 있지만, 이 단계에서 해당 물체의 형상을 자동 생성하지는 않는다. Sionna RT 장면 변환도 다음 단계 범위다.

## 점을 만드는 방식과 선택 이유

| 방식 | 장점 | 문제 | 사용 여부 |
|---|---|---|---|
| 메시 꼭짓점 | 가장 빠름 | 삼각형이 촘촘한 곳이 과대표현됨 | 설정으로 지원 |
| 삼각형 표면 균일 표본 | 표면적에 비례해 점을 뽑아 밀도 편향을 줄임 | 표본 수만큼 계산 필요 | **기본값** |
| 점 사이 간격을 균등화한 표본 | 점 분포가 가장 고름 | 계산량이 커 기술 검증에 과함 | 이번 단계 제외 |

실제 `tsdf_fusion_post.ply`는 약 367만 꼭짓점과 693만 삼각형으로 매우 촘촘하다. 따라서 꼭짓점을 그대로 쓰지 않고 삼각형 면적에 비례한 균일 표본을 기본값으로 정했다. 이후 격자 단위로 가까운 점을 합쳐 반복 평면 검출 비용을 줄인다.

Open3D의 평면 분할은 [공식 `segment_plane` 설명](https://www.open3d.org/docs/latest/tutorial/Basic/python_interface.html), 메시 연결 조각 필터는 [공식 연결 요소 설명](https://open3d.org/docs/latest/tutorial/Basic/mesh.html)을 기준으로 구현했다.

## 실행 환경

저장소의 기존 `pgsr` Conda 환경에서 확인했다.

```bash
conda activate pgsr
python -c "import open3d, yaml, numpy; print(open3d.__version__)"
```

별도 환경에서는 다음 의존성을 설치한다.

```bash
python -m pip install -r tools/proxy_mesh_editor/requirements.txt
```

## 1단계: 후보 추출

저장소 루트에서 실행한다.

```bash
conda run -n pgsr python -m tools.proxy_mesh_editor.main extract \
  --mesh PGSR/output/pnu_classroom/mesh/tsdf_fusion_post.ply \
  --reference-point-cloud PGSR/output/pnu_classroom/point_cloud/iteration_30000/point_cloud.ply \
  --config tools/proxy_mesh_editor/configs/pnu_classroom.yaml \
  --output scenes/pnu_classroom/proxy_mesh/phase1
```

기본 `point_source`는 `mesh_uniform`이므로 참고 점구름은 기록만 하고 평면 검출에는 쓰지 않는다. 참고 점구름을 직접 쓰려면 YAML에서 `reference_point_cloud`로 바꾼다.

주요 결과:

```text
plane_candidates.json
plane_candidates_colored.ply
candidate_meshes/plane_000.ply
candidate_meshes/plane_001.ply
...
```

- 색상 점구름: 후보마다 다른 색, 선택되지 않은 점은 회색
- 후보 PLY: 실제 내부점을 잇는 복잡한 표면이 아니라 생성 예정인 네 꼭짓점 사각형
- JSON: 평면식, 법선, 중심, 점 수, 오차, 사각형 크기·모서리, 분류 제안과 근거

## 2단계: 선택 후보 내보내기

색상 PLY와 JSON을 Blender, MeshLab 또는 Open3D에서 확인한 뒤 YAML의 `selection`을 수정한다.

```yaml
selection:
  - candidate_id: plane_000
    semantic: floor
  - candidate_id: plane_001
    semantic: wall
```

그다음 실행한다.

```bash
conda run -n pgsr python -m tools.proxy_mesh_editor.main export \
  --candidates scenes/pnu_classroom/proxy_mesh/phase1/plane_candidates.json \
  --config tools/proxy_mesh_editor/configs/pnu_classroom.yaml \
  --output scenes/pnu_classroom/proxy_mesh/phase1
```

결과:

```text
proxy_scene.obj
proxy_scene.mtl
scene_metadata.json
objects/floor_000.obj
objects/wall_000.obj
...
```

통합 OBJ와 객체별 OBJ는 같은 좌표 문자열을 사용한다. 각 사각형은 꼭짓점 4개와 삼각형 2개이며, 삼각형 감김 방향은 저장된 법선과 일치한다.

## Phase 1.5-A: 법선 분석

일반 평면 추출과 같은 장면 로드·전처리를 거친 뒤, 점 법선과 높이 방향의 절댓값 내적을 분석한다.

```bash
conda run -n pgsr python -m tools.proxy_mesh_editor.main analyze-normals \
  --mesh PGSR/output/pnu_classroom/mesh/tsdf_fusion_post.ply \
  --reference-point-cloud PGSR/output/pnu_classroom/point_cloud/iteration_30000/point_cloud.ply \
  --config tools/proxy_mesh_editor/configs/pnu_classroom.yaml \
  --output scenes/pnu_classroom/proxy_mesh/normal_analysis
```

`abs(normal · up)`이 0에 가까울수록 벽과 같은 수직면이고, 1에 가까울수록 바닥·천장·책상 상판과 같은 수평면이다. 기준값별 PLY, 수평점 PLY, 히스토그램 CSV, 분석 JSON이 생성된다. 유효하지 않은 법선은 통계에 기록하되 미리보기에서는 제외한다.

## Phase 1.5-A: 벽 전용 평면 추출

벽 추출은 일반 RANSAC의 잔여점을 사용하지 않는다. 전처리 직후 원본 점구름에서 수직면 가능 점을 고른 뒤 별도 RANSAC을 실행한다.

```bash
conda run -n pgsr python -m tools.proxy_mesh_editor.main extract-walls \
  --mesh PGSR/output/pnu_classroom/mesh/tsdf_fusion_post.ply \
  --reference-point-cloud PGSR/output/pnu_classroom/point_cloud/iteration_30000/point_cloud.ply \
  --config tools/proxy_mesh_editor/configs/pnu_classroom.yaml \
  --output scenes/pnu_classroom/proxy_mesh/wall_extraction
```

검출된 평면의 법선도 다시 검사한다. 같은 RANSAC 평면에 속한 끊어진 연결 묶음은 설정에 따라 합칠 수 있지만, 서로 다른 벽 후보끼리는 합치지 않는다. 결과는 다음과 같다.

```text
wall_candidates.json
wall_candidates_colored.ply
wall_residual_points.ply
wall_candidate_meshes/wall_000.ply ...
```

일반 후보와 벽 후보를 함께 내보내려면 선택 설정에 `wall_*` 후보를 넣고 다음처럼 실행한다.

```bash
conda run -n pgsr python -m tools.proxy_mesh_editor.main export \
  --candidates scenes/pnu_classroom/proxy_mesh/phase1/plane_candidates.json \
  --wall-candidates scenes/pnu_classroom/proxy_mesh/wall_extraction/wall_candidates.json \
  --config path/to/selection.yaml \
  --output scenes/pnu_classroom/proxy_mesh/phase1_5
```

기존 `--candidates`만 사용하는 방식도 그대로 동작한다.

## Phase 1.5-B: 닫힌 Room Envelope 생성

Room Envelope는 후보 사각형의 크기를 이어 붙이지 않는다. 별도 설정에서 고른 바닥·천장·벽의 **무한 평면식**을 사용해 인접 벽 두 개와 바닥 또는 천장의 세 평면 교점을 계산한다.

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

벽은 실제 방 둘레의 연속 순서로 3개 이상 지정해야 한다. 시계·반시계 방향은 모두 받을 수 있으며 내부에서는 높이 방향에서 보았을 때 반시계 방향으로 정규화한다. 외곽 벽 후보는 코드가 자동 선택하지 않는다.

```bash
conda run -n pgsr python -m tools.proxy_mesh_editor.main build-envelope \
  --plane-candidates scenes/pnu_classroom/proxy_mesh/phase1/plane_candidates.json \
  --wall-candidates scenes/pnu_classroom/proxy_mesh/wall_extraction/wall_candidates.json \
  --envelope-config tools/proxy_mesh_editor/configs/pnu_classroom_envelope.yaml \
  --output scenes/pnu_classroom/proxy_mesh/room_envelope
```

바닥과 천장은 NumPy 기반의 결정적인 ear clipping으로 삼각분할하므로 볼록·오목 단순 다각형을 모두 지원한다. 서로 교차하는 벽 순서는 오류 처리한다. 출력은 다음과 같다.

```text
room_envelope.obj
room_envelope.mtl
room_envelope.ply
room_envelope.json
topology_report.json
objects/floor_000.obj
objects/ceiling_000.obj
objects/wall_000.obj ...
```

통합 OBJ는 아래쪽 `N`개와 위쪽 `N`개, 총 `2N`개의 전역 꼭짓점을 모든 객체가 공유한다. 모든 삼각형 법선은 계산된 내부점 반대 방향으로 맞추며 경계 모서리, 비다양체 모서리, 연결 요소, 부피와 Euler 값을 검사한다.

## Phase 1.5-C 사전 준비: 실제 크기와 좌표계 진단

이 명령은 실제 미터 단위 변환을 적용하기 전에 입력이 안전한지 확인한다. Room Envelope의 위쪽 방향과 바닥·천장 관계를 검사하고, 장면의 위쪽을 `+Z`에 맞추는 순수 회전, 단일 배율 후보, 원점과 X축 후보를 계산한다.

```bash
conda run -n pgsr python -m tools.proxy_mesh_editor.main calibration-preflight \
  --envelope-json scenes/pnu_classroom/proxy_mesh/room_envelope/room_envelope.json \
  --envelope-obj scenes/pnu_classroom/proxy_mesh/room_envelope/room_envelope.obj \
  --config tools/proxy_mesh_editor/configs/pnu_classroom_calibration_preflight.yaml \
  --output scenes/pnu_classroom/proxy_mesh/calibration_preflight
```

주요 결과:

```text
calibration_preflight.json
calibration_preflight_report.md
scale_analysis.csv
room_envelope_up_aligned.obj
room_envelope_up_aligned.ply
coordinate_axes.ply
pnu_classroom_metric_calibration_draft.yaml
```

`room_envelope_up_aligned.*`에는 위쪽 정렬 회전만 적용된다. 실제 배율, 원점 이동, 바닥 평탄화는 적용하지 않는다. 배율 기준값은 모두 양수여야 하며, 두 기준의 상대 차이가 5%를 넘으면 경고하고 20%를 넘으면 사전 진단을 실패 처리한다. 현재 강의실 기준값은 사진 기반 추정치이므로 생성된 설정 초안도 `provisional` 상태다.

좌표축 PLY의 색은 X축 빨강, Y축 초록, Z축 파랑, 원래 장면 위쪽 노랑, 목표 위쪽 청록, 바닥점 어두운색, 천장점 밝은 분홍색이다. 실제 결과와 수치는 [Phase 1.5-C 사전 진단 결과](PHASE1_5C_PREFLIGHT_VALIDATION.md)에 기록했다.

## Phase 1.5-C: 실제 크기와 표준 좌표계 생성

사전 진단에서 확인한 원점과 X축 모서리를 설정에 명시한 뒤, Room Envelope의 실제 미터 단위 사본을 만든다. 원본 OBJ와 JSON은 읽기만 하며 수정하지 않는다.

```bash
conda run -n pgsr python -m tools.proxy_mesh_editor.main calibrate-metric \
  --envelope-json scenes/pnu_classroom/proxy_mesh/room_envelope/room_envelope.json \
  --envelope-obj scenes/pnu_classroom/proxy_mesh/room_envelope/room_envelope.obj \
  --config tools/proxy_mesh_editor/configs/pnu_classroom_metric_calibration.yaml \
  --output scenes/pnu_classroom/proxy_mesh/metric_calibration
```

변환은 하나의 양수 배율 `s`, 오른손 좌표계 회전 `R`, 설정에 고정한 원점 `o`를 사용한다.

```text
p_metric = s · R · (p_scene - o)
```

현재 강의실 설정은 바닥점 `0`을 원점, 바닥 모서리 `2→3`의 위쪽 성분을 제거한 방향을 `+X`, 기존 `scene.up_vector`를 `+Z`로 사용한다. 실제 모서리 자체의 높이 차이는 그대로 보존되므로 변환된 모서리에 작은 Z 성분이 있을 수 있지만, 그 수평 투영은 정확히 `+X`다.

주요 결과:

```text
room_envelope_metric.obj
room_envelope_metric.mtl
room_envelope_metric.ply
room_envelope_metric.json
calibration.json
calibration_report.md
calibration_validation.json
metric_coordinate_axes.ply
```

`calibration.json`의 `T_metric_from_scene`과 `T_scene_from_metric`은 이후 전파 시뮬레이션 좌표와 원본 장면 좌표를 오갈 때 사용한다. OBJ의 객체·그룹·재질·면 순서와 감김 방향은 유지한다. 면적은 `s²`, 부피는 `s³`, 평면식과 모든 기하 메타데이터는 미터 좌표로 다시 계산한다. 실제 결과는 [Phase 1.5-C 검증 결과](PHASE1_5C_VALIDATION.md)에 기록했다.

## 설정할 때 주의할 값

현재 PGSR 장면은 실제 미터로 보정되지 않았다. `*_ratio` 값은 **메시 경계 상자의 대각선 길이**를 기준으로 계산한다.

| 설정 | 뜻 |
|---|---|
| `scene.up_vector` | 장면의 위쪽 방향. 영벡터는 오류 처리한다. |
| `scene.point_source` | `mesh_uniform`, `mesh_vertices`, `reference_point_cloud` 중 하나 |
| `voxel_size_ratio` | 가까운 점을 하나로 합칠 격자 크기 비율 |
| `distance_threshold_ratio` | 점이 평면에 속한다고 볼 최대 거리 비율 |
| `min_area_ratio` | 장면 대각선 제곱에 대한 최소 사각형 면적 비율 |
| `lower/upper_percentile` | 소수 이상점 때문에 사각형이 과도하게 커지는 것을 막는 범위 |
| `margin_ratio` | 잘린 경계 바깥으로 추가할 여유 비율 |
| `normal_analysis.thresholds` | 수직면 가능 점 미리보기를 만들 절댓값 내적 기준 목록 |
| `wall_extraction.normal_filter.point_normal_max_up_dot` | 벽 RANSAC에 보낼 점 법선의 최대 절댓값 내적 |
| `wall_extraction.ransac.plane_normal_max_up_dot` | 검출된 평면을 벽으로 승인할 최대 절댓값 내적 |
| `wall_extraction.components.min_vertical_span_ratio` | 연결 묶음이 가져야 할 최소 수직 길이의 장면 높이 비율 |
| `room_envelope.ordered_walls` | 사용자가 확인한 외곽 벽 후보의 연속 순서 |
| `room_envelope.validation.plane_residual_tolerance` | 교점이 선택 평면 위에 있다고 볼 최대 오차 |
| `room_envelope.validation.minimum_height_ratio` | 최소 방 높이의 장면 대각선 비율 |
| `calibration_preflight.scale_references` | 임시 배율을 계산할 장면 길이와 추정 실제 길이 목록 |
| `calibration_preflight.scale_analysis.warning_relative_spread` | 기준 배율 차이를 경고할 상대 범위 |
| `calibration_preflight.orientation.target_up` | 순수 회전으로 맞출 목표 위쪽 방향. 현재는 `+Z` |
| `calibration_preflight.validation.*` | 양의 높이, 위쪽 정렬, 직교성, 왕복 변환의 허용 오차 |
| `metric_calibration.scale.references` | 단일 배율을 다시 계산할 장면 길이와 실제 미터 길이 |
| `metric_calibration.coordinate_frame.origin` | 미터 좌표 원점으로 사용할 바닥점의 고정 번호 |
| `metric_calibration.coordinate_frame.x_axis` | 수평 투영을 `+X`로 사용할 방향성 바닥 모서리 |
| `metric_calibration.validation.*` | 기준 길이 오차, 회전, 왕복 변환, 평면, 위상 허용 조건 |

`pnu_classroom.yaml`은 넓은 바닥 후보의 법선과 카메라 높이 변화가 가장 작아지는 방향을 함께 확인해, `-Y`에서 약 7도 기울어진 방향을 위쪽으로 설정했다. 이는 장면별 설정이며 다른 장소에 그대로 적용하면 안 된다.

## 현재 한계

- 같은 평면 위에 떨어져 있는 여러 물체가 있으면 하나의 큰 사각형으로 합쳐질 수 있다.
- 벽 전용 추출에서도 같은 방향의 평행한 표면이 여러 후보로 나뉠 수 있다. 후보끼리 합치거나 모서리를 맞추는 일은 이후 단계다.
- Room Envelope는 외곽 후보를 자동으로 고르지 않으며 잘못된 벽 순서는 오류 또는 잘못된 방 범위를 만든다.
- Room Envelope는 완전히 닫힌 껍질만 만들며 문·창문 구멍과 비평면 구조를 지원하지 않는다.
- `floor`, `wall`, `ceiling`은 법선과 장면 높이만 사용한 제안이다.
- 사각형은 의도적으로 구멍을 막으므로, 문처럼 실제로 통과 가능한 구간은 이후 편집 단계에서 별도 처리해야 한다.
- 일반 추출·Room Envelope·사전 진단 결과는 원본 장면 단위를 유지한다. 미터 단위 결과는 `calibrate-metric`의 별도 출력만 사용한다.
- 현재 실제 크기 결과는 사진 기반 문 규격을 사용한 임시값이다. 현장 실측 뒤 `pnu_classroom_metric_calibration.yaml`의 기준 길이만 바꾸고 다시 실행해야 한다.

## 테스트

Open3D 없이도 핵심 계산과 OBJ 형식을 검사할 수 있다.

```bash
conda run -n pgsr python -m pip install -r tools/proxy_mesh_editor/requirements-test.txt
conda run -n pgsr python -m pytest -q tools/proxy_mesh_editor/tests
```
