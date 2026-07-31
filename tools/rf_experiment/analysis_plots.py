"""분석 결과 그림 생성."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple

import numpy as np

from .analysis_inputs import AnalysisError


def _regular_grid(
    positions: np.ndarray, values: np.ndarray
) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    xs = np.unique(positions[:, 0])
    ys = np.unique(positions[:, 1])
    if len(xs) * len(ys) != len(positions):
        return None
    matrix = np.full((len(ys), len(xs)), np.nan, dtype=float)
    x_index = {float(value): index for index, value in enumerate(xs)}
    y_index = {float(value): index for index, value in enumerate(ys)}
    for point, value in zip(positions, values):
        row, column = y_index[float(point[1])], x_index[float(point[0])]
        if math.isfinite(matrix[row, column]):
            return None
        matrix[row, column] = value
    if not np.all(np.isfinite(matrix)):
        return None
    return xs, ys, matrix


def _plot_heatmap(
    path: Path,
    positions: np.ndarray,
    values: np.ndarray,
    calibration: Sequence[Mapping[str, Any]],
    test: Sequence[Mapping[str, Any]],
    title: str,
    color_limits: Tuple[float, float],
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(10, 7))
    regular = _regular_grid(positions, values)
    vmin, vmax = color_limits
    if regular is not None:
        xs, ys, matrix = regular
        image = axis.pcolormesh(
            xs, ys, matrix, shading="nearest", cmap="viridis", vmin=vmin, vmax=vmax
        )
    else:
        if len(positions) < 3:
            raise AnalysisError("히트맵에는 서로 다른 Grid 점이 최소 3개 필요합니다.")
        image = axis.tricontourf(
            positions[:, 0],
            positions[:, 1],
            values,
            levels=np.linspace(vmin, vmax, 24),
            cmap="viridis",
            vmin=vmin,
            vmax=vmax,
        )
    figure.colorbar(image, ax=axis, label="RSSI (dBm)")
    cal_positions = np.asarray([row["position"] for row in calibration])
    test_positions = np.asarray([row["position"] for row in test])
    axis.scatter(
        cal_positions[:, 0],
        cal_positions[:, 1],
        marker="P",
        color="white",
        edgecolor="black",
        s=90,
        label="Calibration",
    )
    axis.scatter(
        test_positions[:, 0],
        test_positions[:, 1],
        marker="x",
        color="red",
        s=55,
        label="Test",
    )
    axis.set_aspect("equal")
    axis.set_xlabel("X (m)")
    axis.set_ylabel("Y (m)")
    axis.set_title(title)
    axis.legend(loc="best")
    figure.tight_layout()
    figure.savefig(path, dpi=170)
    plt.close(figure)


def _plot_measured_points(path: Path, summary: Sequence[Mapping[str, Any]]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(10, 7))
    values = np.asarray([row["actual_rssi_dbm"] for row in summary])
    positions = np.asarray([row["position"] for row in summary])
    image = axis.scatter(
        positions[:, 0], positions[:, 1], c=values, cmap="viridis", s=100, edgecolor="black"
    )
    for row in summary:
        axis.annotate(
            row["point_id"],
            row["position"][:2],
            xytext=(4, 4),
            textcoords="offset points",
            fontsize=7,
        )
    figure.colorbar(image, ax=axis, label="Corrected RSSI (dBm)")
    axis.set_aspect("equal")
    axis.set_xlabel("X (m)")
    axis.set_ylabel("Y (m)")
    axis.set_title("Measured calibration and test points")
    figure.tight_layout()
    figure.savefig(path, dpi=170)
    plt.close(figure)


def _plot_prediction_vs_measurement(path: Path, comparison: Mapping[str, Any]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    actual = comparison["test_actual"]
    predictions = comparison["test_predictions"]
    colors = {"raw_sionna": "#377eb8", "plain_idw": "#ff7f00", "residual_idw": "#4daf4a"}
    labels = {
        "raw_sionna": "Raw Sionna RT",
        "plain_idw": "Plain IDW",
        "residual_idw": "Sionna RT + Residual IDW",
    }
    all_values = np.concatenate([actual] + [value for value in predictions.values()])
    minimum, maximum = float(np.min(all_values)), float(np.max(all_values))
    padding = max(1.0, 0.05 * (maximum - minimum))
    figure, axis = plt.subplots(figsize=(8, 8))
    for name, values in predictions.items():
        axis.scatter(actual, values, label=labels[name], color=colors[name], alpha=0.85)
    axis.plot(
        [minimum - padding, maximum + padding],
        [minimum - padding, maximum + padding],
        color="black",
        linestyle="--",
        linewidth=1,
    )
    axis.set_xlim(minimum - padding, maximum + padding)
    axis.set_ylim(minimum - padding, maximum + padding)
    axis.set_aspect("equal", adjustable="box")
    axis.set_xlabel("Measured RSSI (dBm)")
    axis.set_ylabel("Predicted RSSI (dBm)")
    axis.set_title("Prediction versus measurement at held-out test points")
    axis.legend(loc="best")
    figure.tight_layout()
    figure.savefig(path, dpi=170)
    plt.close(figure)
