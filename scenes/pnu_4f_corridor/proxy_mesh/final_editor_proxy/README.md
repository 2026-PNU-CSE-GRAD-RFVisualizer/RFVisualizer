# PNU 4F Corridor Proxy Mesh

도면 `IMG_2810.jpg`, 수정 표시 도면 `source/image-1.png`, PGSR Mesh를 함께 사용해 만든 Proxy Mesh Editor 입력이다. 사용자가 확정한 A 해석에 따라 색 선은 복도 외곽 경계로 취급했고, 도면은 형태만 참고했으며 수치 경계는 PGSR 수직면 밀도에서 보정했다.

## 바로 실행

프로젝트 루트에서 다음 명령을 실행한다.

```bash
./run_4f_corridor_proxy_editor.sh
```

첫 실행에서는 약 228만 삼각형인 PGSR Mesh를 편집기 표시용으로 단순화하므로 시간이 더 걸릴 수 있다. 원본 PGSR Mesh는 바뀌지 않는다.

## 좌표 계약

- 원점: 도면의 초록색 `(0,0)` 점
- 축: 도면 오른쪽 `+X`, 위쪽 `+Y`, 높이 `+Z`
- 단위: 미터
- 외피 범위: `X=0.00~11.80`, `Y=0.00~16.342`, `Z=0.00~2.614`
- TX/RX 초기 높이: 도면 표기값 `0.45 m`

초기 Marker는 `configs/rf_experiment/pnu_4f_corridor/tx_rx.json`에 있으며, TX 1개·보정 RX 4개·시험 RX 6개다. 편집기에서 이동 후 저장하면 같은 파일이 갱신된다.

## Mesh 기반 수정 경계

바닥 외곽선은 다음 8개 점을 순서대로 잇는다.

```text
(0.00, 0.00) -> (11.80, 0.00) -> (11.80, 16.342) -> (0.07, 16.342)
-> (0.07, 13.33) -> (3.29, 13.33) -> (3.29, 9.03) -> (0.00, 9.03)
```

- 붉은 뒤집힌 ㄷ자 구간: 바깥 왼쪽 `X=0.07 m`, 안쪽 아래 `Y=13.33 m`
- 파란 엘리베이터 연결 복도: 안쪽 왼쪽 `X=3.29 m`, 아래 복도 접속 `Y=9.03 m`
- PGSR 수직면 지지: `X=0.07` 796점, `X=3.29` 314점, `Y=9.03` 1,666점
- `Y=13.33`은 89점의 보조 피크라 다른 세 경계보다 신뢰도가 낮다.

Proxy Mesh를 같은 규칙으로 다시 만들려면 다음 명령을 실행한다.

```bash
conda run --no-capture-output -n pgsr \
  python -m tools.proxy_mesh_editor.rebuild_4f_corridor_proxy
```

## 검증 상태와 한계

- Room Envelope는 16개 꼭짓점, 28개 삼각형의 닫힌 manifold다.
- 기존 PGSR↔실측 변환을 정한 6개 기준점 오차는 최대 약 `0.044 m`다. 새 붉은/파란 경계 자체의 실측 오차를 뜻하지 않는다.
- 초기 Marker 11개는 모두 방 내부이며 벽과의 최소 여유가 `0.50 m`다.
- Sionna RT 연결 시험은 LoS 거리 오차 약 `1.50e-7 m`, 반사 경로 23개, 내부 Coverage 유효 비율 `98.2%`로 통과했다.
- 바닥은 도면 좌표에서 평평한 `Z=0`으로 만들었다.
- 도면에 전체 세로 길이가 적혀 있지 않아 `Y max`는 PGSR 외벽에서 추정했다.
- 붉은/파란 복도 외곽은 포함했지만 엘리베이터 문·계단·기둥 같은 내부 물체는 아직 Candidate로 배치하지 않았다.
- 특히 붉은 안쪽 `Y=13.33 m` 경계는 PGSR 지지가 약하므로 Editor에서 Mesh를 겹쳐 보고 현장 치수로 마지막 확인이 필요하다.
- 이 정렬은 도면과 PGSR에 기반한 잠정값이며 레이저 실측으로 검증된 결과가 아니다.

## 확인 결과

- Marker/PGSR 겹침: `outputs/proxy_placement/pnu_4f_corridor/preview/top_view.png`
- PGSR 벽 밀도 근거: `outputs/proxy_mesh/4f_corridor/diagnostics/revision2_vertical_wall_density.png`
- 배치 검사: `outputs/proxy_placement/pnu_4f_corridor/validation/placement_validation.json`
- Sionna 장면 미리보기: `outputs/sionna_scenario/pnu_4f_corridor/scenario_preview.png`
- Sionna 연결 시험: `outputs/sionna_smoke_test/pnu_4f_corridor/smoke_test_validation.json`
- 잠정 전파 지도: `outputs/sionna_smoke_test/pnu_4f_corridor/coverage/coverage_map.png`
