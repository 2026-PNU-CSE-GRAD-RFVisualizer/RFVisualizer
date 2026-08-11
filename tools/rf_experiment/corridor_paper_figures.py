"""KMMS 복도 논문에 사용하는 좌표도와 네 방법 비교 그림."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping, Sequence

import numpy as np

from .analysis import idw_predict
from .corridor_measurements import TESTS_ROOT, Measurement
from .corridor_repeated_compute import INCLUDED_RUNS, PRIMARY_VARIANT, VARIANTS
from .corridor_repeated_models import Method, PredictionRow


METHODS: Final[tuple[Method, ...]] = (
    "raw_sionna",
    "plain_idw_all4",
    "residual_idw_all4",
    "global_bias_all4",
)
METHOD_LABELS: Final = (
    "Raw Sionna RT",
    "Plain IDW",
    "Residual IDW",
    "Global bias",
)
METHOD_COLORS: Final = ("#377eb8", "#ff7f00", "#984ea3", "#4daf4a")


@dataclass(frozen=True, slots=True)
class GridPoint:
    x: float
    y: float
    z: float
    rssi_dbm: float


def _grid_points(path: Path) -> tuple[GridPoint, ...]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return tuple(
            GridPoint(
                x=float(row["x"]),
                y=float(row["y"]),
                z=float(row["z"]),
                rssi_dbm=float(row["sionna_rssi_dbm"]),
            )
            for row in csv.DictReader(handle)
        )


def _point_rssi(path: Path) -> Mapping[str, float]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {
            row["point_id"]: float(row["sionna_rssi_dbm"])
            for row in csv.DictReader(handle)
        }


def _unique_points(
    measurements: Sequence[Measurement], role: str
) -> tuple[Measurement, ...]:
    return tuple(
        {row.point_id: row for row in measurements if row.role == role}.values()
    )


def _plot_markers(axis, measurements: Sequence[Measurement], labels: bool) -> None:
    tx_document = json.loads(
        (TESTS_ROOT / INCLUDED_RUNS[0] / "config/tx_rx.json").read_text(
            encoding="utf-8"
        )
    )
    tx_x, tx_y, _ = tx_document["tx"][0]["position"]
    axis.scatter(
        tx_x,
        tx_y,
        marker="*",
        color="red",
        edgecolor="black",
        s=130,
        label="TX",
        zorder=3,
    )
    for role, marker, color, label in (
        ("calibration", "P", "white", "Calibration"),
        ("test", "x", "red", "Held-out Test"),
    ):
        rows = _unique_points(measurements, role)
        axis.scatter(
            [row.x for row in rows],
            [row.y for row in rows],
            marker=marker,
            color=color,
            edgecolor="black" if marker == "P" else None,
            s=55,
            label=label,
            zorder=3,
        )
        if labels:
            for row in rows:
                axis.annotate(
                    row.point_id,
                    (row.x, row.y),
                    xytext=(4, 4),
                    textcoords="offset points",
                    fontsize=7,
                )


def _grid_method_values(
    measurements: Sequence[Measurement], grid: tuple[GridPoint, ...]
) -> tuple[np.ndarray, ...]:
    point_rssi = _point_rssi(VARIANTS[-1].points_csv)
    positions = np.asarray([(row.x, row.y, row.z) for row in grid])
    raw = np.asarray([row.rssi_dbm for row in grid])
    by_run = {
        run_id: tuple(row for row in measurements if row.run_id == run_id)
        for run_id in sorted({row.run_id for row in measurements})
    }
    plain_runs = []
    residual_runs = []
    bias_runs = []
    for rows in by_run.values():
        calibration = tuple(row for row in rows if row.role == "calibration")
        sample_positions = np.asarray([(row.x, row.y, row.z) for row in calibration])
        actual = np.asarray([row.corrected_rssi for row in calibration])
        simulated = np.asarray([point_rssi[row.point_id] for row in calibration])
        residuals = actual - simulated
        plain_runs.append(idw_predict(sample_positions, actual, positions))
        residual_runs.append(raw + idw_predict(sample_positions, residuals, positions))
        bias_runs.append(raw + float(np.mean(residuals)))
    return (
        raw,
        np.mean(plain_runs, axis=0),
        np.mean(residual_runs, axis=0),
        np.mean(bias_runs, axis=0),
    )


def _coordinate_map(
    path: Path, grid: tuple[GridPoint, ...], measurements: Sequence[Measurement]
) -> None:
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(6.4, 7.2))
    axis.scatter(
        [row.x for row in grid],
        [row.y for row in grid],
        color="#d9d9d9",
        marker="s",
        s=4,
        linewidths=0,
        rasterized=True,
    )
    _plot_markers(axis, measurements, labels=True)
    axis.set(xlabel="X (m)", ylabel="Y (m)")
    axis.set_aspect("equal")
    axis.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=3)
    figure.tight_layout()
    figure.savefig(path, dpi=220, bbox_inches="tight")
    plt.close(figure)


def _prediction_comparison(path: Path, predictions: Sequence[PredictionRow]) -> None:
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(7.2, 7.2))
    observed = []
    estimated = []
    for method, label, color in zip(METHODS, METHOD_LABELS, METHOD_COLORS):
        method_rows = tuple(
            row
            for row in predictions
            if row.variant == PRIMARY_VARIANT and row.method == method
        )
        measured = []
        predicted = []
        for point_id in (f"test-{index:02d}" for index in range(1, 7)):
            rows = tuple(row for row in method_rows if row.point_id == point_id)
            measured.append(float(np.mean([row.measured_rssi_dbm for row in rows])))
            predicted.append(float(np.mean([row.predicted_rssi_dbm for row in rows])))
        observed.extend(measured)
        estimated.extend(predicted)
        axis.scatter(measured, predicted, label=label, color=color, s=38)
    lower = min((*observed, *estimated)) - 2.0
    upper = max((*observed, *estimated)) + 2.0
    axis.plot((lower, upper), (lower, upper), "k--", linewidth=1)
    axis.set(
        xlim=(lower, upper),
        ylim=(lower, upper),
        xlabel="Measured RSSI (dBm)",
        ylabel="Predicted RSSI (dBm)",
    )
    axis.set_aspect("equal", adjustable="box")
    axis.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=220, bbox_inches="tight")
    plt.close(figure)


def _method_maps(
    path: Path,
    grid: tuple[GridPoint, ...],
    measurements: Sequence[Measurement],
) -> None:
    import matplotlib.pyplot as plt

    values = _grid_method_values(measurements, grid)
    figure, axes = plt.subplots(2, 2, figsize=(10, 11), sharex=True, sharey=True)
    image = None
    for axis, data, label in zip(axes.flat, values, METHOD_LABELS):
        image = axis.scatter(
            [row.x for row in grid],
            [row.y for row in grid],
            c=data,
            cmap="viridis",
            marker="s",
            s=7,
            linewidths=0,
            vmin=-90.0,
            vmax=-20.0,
            rasterized=True,
        )
        _plot_markers(axis, measurements, labels=False)
        axis.set_title(label)
        axis.set_aspect("equal")
    for axis in axes[:, 0]:
        axis.set_ylabel("Y (m)")
    for axis in axes[-1, :]:
        axis.set_xlabel("X (m)")
    figure.subplots_adjust(
        left=0.07,
        right=0.84,
        bottom=0.09,
        top=0.97,
        hspace=0.14,
        wspace=0.08,
    )
    if image is not None:
        colorbar_axis = figure.add_axes((0.87, 0.25, 0.025, 0.5))
        figure.colorbar(image, cax=colorbar_axis, label="RSSI (dBm)")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="lower center", ncol=3)
    figure.savefig(path, dpi=220)
    plt.close(figure)


def export_kmms_figures(
    output: Path,
    measurements: Sequence[Measurement],
    predictions: Sequence[PredictionRow],
) -> None:
    """현재 고정된 복도 입력에서 KMMS 논문 그림 세 장을 생성한다."""
    import matplotlib

    matplotlib.use("Agg")
    figures = output / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    grid = _grid_points(VARIANTS[-1].points_csv.parent / "sionna_grid.csv")
    _coordinate_map(figures / "kmms_coordinate_map.png", grid, measurements)
    _prediction_comparison(figures / "kmms_prediction_comparison.png", predictions)
    _method_maps(figures / "kmms_method_maps.png", grid, measurements)
