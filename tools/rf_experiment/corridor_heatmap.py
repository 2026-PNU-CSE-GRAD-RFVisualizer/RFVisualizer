"""복도 Sionna 격자에 all-4 전역 편향 보정을 적용한 그림."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Sequence

import numpy as np

from .corridor_measurements import MARKERS_PATH, Measurement


def _rows(path: Path) -> tuple[dict[str, str], ...]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return tuple(csv.DictReader(handle))


def _global_bias(measurements: Sequence[Measurement], points_csv: Path) -> float:
    simulated = {
        row["point_id"]: float(row["sionna_rssi_dbm"])
        for row in _rows(points_csv)
    }
    residuals = [
        row.corrected_rssi - simulated[row.point_id]
        for row in measurements
        if row.role == "calibration"
    ]
    return float(np.mean(residuals))


def _plot(
    path: Path,
    grid_rows: tuple[dict[str, str], ...],
    values: np.ndarray,
    measurements: Sequence[Measurement],
    title: str,
    limits: tuple[float, float],
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(8, 10))
    image = axis.scatter(
        [float(row["x"]) for row in grid_rows],
        [float(row["y"]) for row in grid_rows],
        c=values,
        cmap="viridis",
        marker="s",
        s=12,
        linewidths=0,
        vmin=limits[0],
        vmax=limits[1],
        rasterized=True,
    )
    marker_document = json.loads(MARKERS_PATH.read_text(encoding="utf-8"))
    tx_x, tx_y, _ = marker_document["tx"][0]["position_m"]
    axis.scatter(
        tx_x,
        tx_y,
        marker="*",
        color="red",
        edgecolor="black",
        s=180,
        label="TX",
    )
    for role, marker, color, label in (
        ("calibration", "P", "white", "Calibration"),
        ("test", "x", "red", "Held-out Test"),
    ):
        unique = {row.point_id: row for row in measurements if row.role == role}
        axis.scatter(
            [row.x for row in unique.values()],
            [row.y for row in unique.values()],
            marker=marker,
            color=color,
            edgecolor="black" if marker == "P" else None,
            s=75,
            label=label,
        )
    figure.colorbar(image, ax=axis, label="RSSI (dBm)")
    axis.set(xlabel="X (m)", ylabel="Y (m)", title=title)
    axis.set_aspect("equal")
    axis.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=3)
    figure.tight_layout()
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)


def export_global_bias_heatmaps(
    output: Path,
    measurements: Sequence[Measurement],
    points_csv: Path,
) -> float:
    processed = points_csv.parent
    grid_rows = _rows(processed / "sionna_grid.csv")
    raw = np.asarray([float(row["sionna_rssi_dbm"]) for row in grid_rows])
    bias = _global_bias(measurements, points_csv)
    calibrated = raw + bias
    limits = (-90.0, -20.0)
    figures = output / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    _plot(figures / "raw_rf_heatmap.png", grid_rows, raw, measurements, "Raw Sionna RT RF map", limits)
    _plot(
        figures / "calibrated_rf_heatmap.png",
        grid_rows,
        calibrated,
        measurements,
        f"Calibrated RF map (global bias {bias:+.2f} dB)",
        limits,
    )
    return bias
