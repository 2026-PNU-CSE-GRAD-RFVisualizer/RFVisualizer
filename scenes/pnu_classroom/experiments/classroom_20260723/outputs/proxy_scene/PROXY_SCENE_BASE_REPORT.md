# 실측 기준 Proxy Scene 기본 Envelope

## 한 줄 결론

강의실 가로 15.4m, 깊이 10.8m, 전체 바닥 높이차 약 0.75m를 +X/+Y/+Z 실험 좌표에 반영한 닫힌 기본 Envelope를 생성했다. 계단 경계·문 처리·책상·AP 배치가 남아 있어 최종 Sionna 실험 장면은 아니다.

## 현재 형상

- Bounds: X 0–15.400m, Y 0–10.800m
- 바닥: 단일 경사면 placeholder, 앞 0m → 뒤 0.750m
- 천장: 기존 PGSR Envelope의 앞/뒤 여유 높이를 평균해 만든 임시 평면
- 닫힌 manifold: True
- Triangle: 12

## PGSR 표시 정렬

- 방식: 문 시작점을 (0, 0, 0)에 고정한 Room corner 8개의 anchored affine 최소제곱 정렬
- 문 시작점 anchor 오차: 8.327e-16m
- 평균 corner 오차: 0.2227m
- 최대 corner 오차: 0.3726m
- 용도: 편집 화면의 참조 표시만 허용

## 남은 작업

1. 계단 경계와 단 높이 입력
2. 문 2.09m × 2.09m의 위치·재질 처리
3. 주요 책상 위치·크기·방향 입력
4. AP와 RX Marker 입력
5. Sionna Import와 2D Grid 검증
