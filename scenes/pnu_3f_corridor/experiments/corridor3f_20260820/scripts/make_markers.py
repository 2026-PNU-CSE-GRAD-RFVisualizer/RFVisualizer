#!/usr/bin/env python3
"""TX/RX 좌표표 -> tx_rx.json + 현장 배치용 좌표 도면.

좌표의 출처는 두 가지다.
  1. 최초 위치: 계획 도면 `references/floorplan_tx_calib_test_loop.png`의 표식 픽셀을
     도면-Metric 정합식(1 px = 0.03975 m)으로 옮긴 값. 근거는 ../README.md 4절.
  2. 이후 조정: 보정점의 LOS/NLOS 구성과 Test 점과의 최소 거리를 맞추려고 손으로 옮긴 값.
아래 MARKERS가 지금의 유일한 기준이다. 도면 PNG가 아니라 이 표를 고친다.

실행하면 Proxy Mesh 통행 가능 영역으로 다음을 검사하고, 하나라도 어기면 종료한다.
  - 모든 점이 실내이고 벽에서 MIN_CLEARANCE_M 이상 떨어져 있다
  - 보정점과 Test 점이 MIN_CAL_TEST_M 이상 떨어져 있다 (held-out 독립성)
  - 보정 집합이 LOS와 NLOS를 모두 포함한다 (Test 집합과 조건이 갈리지 않게)

    python scenes/pnu_3f_corridor/experiments/corridor3f_20260820/scripts/make_markers.py
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
from matplotlib.path import Path as Polygon

SCENE = Path(__file__).resolve().parents[3]          # scenes/pnu_3f_corridor
SESSION = Path(__file__).resolve().parents[1]
PLAN = SCENE / "references/floorplan_clean.png"
GRID = SCENE / "references/floorplan_tx_calib_test_grid.png"
ENVELOPE = SCENE / "proxy_mesh/complex_envelope/room_envelope_metric.json"

M_PER_PX, X0, Y0 = 0.03975, 56.6115, -6.4145         # 도면 px -> metric
RX_Z, TX_Z = 0.45, 0.80
SCENE_ID, CS_ID = "corridor3f_20260820", "pnu_3f_corridor_metric_v1"
MIN_CLEARANCE_M, MIN_CAL_TEST_M = 0.5, 3.0
CELL_M = 0.05                                        # 검사용 점유 격자 크기

# 실제 장치 배치. 보정점은 고정 노드가 하나씩 맡고, Test 점 10개는 이동 노드
# node-02 하나가 옮겨 다니며 측정한다. Backend Export의 node_id와 맞춰야 한다.
ROVING_TEST_NODE = "node-02"
NODE_IDS = {
    "TX": "ap-01",
    "C1": "node-01",
    "C2": "node-03",
    "C3": "node-04",
    "C4": "gw-01",
}

# TX: ipTIME N602SR, 펌웨어가 고정한 채널 6
TX_FREQUENCY_HZ = 2.437e9
TX_EIRP_DBM = 20.0

MARKERS = {
    "TX": (21.37, 17.83, "고정 AP / TX"),
    # 보정 RX: 넓은 복도 양끝 2개(LOS) + 좁은 복도 2개(NLOS).
    "C1": (34.90, 18.70, "보정 RX 1 node-01 (넓은 복도 왼쪽, LOS)"),
    "C2": (24.02, 6.31, "보정 RX 2 node-03 (좁은 복도 중앙, 그림자)"),
    "C3": (16.07, 6.31, "보정 RX 3 node-04 (좁은 복도, 코어 통로 부근)"),
    "C4": (5.86, 18.56, "보정 RX 4 gw-01 (넓은 복도 오른쪽, LOS)"),
    # Test RX: 넓은 복도 4개(LOS) + 좁은 복도·짧은 복도 6개(NLOS).
    "T1": (12.57, 17.83, "Test RX 1"),
    "T2": (1.80, 17.80, "Test RX 2"),
    "T3": (1.76, 6.90, "Test RX 3"),
    "T4": (5.17, 5.31, "Test RX 4"),
    "T5": (10.90, 5.31, "Test RX 5"),
    "T6": (20.04, 5.31, "Test RX 6"),
    "T7": (31.57, 5.31, "Test RX 7"),
    "T8": (37.93, 6.90, "Test RX 8"),
    "T9": (37.93, 16.88, "Test RX 9"),
    "T10": (30.10, 17.83, "Test RX 10"),
}


def walkable_grid():
    """Room Envelope 바닥 다각형을 점유 격자로 만든다. 구멍(코어)은 제외된다."""
    document = json.loads(ENVELOPE.read_text(encoding="utf-8"))
    polygon = np.array(document["bottom_corners"])[:, :2]
    maximum = polygon.max(axis=0)
    nx, ny = int(maximum[0] / CELL_M) + 1, int(maximum[1] / CELL_M) + 1
    xs = (np.arange(nx) + 0.5) * CELL_M
    ys = (np.arange(ny) + 0.5) * CELL_M
    grid_x, grid_y = np.meshgrid(xs, ys)
    inside = Polygon(polygon).contains_points(
        np.column_stack([grid_x.ravel(), grid_y.ravel()]))
    return inside.reshape(ny, nx)


def clearance_map(walkable):
    from scipy import ndimage
    return ndimage.distance_transform_edt(walkable) * CELL_M


def sight_line(walkable, start, end):
    steps = int(np.linalg.norm(end - start) / (CELL_M * 0.5)) + 1
    for ratio in np.linspace(0.0, 1.0, steps):
        point = start + (end - start) * ratio
        ix, iy = int(point[0] / CELL_M), int(point[1] / CELL_M)
        if not (0 <= ix < walkable.shape[1] and 0 <= iy < walkable.shape[0]):
            return False
        if not walkable[iy, ix]:
            return False
    return True


def audit():
    walkable = walkable_grid()
    clearance = clearance_map(walkable)
    transmitter = np.array(MARKERS["TX"][:2])
    report, problems = {}, []
    for key, (x, y, _) in MARKERS.items():
        point = np.array([x, y])
        ix, iy = int(x / CELL_M), int(y / CELL_M)
        inside = (0 <= ix < walkable.shape[1] and 0 <= iy < walkable.shape[0]
                  and walkable[iy, ix])
        if not inside:
            problems.append("{}가 통행 가능 영역 밖입니다: {}".format(key, (x, y)))
            report[key] = {"clearance": 0.0, "distance": 0.0, "los": False}
            continue
        margin = float(clearance[iy, ix])
        if margin < MIN_CLEARANCE_M:
            problems.append("{}가 벽에서 {:.2f} m 뿐입니다 (최소 {}).".format(
                key, margin, MIN_CLEARANCE_M))
        report[key] = {
            "clearance": margin,
            "distance": float(np.linalg.norm(point - transmitter)),
            "los": sight_line(walkable, transmitter, point),
        }
    for cal in [k for k in MARKERS if k.startswith("C")]:
        for test in [k for k in MARKERS if k.startswith("T") and k != "TX"]:
            gap = float(np.linalg.norm(
                np.array(MARKERS[cal][:2]) - np.array(MARKERS[test][:2])))
            if gap < MIN_CAL_TEST_M:
                problems.append("{}와 {}가 {:.2f} m 뿐입니다 (최소 {}). "
                                "held-out 평가가 깨집니다.".format(
                                    cal, test, gap, MIN_CAL_TEST_M))
    calibration_los = {report[k]["los"] for k in MARKERS if k.startswith("C")}
    if calibration_los != {True, False}:
        problems.append("보정점이 한 조건에만 몰려 있습니다(LOS={}). "
                        "Test 집합이 두 조건을 모두 가지므로 보정도 그래야 합니다.".format(
                            calibration_los))
    return report, problems


def write_markers(report):
    x, y, name = MARKERS["TX"]
    document = {
        "schema_version": "1.0",
        "scene_id": SCENE_ID,
        "coordinate_system_id": CS_ID,
        # 좌표 배치를 최종 확정했으므로 ready. 현장 실측 여부와는 별개이며,
        # 배율/좌표의 provisional 성격은 scene.json의 dimension_sources에 남아 있다.
        "status": "ready",
        "requirements": {
            "transmitter_count": 1,
            "calibration_receiver_count": 4,
            "test_receiver_count": 10,
        },
        "tx": [{
            "id": "ap_tx_000",
            "name": name,
            "position_m": [x, y, TX_Z],
            "node_id": NODE_IDS["TX"],
            # ipTIME N602SR (2.4GHz 전용, 802.11b/g/n, 2x2 MIMO, 5dBi 외장 안테나 2개).
            # 주파수는 펌웨어가 고정한 채널 6(2437MHz)이다. 2400MHz 와의 FSPL 차이는 0.13dB.
            "frequency_hz": TX_FREQUENCY_HZ,
            # 등가 등방 복사 전력(EIRP) 기준값. 제조사가 출력을 공개하지 않아
            # 국내 2.4GHz 상한(10mW/MHz -> 20MHz 채널 200mW = 23dBm)보다 3dB 낮게 잡았다.
            # 현장에서 LOS 기준점 1개를 재면 확정된다: EIRP = 측정RSSI + FSPL(거리).
            "power_dbm": TX_EIRP_DBM,
        }],
        "rx": [],
    }
    for index, key in enumerate(["C1", "C2", "C3", "C4"]):
        x, y, name = MARKERS[key]
        document["rx"].append({
            "id": "cal_rx_%03d" % index,
            "point_id": "cal-%02d" % (index + 1),
            "name": name,
            "role": "calibration",
            "position_m": [x, y, RX_Z],
            "plan_label": key,
            "node_id": NODE_IDS[key],
            "wall_clearance_m": round(report[key]["clearance"], 2),
            "tx_line_of_sight": report[key]["los"],
        })
    for index in range(1, 11):
        key = "T%d" % index
        x, y, name = MARKERS[key]
        document["rx"].append({
            "id": "test_rx_%03d" % (index - 1),
            "point_id": "test-%02d" % index,
            "name": name,
            "role": "test",
            "position_m": [x, y, RX_Z],
            "plan_label": key,
            "node_id": ROVING_TEST_NODE,
            "wall_clearance_m": round(report[key]["clearance"], 2),
            "tx_line_of_sight": report[key]["los"],
        })
    target = SESSION / "configs/tx_rx.json"
    target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    return target


def draw(report):
    image = np.array(Image.open(PLAN).convert("RGB"))
    height, width, _ = image.shape
    to_px = lambda X, Y: ((X0 - X) / M_PER_PX, (Y - Y0) / M_PER_PX)
    figure, axis = plt.subplots(figsize=(width / 100, height / 100), dpi=150)
    axis.imshow(image)
    axis.set_xlim(0, width)
    axis.set_ylim(height, 0)
    axis.axis("off")
    for X in np.arange(0, 46, 5):
        cx, _ = to_px(X, 0)
        if 0 <= cx <= width:
            axis.axvline(cx, color="#1f77b4", lw=.6, alpha=.35)
            axis.text(cx, 735, "X=%.0f" % X, color="#1f77b4", fontsize=7, ha="center")
    for Y in np.arange(0, 22, 5):
        _, cy = to_px(0, Y)
        if 0 <= cy <= 730:
            axis.axhline(cy, color="#1f77b4", lw=.6, alpha=.35)
            axis.text(34, cy - 4, "Y=%.0f" % Y, color="#1f77b4", fontsize=7, ha="center",
                      bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=.8))
    for key, (X, Y, _) in MARKERS.items():
        cx, cy = to_px(X, Y)
        color = "#d62728" if key == "TX" else ("#1a9850" if key.startswith("C") else "#1f5fd6")
        axis.plot(cx, cy, marker="*" if key == "TX" else ("s" if key.startswith("C") else "o"),
                  color=color, ms=15 if key == "TX" else 8, mec="white", mew=.9, zorder=5)
        condition = "" if key == "TX" else ("  LOS" if report[key]["los"] else "  NLOS")
        device = NODE_IDS.get(key, ROVING_TEST_NODE)
        axis.annotate("%s%s\n%s\n(%.2f, %.2f)" % (key, condition, device, X, Y), (cx, cy),
                      textcoords="offset points", xytext=(0, 12), ha="center", fontsize=7.5,
                      color=color, weight="bold",
                      bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=.8),
                      zorder=6)
    axis.text(20, 42, "pnu_3f_corridor / %s   coordinates in meters, frame %s  "
              "(origin = proxy mesh grid min corner, +X to drawing-left, +Y to drawing-down, "
              "RX z=%.2f TX z=%.2f, ceiling 3.00)" % (SCENE_ID, CS_ID, RX_Z, TX_Z),
              fontsize=8, color="#333")
    axis.text(20, 68, "scale 1 px = %s m (fit to proxy mesh, IoU 0.74) — position uncertainty "
              "about +-0.5 m     LOS/NLOS = 2D sight line to TX through the proxy mesh"
              % M_PER_PX, fontsize=8, color="#333")
    axis.plot([], [], "*", color="#d62728", ms=14, label="TX  fixed transmitter")
    axis.plot([], [], "s", color="#1a9850", ms=9,
              label="C1-C4  calibration RX (2 LOS + 2 NLOS), one fixed node each")
    axis.plot([], [], "o", color="#1f5fd6", ms=9,
              label="T1-T10  held-out test RX, all measured by the roving %s" % ROVING_TEST_NODE)
    axis.legend(loc="lower left", bbox_to_anchor=(0.01, -0.02), frameon=False, fontsize=10)
    figure.tight_layout(pad=0.2)
    figure.savefig(GRID, dpi=150, facecolor="white")


def main():
    report, problems = audit()
    print("%-4s %-8s %8s %8s %8s %7s  %s" % (
        "id", "장치", "X", "Y", "여유", "TX거리", "가시선"))
    for key, (x, y, _) in MARKERS.items():
        item = report[key]
        print("%-4s %-8s %8.2f %8.2f %8.2f %7.2f  %s" % (
            key, NODE_IDS.get(key, ROVING_TEST_NODE), x, y,
            item["clearance"], item["distance"],
            "-" if key == "TX" else ("LOS" if item["los"] else "NLOS")))
    if problems:
        raise SystemExit("\n".join(["배치 규칙 위반:"] + ["  - " + p for p in problems]))
    print("\nwrote", write_markers(report))
    draw(report)
    print("wrote", GRID)


if __name__ == "__main__":
    main()
