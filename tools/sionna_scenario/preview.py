"""Static Phase 2-B scenario, path, and coverage previews."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Sequence

import numpy as np


class PreviewError(RuntimeError):
    """Raised when a requested preview cannot be rendered."""


def _matplotlib():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        return plt
    except Exception as exc:
        raise PreviewError("matplotlib을 초기화할 수 없습니다: {}".format(exc)) from exc


def _convex_hull(points: np.ndarray) -> np.ndarray:
    values = sorted(set((float(point[0]), float(point[1])) for point in points))
    if len(values) <= 1:
        return np.asarray(values, dtype=float)

    def cross(origin, first, second):
        return (first[0] - origin[0]) * (second[1] - origin[1]) - (
            first[1] - origin[1]
        ) * (second[0] - origin[0])

    lower = []
    for point in values:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0.0:
            lower.pop()
        lower.append(point)
    upper = []
    for point in reversed(values):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0.0:
            upper.pop()
        upper.append(point)
    return np.asarray(lower[:-1] + upper[:-1], dtype=float)


def _room_hull(metric_scene: Any) -> np.ndarray:
    metadata = getattr(metric_scene, "metric_metadata", {})
    corners = np.asarray(metadata.get("bottom_corners", []), dtype=float)
    if (
        corners.ndim == 2
        and len(corners) >= 3
        and corners.shape[1] == 3
        and np.all(np.isfinite(corners))
    ):
        # Room Envelope builder가 기록한 순서를 보존해야 오목한 복도도
        # 실제 footprint대로 보인다. Vertex convex hull은 notch를 지운다.
        return corners[:, :2].copy()
    return _convex_hull(np.asarray(metric_scene.vertices, dtype=float)[:, :2])


def _draw_room(axis: Any, metric_scene: Any) -> None:
    hull = _room_hull(metric_scene)
    if len(hull):
        closed = np.vstack([hull, hull[0]])
        axis.plot(closed[:, 0], closed[:, 1], color="black", linewidth=1.5, label="Room Envelope")


def _draw_obstacles(axis: Any, records: Sequence[Dict[str, Any]]) -> None:
    for index, record in enumerate(records):
        hull = _convex_hull(np.asarray(record["vertices"], dtype=float)[:, :2])
        if len(hull) < 3:
            continue
        synthetic = record.get("purpose") == "validation_only"
        axis.fill(
            hull[:, 0],
            hull[:, 1],
            color="#d62728",
            alpha=0.35,
            edgecolor="#8c1515",
            linewidth=1.5,
            label=("Synthetic obstacle" if synthetic else "Proxy obstacle")
            if index == 0
            else None,
        )


def _draw_devices(axis: Any, positions: Sequence[Dict[str, Any]]) -> None:
    for value in positions:
        point = value["resolved_position_m"]
        transmitter = value["kind"] == "transmitter"
        axis.scatter(
            point[0],
            point[1],
            marker="P" if transmitter else "x",
            color="red" if transmitter else "black",
            s=80,
            zorder=10,
        )
        axis.annotate(value["name"], (point[0], point[1]), xytext=(4, 4), textcoords="offset points")


def export_scenario_preview(
    metric_scene: Any,
    records: Sequence[Dict[str, Any]],
    positions: Sequence[Dict[str, Any]],
    output: Path,
) -> str:
    plt = _matplotlib()
    path = Path(output) / "scenario_preview.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(10, 7))
    _draw_room(axis, metric_scene)
    _draw_obstacles(axis, records)
    _draw_devices(axis, positions)
    axis.set_aspect("equal", adjustable="box")
    axis.set_xlabel("X (m)")
    axis.set_ylabel("Y (m)")
    synthetic = any(value.get("purpose") == "validation_only" for value in records)
    title = "synthetic obstacle" if synthetic else ("proxy obstacle" if records else "empty room")
    axis.set_title("PROVISIONAL {} scenario — top view".format(title))
    axis.legend(loc="best")
    figure.tight_layout()
    figure.savefig(path, dpi=170)
    plt.close(figure)
    return str(path.resolve())


def _coverage_db(result: Dict[str, Any]) -> np.ndarray:
    values = np.asarray(result["values"], dtype=float)
    valid = np.asarray(result["valid_mask"], dtype=bool) & np.asarray(
        result["inside_mask"], dtype=bool
    )
    valid &= np.isfinite(values) & (values > 0.0)
    display = np.full(values.shape, np.nan, dtype=float)
    display[valid] = 10.0 * np.log10(values[valid])
    return display


def _extent(centers: np.ndarray) -> List[float]:
    def spacing(values: np.ndarray) -> float:
        coordinates = np.unique(np.asarray(values, dtype=float)[np.isfinite(values)])
        if len(coordinates) < 2:
            return 1.0
        differences = np.diff(np.sort(coordinates))
        positive = differences[differences > 1e-12]
        return float(np.median(positive)) if len(positive) else 1.0

    x_spacing = spacing(centers[:, :, 0])
    y_spacing = spacing(centers[:, :, 1])
    return [
        float(np.min(centers[:, :, 0]) - x_spacing / 2.0),
        float(np.max(centers[:, :, 0]) + x_spacing / 2.0),
        float(np.min(centers[:, :, 1]) - y_spacing / 2.0),
        float(np.max(centers[:, :, 1]) + y_spacing / 2.0),
    ]


def export_coverage_previews(
    baseline: Dict[str, Any],
    variant: Dict[str, Any],
    records: Sequence[Dict[str, Any]],
    positions: Sequence[Dict[str, Any]],
    output: Path,
) -> Dict[str, str]:
    plt = _matplotlib()
    from matplotlib.colors import TwoSlopeNorm

    directory = Path(output)
    directory.mkdir(parents=True, exist_ok=True)
    baseline_db = _coverage_db(baseline)
    variant_db = _coverage_db(variant)
    common = np.asarray(baseline["valid_mask"], dtype=bool) & np.asarray(
        variant["valid_mask"], dtype=bool
    )
    delta = np.full(baseline_db.shape, np.nan, dtype=float)
    delta[common] = variant_db[common] - baseline_db[common]
    centers = np.asarray(baseline["centers"], dtype=float)
    extent = _extent(centers)
    outputs = {}
    common_min = float(np.nanmin([np.nanmin(baseline_db), np.nanmin(variant_db)]))
    common_max = float(np.nanmax([np.nanmax(baseline_db), np.nanmax(variant_db)]))
    for name, values, title in (
        ("coverage_baseline.png", baseline_db, "A: Empty Room"),
        ("coverage_variant.png", variant_db, "B: Room + Synthetic Obstacle"),
    ):
        figure, axis = plt.subplots(figsize=(10, 7))
        image = axis.imshow(
            values,
            origin="lower",
            extent=extent,
            aspect="equal",
            cmap="viridis",
            vmin=common_min,
            vmax=common_max,
        )
        figure.colorbar(image, ax=axis, label="Path gain (dB)")
        _draw_obstacles(axis, records)
        _draw_devices(axis, positions)
        axis.set_xlabel("X (m)")
        axis.set_ylabel("Y (m)")
        axis.set_title("{} — PROVISIONAL, not physically validated".format(title))
        figure.tight_layout()
        path = directory / name
        figure.savefig(path, dpi=170)
        plt.close(figure)
        outputs[name[:-4] + "_png"] = str(path.resolve())
    maximum = float(np.nanmax(np.abs(delta))) if np.any(common) else 1.0
    maximum = max(maximum, 1e-9)
    figure, axis = plt.subplots(figsize=(10, 7))
    image = axis.imshow(
        delta,
        origin="lower",
        extent=extent,
        aspect="equal",
        cmap="coolwarm",
        norm=TwoSlopeNorm(vmin=-maximum, vcenter=0.0, vmax=maximum),
    )
    figure.colorbar(image, ax=axis, label="Variant - baseline (dB)")
    _draw_obstacles(axis, records)
    _draw_devices(axis, positions)
    axis.set_xlabel("X (m)")
    axis.set_ylabel("Y (m)")
    axis.set_title("Synthetic blocker coverage delta — PROVISIONAL")
    figure.tight_layout()
    delta_path = directory / "coverage_delta.png"
    figure.savefig(delta_path, dpi=170)
    plt.close(figure)
    outputs["coverage_delta_png"] = str(delta_path.resolve())
    return outputs


def _path_polyline(record: Dict[str, Any], positions: Dict[str, np.ndarray]) -> np.ndarray:
    start = positions[record["transmitter"]]
    end = positions[record["receiver"]]
    interactions = np.asarray(record.get("interaction_points_m", []), dtype=float)
    if interactions.size == 0:
        return np.vstack([start, end])
    return np.vstack([start, interactions.reshape((-1, 3)), end])


def _draw_paths(
    axis: Any,
    records: Sequence[Dict[str, Any]],
    position_map: Dict[str, np.ndarray],
    color: str,
    prefix: str,
) -> None:
    used = set()
    for record in records:
        path_type = record.get("path_type", "other")
        points = _path_polyline(record, position_map)
        label = "{} {}".format(prefix, path_type)
        axis.plot(
            points[:, 0],
            points[:, 1],
            color=color,
            linestyle="-" if path_type == "los" else "--",
            linewidth=2.0 if path_type == "los" else 0.8,
            alpha=0.9 if path_type == "los" else 0.32,
            label=label if label not in used else None,
        )
        used.add(label)
        if len(points) > 2:
            axis.scatter(points[1:-1, 0], points[1:-1, 1], color=color, s=8, alpha=0.5)


def export_path_previews(
    metric_scene: Any,
    baseline_records: Sequence[Dict[str, Any]],
    variant_records: Sequence[Dict[str, Any]],
    obstacle_records: Sequence[Dict[str, Any]],
    positions: Sequence[Dict[str, Any]],
    output: Path,
) -> Dict[str, str]:
    plt = _matplotlib()
    directory = Path(output)
    directory.mkdir(parents=True, exist_ok=True)
    position_map = {
        value["name"]: np.asarray(value["resolved_position_m"], dtype=float)
        for value in positions
    }
    specs = [
        ("paths_baseline_top.png", baseline_records, [], "#1f77b4", "Baseline"),
        ("paths_variant_top.png", [], variant_records, "#d62728", "Variant"),
        ("paths_overlay_top.png", baseline_records, variant_records, None, "Overlay"),
    ]
    outputs = {}
    for filename, first, second, color, title in specs:
        figure, axis = plt.subplots(figsize=(10, 7))
        _draw_room(axis, metric_scene)
        _draw_obstacles(axis, obstacle_records)
        if first:
            _draw_paths(axis, first, position_map, color or "#1f77b4", "Baseline")
        if second:
            _draw_paths(axis, second, position_map, color or "#d62728", "Variant")
        _draw_devices(axis, positions)
        axis.set_aspect("equal", adjustable="box")
        axis.set_xlabel("X (m)")
        axis.set_ylabel("Y (m)")
        axis.set_title("{} paths — PROVISIONAL synthetic validation".format(title))
        axis.legend(loc="best", fontsize=8)
        figure.tight_layout()
        path = directory / filename
        figure.savefig(path, dpi=170)
        plt.close(figure)
        outputs[filename[:-4] + "_png"] = str(path.resolve())
    return outputs
