# Sionna RT Empty-Room Smoke Test

Phase 1.5-C에서 만든 미터 단위 Room Envelope를 Sionna RT 장면으로 바꾸고, 직접 경로·정반사 경로·저해상도 전파 지도를 실제 solver로 계산하는 Phase 2-A 도구다.

현재 결과는 사진 기반 임시 배율과 단일 concrete 재질을 사용한다. 실제 전파 세기와 정량 비교하는 단계가 아니다.

## 환경

현재 검증 환경:

```text
Python 3.10.20
Sionna RT 1.2.2
Mitsuba 3.8.0
Dr.Jit 1.3.1
TensorFlow 2.21.0
```

새 환경을 만들 경우:

```bash
conda create -n sionna python=3.10
conda activate sionna
python -m pip install -r tools/sionna_smoke_test/requirements-sionna.txt
```

Sionna RT 공식 문서의 [`load_scene`](https://nvlabs.github.io/sionna/rt/api/scene.html), [`PathSolver`](https://nvlabs.github.io/sionna/rt/api/paths_solvers.html), [`RadioMapSolver`](https://nvlabs.github.io/sionna/rt/api/radio_map_solvers.html) 구조를 사용한다.

## 명령

환경 진단:

```bash
conda run -n sionna python -m tools.sionna_smoke_test.main check-environment
```

입력 장면과 TX/RX 배치만 검증:

```bash
conda run -n sionna python -m tools.sionna_smoke_test.main validate-scene \
  --config configs/sionna/pnu_classroom_smoke_test.yaml
```

전체 실행:

```bash
conda run -n sionna python -m tools.sionna_smoke_test.main run \
  --config configs/sionna/pnu_classroom_smoke_test.yaml \
  --output outputs/sionna/pnu_classroom/smoke_test
```

## 처리 방식

1. `room_envelope_metric.obj/json`과 `calibration.json`을 읽는다.
2. OBJ의 `floor_000`, `ceiling_000`, `wall_*`를 객체별 ASCII PLY로 저장한다.
3. 공식 `itu-radio-material`의 `concrete` preset을 참조하는 Mitsuba `scene.xml`을 만든다.
4. 모든 평면의 안쪽 반공간과 바닥·천장 Z를 사용해 TX/RX를 검증한다. 단순 경계 상자 판정은 사용하지 않는다.
5. `PathSolver`로 LoS와 최대 2회 정반사를 계산한다.
6. `RadioMapSolver`로 높이 1.5m, 셀 1m의 path-gain 지도를 계산하고 방 밖 셀을 가린다.
7. `T_scene_from_metric`을 사용해 위치와 Coverage 점을 원본 PGSR 좌표로 되돌린다.

반사·Coverage 계산에는 refraction, diffraction, diffuse reflection을 사용하지 않는다.

## 테스트

Sionna가 필요 없는 테스트와 기존 Proxy Mesh 테스트:

```bash
conda run -n pgsr python -m pytest -q \
  tools/proxy_mesh_editor/tests tools/sionna_smoke_test/tests
```

전용 환경의 실제 solver 통합 테스트:

```bash
RUN_SIONNA_INTEGRATION=1 conda run -n sionna \
  python -m pytest -q tools/sionna_smoke_test/tests/test_sionna_integration.py
```

## 제한

- 배율과 결과는 `provisional`, `low confidence`, `physically_validated=false`다.
- concrete는 동작 확인용 공식 기본값이며 실제 벽체 측정값이 아니다.
- 문·창문·책상·의자·칠판·계단 세부 형상은 없다.
- 현재 TensorFlow는 cuDNN 문제로 GPU를 등록하지 못하지만 Sionna RT가 사용하는 Dr.Jit CUDA 뒷단은 활성화된다.
- 실패 시 성공 산출물을 흉내 내지 않고 `smoke_test_failure.json`에 원인을 기록한다.
