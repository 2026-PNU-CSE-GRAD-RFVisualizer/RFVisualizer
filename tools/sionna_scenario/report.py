"""Markdown reporting for the Phase 2-B synthetic blocker A/B run."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from tools.sionna_smoke_test.io_utils import atomic_write_text


def _number(value: Any, digits: int = 6) -> str:
    if value is None:
        return "n/a"
    return ("{:.%dg}" % digits).format(float(value))


def write_ab_report(result: Dict[str, Any], path: Path) -> str:
    environment = result["environment"]
    baseline = result["baseline_runs"][0]
    variant = result["variant_run"]
    reproducibility = result["reproducibility"]
    path_comparison = result["path_comparison"]
    rx_los = path_comparison["rx_los"]
    coverage = result["coverage_comparison"]
    validation = result["validation"]
    prepared = result["variant_prepared"]
    obstacle_lines = []
    for record in prepared.obstacle_records:
        containment = record["validation"]["containment"]
        obstacle_lines.extend(
            [
                "- ID: `{}`".format(record["id"]),
                "- Geometry: `{}` / bounds `{}` ~ `{}` m".format(
                    record["geometry_type"],
                    record["validation"]["bounds"]["min"],
                    record["validation"]["bounds"]["max"],
                ),
                "- Material: `{}` (`{}`)".format(
                    record["material"]["category"],
                    record["material"]["actual_sionna_material_name"],
                ),
                "- Minimum floor / ceiling / wall clearance: {} / {} / {} m".format(
                    _number(containment["minimum_floor_clearance_m"]),
                    _number(containment["minimum_ceiling_clearance_m"]),
                    _number(containment["minimum_wall_clearance_m"]),
                ),
                "- Configured LoS intersection: `{}`".format(
                    record["validation"]["los"]["any_intersection"]
                ),
            ]
        )
    path_evidence = rx_los["obstacle_evidence"]
    performance = validation["performance"]
    packages = environment.get("packages", {})
    lines = [
        "# RFVisualizer Phase 2-B Synthetic Blocker A/B Report\n",
        "> **SYNTHETIC / PROVISIONAL / NOT PHYSICALLY VALIDATED**  \n",
        "> 이 결과는 장애물 계층과 A/B 파이프라인 검증용이며 실제 강의실 RSSI 정확도를 뜻하지 않습니다.\n",
        "## Environment\n",
        "- Python: `{}`".format(environment.get("python_version")),
        "- Sionna RT: `{}`".format(packages.get("sionna_rt_distribution")),
        "- Mitsuba / Dr.Jit: `{}` / `{}`".format(
            packages.get("mitsuba"), packages.get("drjit")
        ),
        "- Mitsuba variant: `{}`".format(environment.get("mitsuba_variant")),
        "- GPU: `{}`".format(
            ", ".join(value["name"] for value in environment.get("gpu", {}).get("gpus", []))
            or "unavailable"
        ),
        "\n## Baseline reproducibility\n",
        "- Repeat count: `{}`".format(reproducibility["repeat_count"]),
        "- Path structure stable: `{}`".format(
            reproducibility["paths"]["path_structures_match"]
        ),
        "- Coverage mean / p95 / max repeat delta: `{}` / `{}` / `{}` dB".format(
            _number(reproducibility["coverage"]["mean_absolute_repeat_delta_db"]),
            _number(reproducibility["coverage"]["percentile_95_absolute_repeat_delta_db"]),
            _number(reproducibility["coverage"]["maximum_absolute_repeat_delta_db"]),
        ),
        "- Noise floor: `{}` dB".format(
            _number(reproducibility["noise_floor"]["coverage_db"])
        ),
        "- Within declared numerical tolerance: `{}`".format(
            reproducibility["reproducible_within_tolerance"]
        ),
        "\n## Synthetic obstacle\n",
        *obstacle_lines,
        "\n## Scene composition\n",
        "- Baseline objects / triangles: `{}` / `{}`".format(
            baseline["manifest"]["total_object_count"],
            baseline["manifest"]["total_triangle_count"],
        ),
        "- Variant objects / triangles: `{}` / `{}`".format(
            variant["manifest"]["total_object_count"],
            variant["manifest"]["total_triangle_count"],
        ),
        "- Independent shapes (`merge_shapes=false`): `{}`".format(
            variant["manifest"]["object_layers_independent"]
        ),
        "\n## Path A/B\n",
        "- Baseline `rx_los` LoS: `{}` ({} path)".format(
            rx_los["baseline"]["los_path_exists"], rx_los["baseline"]["los_path_count"]
        ),
        "- Variant `rx_los` LoS: `{}` ({} path)".format(
            rx_los["variant"]["los_path_exists"], rx_los["variant"]["los_path_count"]
        ),
        "- Total path count delta: `{}`".format(
            path_comparison["changes"]["total_path_count_delta"]
        ),
        "- Specular reflection path count delta: `{}`".format(
            path_comparison["changes"]["specular_reflection_path_count_delta"]
        ),
        "- Blocker interaction path count: `{}`".format(
            path_evidence["variant_obstacle_interaction_path_count"]
        ),
        "- Blocker-related evidence: `{}` (`{}`)".format(
            path_evidence["blocker_related_change"], path_evidence["evidence_basis"]
        ),
        "\n## Coverage A/B\n",
        "- Grid / common valid cells: `{}` / `{}`".format(
            coverage["grid_shape"], coverage["common_valid_cell_count"]
        ),
        "- Mean / mean absolute delta: `{}` / `{}` dB".format(
            _number(coverage["mean_delta_db"]),
            _number(coverage["mean_absolute_delta_db"]),
        ),
        "- Minimum / maximum delta: `{}` / `{}` dB".format(
            _number(coverage["minimum_delta_db"]), _number(coverage["maximum_delta_db"])
        ),
        "- `|delta| > 1 dB` / `> 3 dB`: `{}` / `{}` cells".format(
            coverage["abs_delta_gt_1_db_cell_count"],
            coverage["abs_delta_gt_3_db_cell_count"],
        ),
        "- A/B change exceeds baseline noise: `{}`".format(
            coverage["ab_change_exceeds_noise_floor"]
        ),
        "\n## Coordinate bridge\n",
        "- Metric ↔ PGSR maximum round-trip error: `{}`".format(
            _number(variant["manifest"]["coordinate_bridge_validation"]["maximum_error"])
        ),
        "- Obstacle metric and PGSR vertices: `variant/obstacles_metric.json`, `variant/obstacles_scene.json`\n",
        "## Performance\n",
        "- Baseline first path / coverage solve: `{}` / `{}` s".format(
            _number(performance["baseline_runs"][0]["path_solve_seconds"]),
            _number(performance["baseline_runs"][0]["coverage_solve_seconds"]),
        ),
        "- Variant path / coverage solve: `{}` / `{}` s".format(
            _number(performance["variant"]["path_solve_seconds"]),
            _number(performance["variant"]["coverage_solve_seconds"]),
        ),
        "- Comparison compute / export: `{}` / `{}` s".format(
            _number(performance["comparison_compute_seconds"]),
            _number(performance["comparison_export_seconds"]),
        ),
        "- Total before report: `{}` s".format(
            _number(performance["total_seconds_before_report"])
        ),
        "\n## Validation\n",
        "- Overall success: `{}`".format(validation["overall_success"]),
        "- Detailed checks: `experiment_validation.json`",
        "- Reproducibility: `reproducibility.json`",
        "- Path comparison: `path_comparison.json`",
        "- Coverage comparison: `coverage_comparison.json`",
        "\n## Limitations\n",
        "- 장애물은 검증 전용 synthetic box이며 실제 책상·칠판·문 위치를 나타내지 않습니다.",
        "- Room scale과 RF material은 provisional이며 현장 실측으로 검증되지 않았습니다.",
        "- 실제 RSSI, 고해상도 Radio Map, Viewer/실시간 기능은 이번 범위가 아닙니다.",
        "",
    ]
    destination = Path(path)
    atomic_write_text(destination, "\n".join(lines))
    return str(destination.resolve())


def write_phase2b_index(result: Dict[str, Any], path: Path, report_path: str) -> str:
    """Write the phase-level pointer and headline evidence beside scenario outputs."""

    coverage = result["coverage_comparison"]
    rx_los = result["path_comparison"]["rx_los"]
    validation = result["validation"]
    lines = [
        "# RFVisualizer Phase 2-B Validation",
        "",
        "> **SYNTHETIC / PROVISIONAL / physically_validated=false**",
        "",
        "- Overall success: `{}`".format(validation["overall_success"]),
        "- Baseline → variant `rx_los`: `{}` → `{}`".format(
            rx_los["baseline"]["los_path_exists"],
            rx_los["variant"]["los_path_exists"],
        ),
        "- Common valid cells: `{}`".format(coverage["common_valid_cell_count"]),
        "- Mean / maximum-absolute coverage delta: `{:.6g}` / `{:.6g}` dB".format(
            coverage["mean_delta_db"], coverage["maximum_absolute_delta_db"]
        ),
        "- Full A/B report: `{}`".format(report_path),
        "",
        "이 검증은 synthetic blocker 계층의 작동만 입증하며 실제 강의실 물체나 RSSI 정확도를 입증하지 않습니다.",
        "",
    ]
    destination = Path(path)
    atomic_write_text(destination, "\n".join(lines))
    return str(destination.resolve())
