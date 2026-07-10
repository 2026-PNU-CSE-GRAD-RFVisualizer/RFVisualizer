"""YAML 설정 로드와 검증."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, Iterable

import numpy as np
import yaml


class ConfigError(ValueError):
    """사용자가 수정할 수 있는 설정에 문제가 있을 때 발생한다."""


DEFAULT_CONFIG: Dict[str, Any] = {
    "schema_version": "1.0",
    "scene": {
        "up_vector": [0.0, 0.0, 1.0],
        "point_source": "mesh_uniform",
        "random_seed": 20260710,
    },
    "preprocessing": {
        "mesh_components": {
            "enabled": False,
            "keep_largest": 0,
            "min_triangles": 1000,
            "min_area_ratio": 0.0,
        },
        "sampling": {"number_of_points": 500000},
        "voxel_downsampling": {
            "enabled": True,
            "voxel_size": None,
            "voxel_size_ratio": 0.002,
        },
        "statistical_outlier_removal": {
            "enabled": False,
            "nb_neighbors": 30,
            "std_ratio": 2.5,
        },
        "radius_outlier_removal": {
            "enabled": False,
            "nb_points": 12,
            "radius": None,
            "radius_ratio": 0.006,
        },
        "normal_estimation": {
            "enabled": True,
            "search_radius": None,
            "search_radius_ratio": 0.006,
            "max_nn": 30,
        },
    },
    "normal_analysis": {
        "thresholds": [0.25, 0.35, 0.50],
        "histogram_bins": 50,
        "horizontal_min_up_dot": 0.85,
    },
    "wall_extraction": {
        "enabled": True,
        "normal_filter": {
            "enabled": True,
            "point_normal_max_up_dot": 0.35,
        },
        "ransac": {
            "distance_threshold": None,
            "distance_threshold_ratio": 0.001,
            "ransac_n": 3,
            "num_iterations": 3000,
            "max_planes": 12,
            "max_attempts": 60,
            "min_inliers": 300,
            "min_inlier_ratio": 0.002,
            "plane_normal_max_up_dot": 0.25,
            "max_consecutive_small_planes": 5,
        },
        "components": {
            "enabled": True,
            "eps": None,
            "eps_ratio": 0.015,
            "min_points": 10,
            "merge_valid_components": True,
            "min_vertical_span": None,
            "min_vertical_span_ratio": 0.20,
        },
        "meshing": {
            "lower_percentile": 1.0,
            "upper_percentile": 99.0,
            "margin_ratio": 0.02,
            "min_area": None,
            "min_area_ratio": 0.00075,
        },
    },
    "plane_extraction": {
        "distance_threshold": None,
        "distance_threshold_ratio": 0.001,
        "ransac_n": 3,
        "num_iterations": 1000,
        "max_planes": 20,
        "max_attempts": 40,
        "min_inliers": 800,
        "min_inlier_ratio": 0.005,
        "min_area": None,
        "min_area_ratio": 0.002,
        "stop_remaining_ratio": 0.05,
        "inlier_components": {
            "enabled": False,
            "eps": None,
            "eps_ratio": 0.015,
            "min_points": 10,
            "preserve_boundary_planes": True,
        },
        "orientation_limits": {
            "enabled": False,
            "horizontal": 12,
            "vertical": 12,
            "other": 6,
        },
    },
    "classification": {
        "horizontal_max_angle_deg": 15.0,
        "vertical_max_deviation_deg": 15.0,
        "boundary_height_ratio": 0.15,
        "height_lower_percentile": 5.0,
        "height_upper_percentile": 95.0,
    },
    "plane_meshing": {
        "lower_percentile": 1.0,
        "upper_percentile": 99.0,
        "margin_ratio": 0.02,
        "min_extent": None,
        "min_extent_ratio": 0.002,
        "vertical_alignment_max_dot": 0.3,
    },
    "preview": {
        "residual_color": [0.45, 0.45, 0.45],
        "write_candidate_meshes": True,
    },
    "selection": [],
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def normalize_vector(values: Iterable[float], field_name: str = "vector") -> np.ndarray:
    array = np.asarray(list(values), dtype=float)
    if array.shape != (3,) or not np.all(np.isfinite(array)):
        raise ConfigError("{}는 유한한 숫자 3개여야 합니다.".format(field_name))
    length = float(np.linalg.norm(array))
    if length <= 1e-12:
        raise ConfigError("{}는 영벡터일 수 없습니다.".format(field_name))
    return array / length


def _require_positive(config: Dict[str, Any], path: str, allow_zero: bool = False) -> None:
    value: Any = config
    for part in path.split("."):
        value = value[part]
    valid = value >= 0 if allow_zero else value > 0
    if not valid:
        relation = "0 이상" if allow_zero else "0보다 큰"
        raise ConfigError("{} 값은 {} 수여야 합니다.".format(path, relation))


def _value_at(config: Dict[str, Any], path: str) -> Any:
    value: Any = config
    for part in path.split("."):
        value = value[part]
    return value


def _require_positive_integer(config: Dict[str, Any], path: str) -> None:
    value = _value_at(config, path)
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or int(value) <= 0:
        raise ConfigError("{} 값은 양의 정수여야 합니다.".format(path))


def _require_boolean(config: Dict[str, Any], path: str) -> None:
    if not isinstance(_value_at(config, path), bool):
        raise ConfigError("{} 값은 true 또는 false여야 합니다.".format(path))


def _require_probability(config: Dict[str, Any], path: str) -> None:
    value = float(_value_at(config, path))
    if not np.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ConfigError("{} 값은 0과 1 사이여야 합니다.".format(path))


def _validate_absolute_ratio(
    config: Dict[str, Any], absolute_path: str, ratio_path: str
) -> None:
    """절대값을 우선하며, 계산에 쓰일 값이 양수가 되도록 검사한다."""

    absolute = _value_at(config, absolute_path)
    ratio = float(_value_at(config, ratio_path))
    if not np.isfinite(ratio) or ratio < 0.0:
        raise ConfigError("{} 값은 0 이상이어야 합니다.".format(ratio_path))
    if absolute is not None:
        absolute_value = float(absolute)
        if not np.isfinite(absolute_value) or absolute_value <= 0.0:
            raise ConfigError("{} 값은 0보다 커야 합니다.".format(absolute_path))
    elif ratio <= 0.0:
        raise ConfigError(
            "{}가 null이면 {} 값은 0보다 커야 합니다.".format(
                absolute_path, ratio_path
            )
        )


def format_threshold_token(value: float) -> str:
    """법선 기준값을 충돌 없이 파일명에 쓸 문자열로 바꾼다."""

    number = float(value)
    if not np.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ConfigError("법선 기준값은 0과 1 사이여야 합니다.")
    if number == 0.0:
        number = 0.0
    text = np.format_float_positional(number, unique=True, trim="-")
    if "." not in text:
        text = text + ".00"
    else:
        integer, fraction = text.split(".", 1)
        text = integer + "." + fraction.ljust(2, "0")
    return text.replace(".", "_")


def validate_config(config: Dict[str, Any]) -> Dict[str, Any]:
    normalize_vector(config["scene"]["up_vector"], "scene.up_vector")

    point_source = config["scene"]["point_source"]
    allowed_sources = {"mesh_uniform", "mesh_vertices", "reference_point_cloud"}
    if point_source not in allowed_sources:
        raise ConfigError(
            "scene.point_source는 {} 중 하나여야 합니다.".format(
                ", ".join(sorted(allowed_sources))
            )
        )

    positive_paths = (
        "preprocessing.sampling.number_of_points",
        "plane_extraction.ransac_n",
        "plane_extraction.num_iterations",
        "plane_extraction.max_planes",
        "plane_extraction.max_attempts",
        "plane_extraction.min_inliers",
    )
    for path in positive_paths:
        _require_positive(config, path)

    for path in (
        "normal_analysis.histogram_bins",
        "wall_extraction.ransac.ransac_n",
        "wall_extraction.ransac.num_iterations",
        "wall_extraction.ransac.max_planes",
        "wall_extraction.ransac.max_attempts",
        "wall_extraction.ransac.min_inliers",
        "wall_extraction.ransac.max_consecutive_small_planes",
        "wall_extraction.components.min_points",
    ):
        _require_positive_integer(config, path)

    for path in (
        "wall_extraction.enabled",
        "wall_extraction.normal_filter.enabled",
        "wall_extraction.components.enabled",
        "wall_extraction.components.merge_valid_components",
    ):
        _require_boolean(config, path)

    for path in (
        "plane_extraction.min_inlier_ratio",
        "plane_extraction.stop_remaining_ratio",
        "normal_analysis.horizontal_min_up_dot",
        "wall_extraction.normal_filter.point_normal_max_up_dot",
        "wall_extraction.ransac.min_inlier_ratio",
        "wall_extraction.ransac.plane_normal_max_up_dot",
    ):
        _require_probability(config, path)

    thresholds = config["normal_analysis"]["thresholds"]
    if not isinstance(thresholds, list) or not thresholds:
        raise ConfigError("normal_analysis.thresholds는 하나 이상의 기준값 목록이어야 합니다.")
    threshold_values = [float(value) for value in thresholds]
    for value in threshold_values:
        if not np.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ConfigError("normal_analysis.thresholds 값은 0과 1 사이여야 합니다.")
    tokens = [format_threshold_token(value) for value in threshold_values]
    if len(set(threshold_values)) != len(threshold_values) or len(set(tokens)) != len(tokens):
        raise ConfigError("normal_analysis.thresholds에 중복되거나 파일명이 충돌하는 값이 있습니다.")

    for absolute_path, ratio_path in (
        (
            "wall_extraction.ransac.distance_threshold",
            "wall_extraction.ransac.distance_threshold_ratio",
        ),
        ("wall_extraction.components.eps", "wall_extraction.components.eps_ratio"),
        (
            "wall_extraction.components.min_vertical_span",
            "wall_extraction.components.min_vertical_span_ratio",
        ),
        ("wall_extraction.meshing.min_area", "wall_extraction.meshing.min_area_ratio"),
    ):
        _validate_absolute_ratio(config, absolute_path, ratio_path)

    for path in (
        "wall_extraction.meshing.margin_ratio",
    ):
        value = float(_value_at(config, path))
        if not np.isfinite(value) or value < 0.0:
            raise ConfigError("{} 값은 0 이상이어야 합니다.".format(path))

    lower = float(config["plane_meshing"]["lower_percentile"])
    upper = float(config["plane_meshing"]["upper_percentile"])
    if not 0.0 <= lower < upper <= 100.0:
        raise ConfigError(
            "plane_meshing의 하한 백분위수는 상한보다 작고 0~100 범위여야 합니다."
        )

    height_lower = float(config["classification"]["height_lower_percentile"])
    height_upper = float(config["classification"]["height_upper_percentile"])
    if not 0.0 <= height_lower < height_upper <= 100.0:
        raise ConfigError(
            "classification의 높이 하한 백분위수는 상한보다 작고 0~100 범위여야 합니다."
        )

    wall_lower = float(config["wall_extraction"]["meshing"]["lower_percentile"])
    wall_upper = float(config["wall_extraction"]["meshing"]["upper_percentile"])
    if not 0.0 <= wall_lower < wall_upper <= 100.0:
        raise ConfigError(
            "wall_extraction.meshing의 하한 백분위수는 상한보다 작고 0~100 범위여야 합니다."
        )

    if int(config["plane_extraction"]["ransac_n"]) < 3:
        raise ConfigError("plane_extraction.ransac_n은 3 이상이어야 합니다.")
    if int(config["wall_extraction"]["ransac"]["ransac_n"]) < 3:
        raise ConfigError("wall_extraction.ransac.ransac_n은 3 이상이어야 합니다.")

    return config


def load_config(path: Path) -> Dict[str, Any]:
    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError("설정 파일을 찾을 수 없습니다: {}".format(config_path))
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError("설정 파일을 읽을 수 없습니다: {}".format(exc)) from exc
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise ConfigError("YAML 최상위 값은 키와 값의 모음이어야 합니다.")
    return validate_config(_deep_merge(DEFAULT_CONFIG, loaded))


def resolve_scene_value(
    section: Dict[str, Any], absolute_key: str, ratio_key: str, scene_extent: float
) -> float:
    """절대값이 있으면 우선 사용하고, 없으면 장면 대각선 비율을 사용한다."""

    absolute = section.get(absolute_key)
    if absolute is not None:
        value = float(absolute)
    else:
        value = float(section[ratio_key]) * float(scene_extent)
    if not np.isfinite(value) or value <= 0.0:
        raise ConfigError(
            "{} 또는 {}로 계산한 값은 0보다 커야 합니다.".format(
                absolute_key, ratio_key
            )
        )
    return value
