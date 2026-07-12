"""Phase 2-A 실제 실행 결과를 Markdown으로 정리한다."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from .io_utils import atomic_write_text


def write_report(
    path: Path,
    environment: Dict[str, Any],
    manifest: Dict[str, Any],
    materials: Dict[str, Any],
    positions: Dict[str, Any],
    validation: Dict[str, Any],
    files: Dict[str, Any],
) -> None:
    los = validation["los_validation"]
    reflection = validation["reflection_validation"]
    coverage = validation["coverage_validation"]
    lines = [
        "# Phase 2-A Sionna RT Empty-Room Smoke Test\n\n",
        "> **PROVISIONAL — NOT PHYSICALLY VALIDATED**\n\n",
        "## 결론\n\n",
        "- 전체 상태: **{}**\n".format("통과" if validation["overall_success"] else "실패"),
        "- Sionna RT: `{}`\n".format(environment["packages"]["sionna"]),
        "- Mitsuba: `{}` / variant: `{}`\n".format(
            environment["packages"]["mitsuba"], environment.get("mitsuba_variant")
        ),
        "- GPU backend: `{}`\n\n".format(environment.get("gpu_backend_active")),
        "## 장면\n\n",
        "- 객체: `{}` / 삼각형: `{}`\n".format(
            len(manifest["objects"]), manifest["exported_statistics"]["triangle_count"]
        ),
        "- Bounds: `{}`\n".format(manifest["exported_statistics"]["bounds"]),
        "- 재질: `{}`\n\n".format(
            [value["sionna_material_name"] for value in materials["materials"]]
        ),
        "## TX/RX\n\n",
    ]
    for value in positions["positions"]:
        lines.append(
            "- `{}`: `{}` — floor `{:.3f}m`, ceiling `{:.3f}m`, wall `{:.3f}m` 여유\n".format(
                value["name"],
                value["resolved_position_m"],
                value["validation"]["floor_clearance_m"],
                value["validation"]["ceiling_clearance_m"],
                value["validation"]["minimum_wall_clearance_m"],
            )
        )
    lines.extend(
        [
            "\n## LoS\n\n",
            "- Path count: `{}` / LoS: `{}`\n".format(los["path_count"], los["los_path_count"]),
            "- Euclidean: `{:.9g}m` / Sionna: `{:.9g}m`\n".format(
                los["euclidean_distance_m"], los["sionna_los_distance_m"]
            ),
            "- 거리 오차: `{:.6g}m`\n\n".format(los["distance_error_m"]),
            "## Reflection\n\n",
            "- Path count: `{}` / reflection: `{}`\n".format(
                reflection["path_count"], reflection["reflection_path_count"]
            ),
            "- 최대 interaction: `{}` / 상태: `{}`\n\n".format(
                reflection["maximum_interaction_count"], reflection["status"]
            ),
            "## Coverage\n\n",
            "- Grid: `{}` / cell: `{}`m\n".format(
                coverage["grid_shape_yx"], coverage["cell_size_m"]
            ),
            "- Inside/valid: `{}/{}` / valid ratio: `{:.2%}`\n".format(
                coverage["inside_cell_count"], coverage["valid_cell_count"], coverage["valid_ratio_of_inside"]
            ),
            "- Path gain dB min/mean/max: `{:.3f} / {:.3f} / {:.3f}`\n\n".format(
                coverage["value_min_db"], coverage["value_mean_db"], coverage["value_max_db"]
            ),
            "## 성능\n\n",
        ]
    )
    for name, value in validation["performance_seconds"].items():
        lines.append("- `{}`: `{:.6g}s`\n".format(name, value))
    lines.append("\n## 경고\n\n")
    for warning in validation["warnings"]:
        lines.append("- {}\n".format(warning))
    lines.append("\n## 생성 파일\n\n")
    for name, value in files.items():
        lines.append("- `{}`: `{}`\n".format(name, value))
    atomic_write_text(path, "".join(lines))
