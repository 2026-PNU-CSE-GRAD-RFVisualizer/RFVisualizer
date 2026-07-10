# PNU 강의실 Phase 1.5-B 검증 결과

검증일: 2026-07-11  
실행 환경: `pgsr` Conda 환경, Open3D 0.19.0

## 1. 구현 요약

일반 후보 JSON의 바닥·천장과 벽 후보 JSON의 순서 있는 벽을 입력으로 받아 닫힌 방 껍질을 생성했다. 후보 사각형은 범위 결정에 사용하지 않고, 인접 벽 두 개와 바닥 또는 천장의 무한 평면 교점으로 공통 모서리를 계산했다.

## 2. 변경 구성

- `envelope/config.py`: 별도 선택·검증 설정
- `envelope/candidate_loader.py`: 두 후보 문서 로드와 ID·방향·법선 검증
- `envelope/intersections.py`: 평면 정규화와 세 평면 교점 진단
- `envelope/polygon.py`: 자기 교차 검사와 오목 다각형 ear clipping
- `envelope/builder.py`: 공유 꼭짓점 메시와 바깥쪽 감김 생성
- `envelope/validator.py`: 기하·위상·부피 검사
- `envelope/exporter.py`: 통합·개별 OBJ, MTL, PLY 출력

## 3. 입력 설정

실제 선택은 `configs/pnu_classroom_envelope.yaml`에 추출 설정과 분리해 저장했다.

| 용도 | 후보 |
|---|---|
| 바닥 | `plane_006` |
| 천장 | `plane_005` |
| 입력 벽 순서 | `wall_008 → wall_000 → wall_001 → wall_006` |
| 내부 정규화 순서 | `wall_006 → wall_001 → wall_000 → wall_008` |

높이축 정렬 평면도에 후보 ID와 사각형을 겹쳐 외곽 네 방향을 직접 확인했다. 같은 방향의 평행 후보는 자동으로 합치거나 선택하지 않았다.

## 4. 교차 계산

각 꼭짓점은 `이전 벽 + 현재 벽 + 바닥/천장`의 3×3 선형식을 풀어 계산한다. 모든 평면식은 단위 법선으로 정규화하며 determinant, condition number, 선택 평면 residual을 JSON에 기록한다.

실제 최대 평면 residual은 `8.88e-16`으로 허용값 `1e-6` 이하다.

## 5. Polygon 처리

바닥 꼭짓점을 바닥 평면의 결정적 2차원 축으로 투영하고 입력 순서가 시계 방향이면 벽과 교점을 함께 반전한다. 바닥과 천장의 자기 교차를 각각 검사하고, NumPy 기반 ear clipping으로 볼록·오목 단순 다각형을 삼각분할한다.

실제 강의실 다각형은 자기 교차가 없으며 네 모서리가 외곽 후보점 범위에 놓였다.

## 6. Topology 생성

벽이 `N`개일 때 아래 꼭짓점 `N`개와 위 꼭짓점 `N`개만 만든다. 바닥·천장·벽은 통합 OBJ에서 같은 전역 꼭짓점을 공유한다. 각 삼각형은 내부점을 향하는지 검사하고 필요하면 감김을 뒤집는다.

실제 결과는 꼭짓점 8개와 삼각형 12개다.

## 7. 검증 결과

| 항목 | 결과 |
|---|---:|
| 꼭짓점 | 8 |
| 삼각형 | 12 |
| 모서리 | 18 |
| 경계 모서리 | 0 |
| 비다양체 모서리 | 0 |
| 퇴화 삼각형 | 0 |
| 중복 면 / 중복 꼭짓점 | 0 / 0 |
| 연결 요소 | 1 |
| Euler characteristic | 2 |
| 안쪽을 향한 면 | 0 |
| 표면적 | 185.304 장면 단위² |
| 부피 | 100.638 장면 단위³ |

방 높이는 최소 1.348, 평균 1.481, 최대 1.606 장면 단위다. 바닥·천장 평면의 기울기 차이는 2.018도다.

## 8. 실제 강의실 결과

위·옆 투영에서 바닥, 천장, 네 벽이 모두 존재하고 각 모서리가 공유됐다. 비정상적으로 먼 교점은 없었다. 생성 벽의 후보 사각형 대비 투영 범위 포함 비율은 약 73~92%이며, 후보 사각형 자체는 생성 벽에 약 71~100% 포함됐다.

현재 결과는 선택한 네 무한 평면으로 만든 닫힌 껍질이다. 실제 미터 크기나 문 구멍이 반영된 최종 전파 장면은 아니다.

## 9. 실행 명령

```bash
conda run -n pgsr python -m tools.proxy_mesh_editor.main build-envelope \
  --plane-candidates outputs/proxy_mesh/pnu_classroom/phase1/plane_candidates.json \
  --wall-candidates outputs/proxy_mesh/pnu_classroom/wall_extraction/wall_candidates.json \
  --envelope-config tools/proxy_mesh_editor/configs/pnu_classroom_envelope.yaml \
  --output outputs/proxy_mesh/pnu_classroom/room_envelope
```

## 10. 테스트 결과

- 전체 테스트: 36개 통과
- 직사각형 방: 꼭짓점 8개, 부피 96, 닫힌 manifold
- 임의 3차원 회전: 부피와 위상 유지
- 오각형·L자 오목 방: 정상 삼각분할과 닫힌 껍질
- 벽 2개, 중복 ID, 존재하지 않는 ID, NaN 평면, 인접 평행 벽, 기울어진 천장, 뒤집힌 높이, 자기 교차, singular 교점 오류 처리

## 11. 현재 한계

- 외곽 벽 선택과 순서는 사람이 지정해야 한다.
- 같은 방향의 중복·평행 후보를 자동 정리하지 않는다.
- 문·창문 구멍, 책상, 곡면, 실제 길이 보정을 지원하지 않는다.
- 후보 평면이 실제 구조와 다르면 위상은 닫혀도 실제 방과 어긋날 수 있다.

## 12. 다음 단계 인터페이스

`room_envelope.obj`는 공통 꼭짓점을 가진 닫힌 메시이며, `room_envelope.json`은 평면식, 공통 모서리, 높이, 선택 후보와 검증 수치를 제공한다. 이후 실제 크기 보정과 Sionna 장면 변환은 이 두 파일을 입력으로 사용할 수 있다.
