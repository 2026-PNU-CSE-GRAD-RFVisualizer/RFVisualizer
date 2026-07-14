# 11. 현재 확정된 아키텍처

| 구성 요소 | 현재 확정된 역할 |
|---|---|
| 고정 ESP32 노드 | 실제 AP RSSI 측정 및 MQTT 전송 |
| PGSR | Gaussian Scene, Surface Mesh, Unbiased Depth 후보 생성 |
| Proxy Mesh Editor | 일반·벽 평면 후보를 추출하고 선택 평면 교점으로 닫힌 Room Envelope 생성 |
| Proxy Placement Editor | Metric Room과 선택적 PGSR reference 위에서 기존 Phase 2-B obstacle schema의 proxy를 사람이 배치·검증·저장 |
| Blender 등 Mesh 도구 | Mesh 정리 및 주요 재질 그룹 수동 분리 |
| Sionna RT | Mesh 기반 단일 높이 Radio Map 사전 계산 |
| SIBR | Fork하여 확장할 3DGS 실시간 Viewer 기반 |
| SIBR Gaussian Renderer | Gaussian Scene Color 생성 |
| PGSR Mesh Renderer | Depth-only Pass의 1순위 Source |
| PGSR Unbiased Depth | Mesh Depth 비교 실험 후보 |
| OpenGL | Heatmap Plane, Depth Pass, Composite, UI |
| Dear ImGui | FPS, RSS, Orientation, Position Confidence, 지연시간 표시 |
| Render Thread | 장면 렌더링과 최신 Raw Frame 게시 |
| Encoder Thread | JPEG 인코딩과 최신 Encoded Frame 게시 |
| Network Thread | 최신 JPEG Frame TCP 전송 |
| Pose Receiver Thread | UDP Orientation/Control Packet 수신 |
| Frame Queue | 크기 1~2, 오래된 Frame Drop |
| 핸드헬드 ESP32-S3 | IMU/버튼 입력 및 JPEG 영상 표시 |
| 영상 Codec | JPEG Frame over TCP 우선 |
| 목표 화면 | RGB LCD 800×480 @ 10 FPS |
| GaussianRT-RF | 핵심 구현이 아닌 Future Work |

현재 Viewer의 핵심 원칙은 다음과 같다.

> **공식 SIBR Real-time Viewer를 1순위 구현 기반으로 Fork하고, 기존 Gaussian 렌더링 구조 위에 Heatmap, Mesh Depth, Pose, Streaming 기능을 추가한다.**

> **전파 계산용 PGSR Mesh는 Blender 등에서 주요 구조와 재질을 수동으로 정리하며, 완전 자동 Material Assignment를 목표로 하지 않는다.**

> **히트맵 Occlusion은 PGSR Mesh Depth를 우선 사용하고, 필요할 경우 PGSR Unbiased Depth와 비교한다.**

> **Render, JPEG Encode, TCP Send, Pose Receive는 독립 Thread로 분리하고, 크기 1~2의 Bounded Queue에서 오래된 Frame을 폐기한다.**

> **MVP의 히트맵은 단일 높이의 2.5D Radio Map Plane이며, 다중 Slice와 Volume Rendering은 확장 항목이다.**

아직 확정하지 않은 항목:

- 고정 ESP32 기반 핸드헬드 위치추정 알고리즘
- 실제 RSSI와 Sionna RT의 결합 강도
- PGSR Unbiased Depth의 최종 사용 여부
- JPEG 품질·Encoder·Readback·Buffer 세부 구조
- IMU Yaw Drift 대응 방식
- 여러 높이의 Radio Map 확장 여부

# 12. 핵심 정리

Sionna RT는 실제 RSSI 측정 파이프라인을 대체하는 것이 아니라, 실제 공간의 기하 구조를 반영한 전파 분포를 계산하는 모듈로 사용한다.

PGSR은 실시간 화면용 Gaussian Scene과 전파 계산·가림 판정용 Surface Mesh를 함께 생성한다. 추출된 Mesh는 Blender 등에서 정리하고, 한 개의 고정 실내 공간에 필요한 주요 구조만 3~5개 재질 그룹으로 수동 분리한다. 자동 Material Segmentation은 최소 구현 범위에 포함하지 않는다.

Proxy Mesh Editor의 벽 추출은 일반 평면 추출 잔여점이 아니라 전처리 원본에서 독립적으로 실행한다. 점 법선 필터와 벽 평면 재검사로 후보를 만들되, 후보 사이의 병합·모서리 맞춤·방수 처리는 이 단계에서 수행하지 않는다.

Room Envelope Builder는 사람이 순서대로 선택한 바닥·천장·벽의 무한 평면 교점으로 공통 꼭짓점을 만들고 닫힌 단일 메시를 출력한다. 외곽 후보 자동 선택과 문 구멍은 후속 단계이며, 실제 크기 확정에는 현장 실측이 남아 있다.

실제 크기 보정은 Room Envelope 원본을 유지한 채 미터 단위 표준 좌표 사본과 양방향 4×4 변환 행렬을 만든다. 설정에 고정한 바닥점·바닥 모서리·장면 위쪽으로 오른손 좌표계를 구성하고 하나의 양수 배율만 적용한다. 현재 사진 기반 문 크기로 얻은 결과는 임시값이므로 현장 실측 뒤 보정 설정만 갱신해 다시 실행해야 한다.

Phase 2-A에서는 이 미터 단위 사본을 객체별 PLY와 Mitsuba XML로 변환하고 Sionna RT의 빈 방 연결 시험을 완료했다. ITU concrete 단일 근사 재질에서 LoS, 최대 2회 정반사, 높이 1.5m의 저해상도 path-gain 지도를 계산하고 Coverage 점을 원본 PGSR 좌표로 역변환한다. 이는 물리 정확도가 아니라 장면·좌표·solver 연결 성공을 의미한다.

Phase 2-B에서는 닫힌 Room Envelope를 그대로 둔 채 box·thin panel·외부 mesh를 독립 Proxy Obstacle Layer로 구성하고 객체별 Sionna ITU 재질을 지정한다. 실제 실행한 synthetic blocker A/B 시험은 같은 TX/RX·seed·coverage grid에서 직접 경로 차단과 유한한 Coverage 변화를 확인했으며, baseline 반복 오차와 A/B 변화를 분리해 기록한다. 실제 강의실 장애물은 실측 전까지 활성화하지 않으므로 이 단계의 결과는 계층과 비교 파이프라인 검증이다.

Phase 2-C에서는 Phase 2-B schema를 원본으로 사용하는 Open3D Proxy Placement Editor를 추가한다. Room Envelope와 calibration은 읽기 전용이며 모든 편집은 meter/+Z 좌표에서 수행한다. Candidate 기본값은 미측정 placeholder라 비활성 상태로 추가되고, 사람이 위치·크기·방향·confidence·measurement source를 확인한 뒤에만 활성화한다. Metric/PGSR transform과 왕복 오차, floor/ceiling/wall clearance, collision warning을 함께 저장한다.

실시간 Viewer는 공식 SIBR Real-time Viewer를 Fork하여 확장하는 방식을 우선 검증한다. 기존 Gaussian Renderer와 Camera 구조를 유지한 채 Heatmap Plane, PGSR Mesh Depth-only Pass, UDP Pose Receiver, Offscreen Framebuffer, JPEG Streaming 모듈을 추가한다.

히트맵 가림 판정은 PGSR Mesh Depth를 우선 사용한다. Gaussian Color와 Mesh 경계가 일치하지 않는 문제는 Occlusion Boundary Mismatch로 정의하고, Camera·Projection·Scale·Mesh 오류를 먼저 확인한다. 이후 필요할 경우 PGSR Unbiased Depth 비교와 작은 후처리 보정을 수행한다.

핸드헬드 ESP32-S3는 IMU Orientation과 버튼 입력을 PC에 전달하고, PC에서 렌더링된 JPEG Frame을 수신·디코딩하여 800×480 RGB LCD에 목표 10 FPS로 표시한다. Render, Encoder, Network, Pose Receiver는 독립 Thread로 동작하며, Frame Queue는 1~2개로 제한하고 오래된 Frame을 폐기해 지연 누적을 막는다.

Camera Position은 연속 추적하지 않고 버튼을 눌렀을 때만 갱신하며, 버튼 미입력 중에는 마지막 Position을 유지한다.

MVP의 RF 시각화는 사람이 장치를 드는 높이의 단일 Radio Map Plane이다. 이는 2.5D 표현이며, 여러 높이의 Slice와 Volume Rendering은 기본 파이프라인이 안정화된 뒤 확장한다.

GaussianRT-RF는 연구적으로 유망하지만 현재 프로젝트의 구현 기반으로 사용하지 않는다. 최종 발표에서 Mesh 전처리 없이 Gaussian 표현으로 시각 렌더링과 RF Ray Tracing을 통합하는 Future Work로 제시한다.

현재 가장 중요한 미확정 문제는 다음과 같다.

1. 기존 고정 ESP32를 활용한 핸드헬드 위치추정 방식
2. 실제 RSSI와 Sionna RT 결과의 결합 방식
3. IMU Yaw Drift와 재중심화 처리
4. PGSR Mesh Depth와 Unbiased Depth 비교 결과
5. ESP32-S3 JPEG 품질·Buffer·Readback 세부 구현
6. Tracking 좌표계와 Gaussian/Sionna 좌표계의 정렬
7. 여러 높이 Radio Map 및 Volume Rendering 확장 여부

이 문서는 구현과 실험 결과에 따라 계속 수정한다.
