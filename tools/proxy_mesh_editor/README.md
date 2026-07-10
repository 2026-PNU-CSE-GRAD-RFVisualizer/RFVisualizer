# PGSR 평면 Proxy Mesh 기술 검증 도구

PGSR의 삼각형 메시에서 큰 평면 후보를 찾고, 사람이 선택한 후보를 구멍 없는 사각형 OBJ로 바꾸는 **비화면 방식 Phase 1 도구**다. 자동 분류 결과는 제안일 뿐이며 최종 의미는 `selection`에서 사람이 지정한다.

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
  --output outputs/proxy_mesh/pnu_classroom/phase1
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
  --candidates outputs/proxy_mesh/pnu_classroom/phase1/plane_candidates.json \
  --config tools/proxy_mesh_editor/configs/pnu_classroom.yaml \
  --output outputs/proxy_mesh/pnu_classroom/phase1
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

`pnu_classroom.yaml`은 넓은 바닥 후보의 법선과 카메라 높이 변화가 가장 작아지는 방향을 함께 확인해, `-Y`에서 약 7도 기울어진 방향을 위쪽으로 설정했다. 이는 장면별 설정이며 다른 장소에 그대로 적용하면 안 된다.

## 현재 한계

- 같은 평면 위에 떨어져 있는 여러 물체가 있으면 하나의 큰 사각형으로 합쳐질 수 있다.
- `floor`, `wall`, `ceiling`은 법선과 장면 높이만 사용한 제안이다.
- 사각형은 의도적으로 구멍을 막으므로, 문처럼 실제로 통과 가능한 구간은 이후 편집 단계에서 별도 처리해야 한다.
- 좌표와 크기는 원본 장면 단위를 유지한다. Sionna RT 전에 실제 미터 크기와 축 방향을 다시 검증해야 한다.

## 테스트

Open3D 없이도 핵심 계산과 OBJ 형식을 검사할 수 있다.

```bash
python -m pytest -q tools/proxy_mesh_editor/tests
```
