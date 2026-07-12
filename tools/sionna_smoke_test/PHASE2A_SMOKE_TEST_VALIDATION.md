# Phase 2-A Sionna RT Empty-Room Smoke Test 검증 결과

## 결론

미터 단위 강의실 외곽을 Sionna RT 장면으로 로드하고, LoS·최대 2회 정반사·저해상도 path-gain 지도를 실제 solver로 계산했다. 장면 변환, 위치 배치, 경로 거리, Coverage, 원본 PGSR 좌표 역변환 검증이 모두 통과했다.

결과는 `provisional`, `low confidence`, `physically_validated=false`다.

## 기준 저장소와 환경

- 기준 커밋: 로컬 `main`의 `190bc4683e58175c3501e16b7b7e558b3e202736`
- 원격 `main`: HTTPS 인증 정보가 없어 확인하지 못함
- Python: `3.10.20`
- Sionna RT: `1.2.2`
- Mitsuba: `3.8.0`
- Dr.Jit: `1.3.1`
- TensorFlow: `2.21.0`
- GPU: NVIDIA GeForce RTX 4090, 24,564 MiB
- Mitsuba variant: `cuda_ad_mono_polarized`
- Dr.Jit CUDA/LLVM: 모두 사용 가능
- TensorFlow GPU: cuDNN 라이브러리 문제로 등록되지 않음

전파 solver는 TensorFlow GPU가 아니라 활성화된 Dr.Jit CUDA 뒷단으로 실행됐다.

## 장면 변환

Metric OBJ의 객체와 그룹을 읽어 다음 6개 PLY를 생성했다.

```text
floor_000
ceiling_000
wall_000
wall_001
wall_002
wall_003
```

Mitsuba `scene.xml`은 각 PLY와 `itu-radio-material`을 연결한다. Sionna `load_scene(..., merge_shapes=False)`로 객체 6개와 재질 3개가 실제 등록되는 것을 확인했다.

- 삼각형: `12 → 12`
- Bounds: 일치
- 표면적: 일치
- 부호 있는 부피: 일치

## 재질

바닥·천장·벽에 설치된 Sionna의 공식 ITU concrete preset을 사용했다.

```text
relative permittivity: 5.23999977
conductivity at 2.4 GHz: 0.09163117 S/m
thickness: 0.1 m
scattering coefficient: 0
```

실제 강의실 재질 측정값이 아니라 연결 시험용 근사값이다.

## TX/RX 배치

설정 좌표 세 개가 모두 유효해 대체 위치는 사용하지 않았다.

| 장치 | Metric 좌표 (m) | 원본 PGSR 좌표 | 바닥/천장/벽 최소 여유 (m) |
|---|---|---|---|
| tx_test | `[-7,-5,1.5]` | `[0.1610,0.0347,0.1934]` | `1.266 / 1.009 / 4.719` |
| rx_los | `[-3,-5,1.5]` | `[-1.6560,-0.2999,2.0103]` | `1.314 / 0.959 / 3.127` |
| rx_reflection | `[-10,-8,1.5]` | `[2.8969,0.2970,0.2060]` | `1.141 / 1.243 / 2.854` |

내부 판정은 단순 경계 상자가 아니라 Room Envelope의 바닥·천장·벽 평면을 안쪽으로 정렬한 반공간 거리로 수행했다.

## LoS와 Reflection

LoS:

```text
path count: 1
Euclidean distance: 4.0 m
Sionna distance: 3.999999907 m
distance error: 9.2764e-8 m
```

Reflection:

```text
total path count: 26
specular reflection path count: 25
maximum interaction count: 2
all numeric values finite: true
```

Refraction, diffraction, diffuse reflection은 비활성화했다.

## Coverage

- 높이: `1.5 m`
- 셀 크기: `1.0 × 1.0 m`
- 격자: `11 × 15`, 총 165셀
- 방 내부 셀: 151
- 유효 내부 셀: 151
- 내부 유효 비율: `100%`
- NaN/Inf: `0 / 0`
- Path gain: `-61.064 / -58.664 / -20.772 dB` (최솟값/평균/최댓값)

방 밖 14셀은 출력 그림과 배열에서 가려진다.

## 좌표 변환과 성능

- Metric → scene → metric 최대 오차: `1.9860e-15`
- Scene → metric → scene 최대 오차: `1.9862e-15`

실행 시간:

| 단계 | 시간 |
|---|---:|
| 환경 진단 | 1.4054 s |
| 장면 변환 | 0.0018 s |
| Sionna 장면 로드 | 0.1650 s |
| LoS | 0.0718 s |
| Reflection | 0.0934 s |
| Coverage | 0.0044 s |
| 보고서 전 전체 | 2.0282 s |

## 테스트

```text
88 passed, 1 skipped
```

기본 테스트 환경에서는 Sionna가 필요한 통합 시험 한 개를 명시적으로 건너뛴다. 전용 Sionna 환경에서 `RUN_SIONNA_INTEGRATION=1`로 실행한 결과는 다음과 같다.

```text
1 passed
```

## 생성 파일과 한계

실제 결과는 `outputs/sionna/pnu_classroom/smoke_test/`에 있다. 장면 XML/PLY, 위치, 경로 JSON/CSV, Coverage NPY/CSV/PNG, 검증 JSON, 실행 보고서를 모두 생성했다.

이번 결과는 기하·좌표·API 연결 시험이다. 실제 RSSI 정확도, 문과 가구, 재질 추정, 고해상도 지도, Viewer 연결은 검증하지 않았다. Phase 2-B에서는 큰 차폐 구조부터 추가하고 재질을 벽·바닥·금속·목재 수준으로 나누어야 한다.
