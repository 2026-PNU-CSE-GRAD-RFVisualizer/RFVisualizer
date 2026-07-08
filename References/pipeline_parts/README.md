# RFVisualizer 파이프라인 참고 문서 색인

이 폴더의 파일들은 `../3DGS_Sionna_RT_실시간_시각화_파이프라인_수정본.md`를 작업 주제별로 나눈 참조 문서다. 원문 전체를 한 번에 읽지 말고, 현재 작업에 필요한 파일만 골라 읽는다.

## 파일 구성

| 파일 | 읽어야 하는 상황 |
|---|---|
| `00_overview.md` | 프로젝트 목적, 전체 흐름, 최소 구현 범위를 처음 파악할 때 |
| `01_offline_build.md` | 촬영, 카메라 자세 추정, PGSR 학습, 전파 계산용 Mesh, Sionna RT, Radio Map 저장을 다룰 때 |
| `02_realtime_control.md` | 임베디드 장치 역할, 방향과 위치 갱신, 제어 데이터 전송, PC 초기화를 다룰 때 |
| `03_viewer_rendering.md` | SIBR Viewer 확장, 가우시안 렌더링, OpenGL 히트맵 합성, 가림 처리를 다룰 때 |
| `04_streaming_threads.md` | JPEG 인코딩, 영상 전송, 임베디드 화면 출력, 실시간 Viewer 내부 Thread 구조를 다룰 때 |
| `05_runtime_components.md` | 전체 실행 반복 구조, PC/임베디드/네트워크 구성 요소를 빠르게 확인할 때 |
| `06_implementation_scope.md` | 구현 순서, 기술 검증 순서, 최소 구현 범위, 기존 기획 대비 변경점을 확인할 때 |
| `07_open_questions.md` | 아직 확정하지 않은 설계, 실험으로 결정해야 할 항목, 성능 측정 지표를 다룰 때 |
| `08_architecture_summary.md` | 현재 확정된 구조와 핵심 결론만 빠르게 확인할 때 |

## 관리 원칙

- 원문을 수정하면 관련 분할 파일도 함께 갱신한다.
- 새 구현 결정이 생기면 `07_open_questions.md`의 미확정 항목을 줄이고, 확정 내용은 관련 주제 파일과 `08_architecture_summary.md`에 반영한다.
- 파일을 더 나눌 때는 코드 모듈 이름이 아니라 작업자가 읽는 목적을 기준으로 나눈다.
