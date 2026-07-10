"""전처리된 점 법선이 높이 방향과 이루는 관계를 분석한다."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, Tuple

import numpy as np

from ..config import format_threshold_token, normalize_vector


class NormalAnalysisError(ValueError):
    """법선 분석 입력이나 출력에 문제가 있을 때 발생한다."""


def compute_normal_up_scores(
    normals: np.ndarray, up_vector: np.ndarray
) -> Tuple[np.ndarray, np.ndarray]:
    """각 법선의 ``abs(normal · up)`` 값과 유효 여부를 반환한다."""

    values = np.asarray(normals, dtype=float)
    if values.ndim != 2 or values.shape[1] != 3:
        raise NormalAnalysisError("점 법선은 N×3 배열이어야 합니다.")
    up = normalize_vector(up_vector, "up_vector")
    lengths = np.linalg.norm(values, axis=1)
    valid = (
        np.all(np.isfinite(values), axis=1)
        & np.isfinite(lengths)
        & (lengths > 1e-12)
    )
    scores = np.full(len(values), np.nan, dtype=float)
    if np.any(valid):
        normalized = values[valid] / lengths[valid, None]
        scores[valid] = np.clip(np.abs(normalized @ up), 0.0, 1.0)
    return scores, valid


def _open3d():
    try:
        import open3d as o3d
    except ImportError as exc:
        raise NormalAnalysisError("법선 PLY 저장에는 Open3D가 필요합니다.") from exc
    return o3d


def _write_empty_point_cloud(path: Path) -> None:
    path.write_text(
        "ply\n"
        "format ascii 1.0\n"
        "comment RFVisualizer empty point preview\n"
        "element vertex 0\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "end_header\n",
        encoding="ascii",
    )


def _write_subset(
    point_cloud: Any,
    indices: np.ndarray,
    path: Path,
    fallback_color: np.ndarray,
) -> None:
    o3d = _open3d()
    selected = np.asarray(indices, dtype=int)
    if not len(selected):
        _write_empty_point_cloud(path)
        return
    subset = point_cloud.select_by_index(selected.tolist())
    if not subset.has_colors():
        subset.paint_uniform_color(np.asarray(fallback_color, dtype=float).tolist())
    if not o3d.io.write_point_cloud(
        str(path), subset, write_ascii=False, compressed=False
    ):
        raise NormalAnalysisError("법선 분석 PLY를 저장하지 못했습니다: {}".format(path))


def _write_histogram_csv(path: Path, rows: list) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=("bin_start", "bin_end", "count", "ratio")
            )
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)
    except OSError as exc:
        raise NormalAnalysisError("법선 히스토그램 CSV를 저장하지 못했습니다: {}".format(exc)) from exc


def write_normal_analysis_outputs(
    point_cloud: Any,
    output_directory: Path,
    settings: Dict[str, Any],
    up_vector: np.ndarray,
) -> Dict[str, Any]:
    """법선 통계, 히스토그램 CSV, 기준값별 PLY를 생성한다."""

    point_count = len(point_cloud.points)
    if not point_cloud.has_normals() or len(point_cloud.normals) != point_count:
        raise NormalAnalysisError(
            "전처리된 점구름에 점 수와 같은 개수의 법선이 없습니다. "
            "preprocessing.normal_estimation.enabled를 켜 주세요."
        )
    scores, valid = compute_normal_up_scores(
        np.asarray(point_cloud.normals, dtype=float), up_vector
    )
    valid_count = int(np.count_nonzero(valid))
    invalid_count = int(point_count - valid_count)
    if valid_count == 0:
        raise NormalAnalysisError("유효한 점 법선이 하나도 없습니다.")

    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    for stale in output.glob("vertical_points_dot_*.ply"):
        stale.unlink()

    histogram_bins = int(settings["histogram_bins"])
    counts, edges = np.histogram(scores[valid], bins=histogram_bins, range=(0.0, 1.0))
    histogram_rows = []
    for index, count in enumerate(counts):
        histogram_rows.append(
            {
                "bin_start": float(edges[index]),
                "bin_end": float(edges[index + 1]),
                "count": int(count),
                "ratio": float(count / valid_count),
            }
        )
    histogram_path = output / "normal_up_dot_histogram.csv"
    _write_histogram_csv(histogram_path, histogram_rows)

    threshold_results = []
    vertical_files: Dict[str, str] = {}
    for threshold_value in settings["thresholds"]:
        threshold = float(threshold_value)
        token = format_threshold_token(threshold)
        indices = np.flatnonzero(valid & (scores <= threshold))
        path = output / "vertical_points_dot_{}.ply".format(token)
        _write_subset(
            point_cloud,
            indices,
            path,
            fallback_color=np.asarray([0.121, 0.466, 0.705]),
        )
        count = int(len(indices))
        threshold_results.append(
            {
                "threshold": threshold,
                "point_count": count,
                "ratio_of_valid_normals": float(count / valid_count),
                "ratio_of_preprocessed_points": float(count / point_count),
                "preview_path": str(path.resolve()),
            }
        )
        vertical_files[token] = str(path.resolve())

    horizontal_threshold = float(settings["horizontal_min_up_dot"])
    horizontal_indices = np.flatnonzero(valid & (scores >= horizontal_threshold))
    horizontal_path = output / "horizontal_points.ply"
    _write_subset(
        point_cloud,
        horizontal_indices,
        horizontal_path,
        fallback_color=np.asarray([1.000, 0.498, 0.000]),
    )

    return {
        "preprocessed_point_count": int(point_count),
        "valid_normal_count": valid_count,
        "invalid_normal_count": invalid_count,
        "threshold_results": threshold_results,
        "horizontal_result": {
            "minimum_up_dot": horizontal_threshold,
            "point_count": int(len(horizontal_indices)),
            "ratio_of_valid_normals": float(len(horizontal_indices) / valid_count),
            "ratio_of_preprocessed_points": float(len(horizontal_indices) / point_count),
            "preview_path": str(horizontal_path.resolve()),
        },
        "histogram": {
            "range": [0.0, 1.0],
            "bin_count": histogram_bins,
            "sample_count": valid_count,
            "bins": histogram_rows,
            "csv_path": str(histogram_path.resolve()),
        },
        "files": {
            "histogram_csv": str(histogram_path.resolve()),
            "vertical_previews": vertical_files,
            "horizontal_preview": str(horizontal_path.resolve()),
        },
    }
