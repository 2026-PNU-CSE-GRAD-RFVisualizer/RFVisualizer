# RFVisualizer

사진·영상에서 PGSR 장면과 Mesh를 만들고, 전파 계산용 Proxy Scene을 제작한 뒤, Sionna RT와 실측 RSSI를 비교하는 저장소다.

> 모든 모듈 명령은 저장소 루트에서 실행한다. 이 저장소에는 루트 `setup.py`/`pyproject.toml`이 없으므로 `pip install -e .` 대신 Conda 환경에서 `python -m ...`으로 실행한다.

## 설치 방법

실행 환경은 역할별로 나뉜다.

| 환경 | 용도 | 저장소 기준 의존성 |
|---|---|---|
| `pgsr` | PGSR 학습·렌더링, Proxy Mesh/Placement Editor, 기본 테스트 | `PGSR/requirements.txt`, `tools/proxy_mesh_editor/requirements-test.txt` |
| `sionna` | Sionna RT RSSI 계산과 실제 solver integration test | `tools/sionna_smoke_test/requirements-sionna.txt` |

먼저 루트로 이동한다.

```bash
cd /path/to/RFVisualizer
```

이미 환경이 있다면 다음처럼 저장소 의존성을 맞춘다.

```bash
conda run -n pgsr python -m pip install -r tools/proxy_mesh_editor/requirements-test.txt
conda run -n sionna python -m pip install -r tools/sionna_smoke_test/requirements-sionna.txt
```

새 환경은 PGSR의 CUDA·PyTorch 조합을 먼저 설치한 뒤 저장소 의존성을 설치한다. CUDA에 맞는 PyTorch 설치 명령은 [PGSR 설치 문서](PGSR/README.md#installation)의 명령을 따른다.

```bash
conda create -n pgsr python=3.8 -y
conda run -n pgsr python -m pip install -r PGSR/requirements.txt
conda run -n pgsr python -m pip install PGSR/submodules/diff-plane-rasterization PGSR/submodules/simple-knn
conda run -n pgsr python -m pip install -r tools/proxy_mesh_editor/requirements-test.txt

conda create -n sionna python=3.10 -y
conda run -n sionna python -m pip install -r tools/sionna_smoke_test/requirements-sionna.txt
```

Proxy Placement Editor의 GUI 창이 Wayland/XWayland에서 열리지 않으면 다음 명령으로 전용 Open3D 0.18 CPU runtime을 준비한다.

```bash
conda run -n pgsr python -m tools.proxy_placement_editor.main setup-gui-runtime
```

## 주요 디렉터리

| 경로 | 역할 |
|---|---|
| `PGSR/` | 사진 입력으로 Gaussian 장면과 Surface Mesh를 생성하는 PGSR 코드 |
| `colmap/` | COLMAP 소스와 빌드 영역 |
| `tools/proxy_mesh_editor/` | PGSR Mesh의 평면·벽 후보, Room Envelope, Metric Calibration 생성 |
| `tools/proxy_placement_editor/` | 문·계단·책상·장애물·AP/TX·RX를 배치하는 통합 Open3D Editor |
| `tools/rf_experiment/` | Scene/TX/RX/CSV 계약 검증, Sionna 실행, 세 방법 비교 분석 |
| `tools/sionna_scenario/` | Sionna Scene·Obstacle schema와 Phase 2-B 실행 도구 |
| `tools/sionna_smoke_test/` | Empty Room과 Sionna Path/Coverage smoke test |
| `scenes/<scene_id>/` | 씬 하나의 설정과 산출물을 전부 모은 폴더. `configs/`(도구별 입력)와 각 도구의 출력(`proxy_mesh/`, `proxy_placement/`, `sionna/`, `rf_experiment/`)을 함께 담는다. `scene.yaml`이 그 씬에서 각 도구를 실행할 때 쓰는 경로를 선언한다 |
| `scenes/<room_id>/experiments/<session_id>/` | 같은 방을 재사용하는 날짜별 현장 측정 세션. 자체 `scene.yaml`, `configs/`, `outputs/`를 가진다 |
| `scripts/run_scene.py` | `scenes/**/scene.yaml`을 읽어 `tools.<package>.main`을 실행하는 공용 런처. 씬별 wrapper 스크립트를 대신한다 |
| `TUTORIAL.md` | 촬영부터 PGSR, Proxy, 실측, 분석까지의 전체 순서 |

원본 사진·영상은 `PGSR/data/` 또는 별도 백업에 두고, 생성 결과는 `scenes/<scene_id>/` 아래에 저장한다. 기존 결과를 덮어쓰지 않으려면 새 씬 id나 새 출력 폴더를 사용한다.

씬마다 반복되는 긴 명령은 `scripts/run_scene.py <scene_id> <package> <subcommand>`로 대신 실행한다. `scene.yaml`에 없는 값이나 일회성 값은 그 뒤에 그대로 이어 붙이면 덮어쓴다.

```bash
conda run -n pgsr python scripts/run_scene.py <scene_id> proxy_placement_editor edit
conda run -n pgsr python scripts/run_scene.py <scene_id> proxy_placement_editor edit --software-rendering
conda run -n pgsr python scripts/run_scene.py <session_id> rf_experiment validate-contracts
```

## Proxy Editor 실행

이 저장소의 이름이 비슷한 두 도구를 구분한다.

1. `proxy_mesh_editor`: PGSR Mesh에서 평면 후보를 고르고 Room Envelope를 만든다.
2. `proxy_placement_editor`: 완성된 Metric Room을 보면서 장애물과 TX/RX를 배치한다. 일반적으로 사용자가 말하는 Proxy Editor는 이 통합 Editor다.

### Room Envelope 선택

후보를 GUI에서 선택하려면 display가 있는 환경에서 실행한다.

```bash
conda run -n pgsr python -m tools.proxy_mesh_editor.main pick-envelope \
  --plane-candidates scenes/<scene_id>/proxy_mesh/phase1/plane_candidates.json \
  --wall-candidates scenes/<scene_id>/proxy_mesh/wall_extraction/wall_candidates.json \
  --envelope-config scenes/<scene_id>/configs/proxy_mesh/envelope.yaml \
  --output scenes/<scene_id>/proxy_mesh/room_envelope_picked
```

headless 환경에서는 후보 선택 GUI 대신 설정이 완성된 `build-envelope`를 사용한다. 자세한 입력·출력 계약은 [Proxy Mesh Editor 문서](tools/proxy_mesh_editor/README.md)를 따른다.

### 통합 Proxy Placement Editor

씬별 입력·출력 경로는 `scenes/<scene_id>/scene.yaml`에 선언되어 있으므로 `scripts/run_scene.py`로 바로 연다.

```bash
conda run -n pgsr python scripts/run_scene.py <scene_id> proxy_placement_editor edit
```

날짜별 현장 측정 세션을 열 때는 세션의 `scene.yaml`에 선언된 세션 ID를 쓴다.

```bash
conda run -n pgsr python scripts/run_scene.py <session_id> proxy_placement_editor edit
```

GUI에 문제가 있으면 뒤에 Mesa 소프트웨어 렌더링 플래그를 이어 붙인다.

```bash
conda run -n pgsr python scripts/run_scene.py <scene_id> proxy_placement_editor edit --software-rendering
```

GUI 없이 Scenario만 검사하거나 미리보기를 만들 때는 `edit` 대신 `validate`를 사용한다.

```bash
conda run -n pgsr python scripts/run_scene.py <session_id> proxy_placement_editor validate
```

GUI 사용법과 저장 산출물은 [Proxy Placement Editor 문서](tools/proxy_placement_editor/README.md)에 있다.

## RF Experiment 실행

RF Experiment는 `validate-contracts` → Proxy Scene/TX/RX 준비 → `run-sionna` → `analyze` 순서다. 현재 예시 설정의 Scene과 Marker는 `draft` 상태이므로, `--require-ready` 없는 계약 검증은 경고와 함께 `ready: false`를 보고할 수 있다.

아래 명령은 모두 `scripts/run_scene.py <scene_id> rf_experiment <subcommand>` 형태로 줄여 쓸 수 있다. `scene.yaml`에 없는 값만 추가로 붙인다.

### 1. 계약 검증

```bash
conda run -n pgsr python scripts/run_scene.py <session_id> rf_experiment validate-contracts
```

현장 실행 전에 실제 Proxy Scene과 TX/RX를 확정한 뒤에는 `--require-ready`를 이어 붙인다.

```bash
conda run -n pgsr python scripts/run_scene.py <session_id> rf_experiment validate-contracts --require-ready
```

### 2. 실측 치수 기반 Proxy Envelope 생성

```bash
conda run -n pgsr python scripts/run_scene.py <session_id> rf_experiment build-proxy-envelope
```

이 명령은 기존 PGSR 기반 결과를 덮어쓰지 않고 새 OBJ/JSON/Calibration을 만든다. 생성된 `room_envelope_metric.obj`와 `calibration.json`을 Proxy Placement Editor에 입력한다.

### 3. Sionna RSSI 계산

실제 Scene과 Marker가 모두 `ready`인 경우:

```bash
conda run -n sionna python scripts/run_scene.py <session_id> rf_experiment run-sionna
```

연결만 확인할 때는 합성 Marker와 `--allow-draft`를 이어 붙인다. `--markers`를 다시 지정하면 `scene.yaml`의 값을 덮어쓴다. 이 결과는 논문용 실측 근거가 아니다.

```bash
conda run -n sionna python scripts/run_scene.py <session_id> rf_experiment run-sionna \
  --markers scenes/<scene_id>/experiments/<session_id>/configs/dry_run/tx_rx_synthetic.json \
  --output scenes/<scene_id>/experiments/<session_id>/outputs/sionna_dry_run \
  --allow-draft
```

### 4. 실측값과 예측값 비교

Backend Summary CSV와 Sionna의 지점·격자 CSV가 준비된 뒤 실행한다.

```bash
conda run -n pgsr python scripts/run_scene.py <session_id> rf_experiment analyze \
  --summary <measurements_summary.csv> \
  --sionna-points <sionna_points.csv> \
  --sionna-grid <sionna_grid.csv>
```

`<...>`는 실제 입력 파일 경로로 바꾼다. `calibration` 행은 보정에만, `test` 행은 MAE·RMSE 평가에만 사용한다. 상세 계약은 [RF Experiment 문서](tools/rf_experiment/README.md)를 따른다.

## 테스트 방법

테스트는 패키지별로 범위를 지정해 실행한다. 먼저 Sionna solver가 필요 없는 핵심 회귀를 실행한다.

```bash
conda run -n pgsr python -m pytest -q --import-mode=importlib \
  tools/proxy_mesh_editor/tests \
  tools/sionna_smoke_test/tests
```

Proxy Placement Editor와 Sionna Scenario 회귀는 각각 실행한다.

```bash
conda run -n pgsr python -m pytest -q --import-mode=importlib \
  tools/proxy_placement_editor/tests

conda run -n pgsr python -m pytest -q --import-mode=importlib \
  tools/sionna_scenario/tests
```

RF Experiment 전체 테스트에는 Python 3.10 이상과 `pydantic`이 필요하다.

```bash
python -m pytest -q --import-mode=importlib tools/rf_experiment/tests
```

실제 Sionna integration test는 명시적으로 켠다.

```bash
RUN_SIONNA_PHASE2B_INTEGRATION=1 conda run -n sionna \
  python -m pytest -q --import-mode=importlib \
  tools/sionna_scenario/tests

RUN_SIONNA_INTEGRATION=1 conda run -n sionna \
  python -m pytest -q --import-mode=importlib \
  tools/sionna_smoke_test/tests/test_sionna_integration.py
```

저장소 루트에서 범위 없는 `pytest`는 사용하지 않는다. vendored COLMAP의 선택 의존성과 여러 테스트 디렉터리의 동명 모듈 충돌을 피하려면 위처럼 테스트 경로와 `--import-mode=importlib`를 함께 지정한다.

## 더 자세한 문서

- [전체 튜토리얼](TUTORIAL.md)
- [Proxy Mesh Editor](tools/proxy_mesh_editor/README.md)
- [Proxy Placement Editor](tools/proxy_placement_editor/README.md)
- [RF Experiment](tools/rf_experiment/README.md)
- [Sionna Scenario](tools/sionna_scenario/README.md)
- [Sionna Smoke Test](tools/sionna_smoke_test/README.md)
