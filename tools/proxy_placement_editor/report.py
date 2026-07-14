"""Human-readable provisional placement report."""

from __future__ import annotations

from typing import Any, Dict


def placement_report_markdown(report: Dict[str, Any], files: Dict[str, str]) -> str:
    lines = [
        "# Phase 2-C Proxy Placement Report",
        "",
        "> **PROVISIONAL GEOMETRY** — 현장 실측으로 검증되지 않았으며 실제 RSSI 정확도로 해석하면 안 됩니다.",
        "",
        "- Scenario: `{}`".format(report.get("scenario_id")),
        "- Validation success: `{}`".format(report.get("success")),
        "- Enabled obstacles: `{}`".format(report.get("enabled_obstacle_count")),
        "- Renderable obstacles: `{}`".format(report.get("renderable_obstacle_count")),
        "- Maximum coordinate round-trip error: `{:.3e}`".format(
            report.get("maximum_coordinate_round_trip_error", 0.0)
        ),
        "",
        "## Objects",
        "",
        "| ID | Enabled | Status | Material | Min floor | Min ceiling | Min wall |",
        "|---|---:|---|---|---:|---:|---:|",
    ]
    for value in report.get("objects", []):
        if value.get("renderable"):
            containment = value["phase2b_validation"]["containment"]
            lines.append(
                "| {} | {} | {} | {} | {:.4f} | {:.4f} | {:.4f} |".format(
                    value["id"],
                    value["enabled"],
                    value["status"],
                    value["material"]["category"],
                    containment["minimum_floor_clearance_m"],
                    containment["minimum_ceiling_clearance_m"],
                    containment["minimum_wall_clearance_m"],
                )
            )
        else:
            lines.append(
                "| {} | {} | {} | - | - | - | - |".format(
                    value["id"], value["enabled"], value["status"]
                )
            )
    lines.extend(["", "## Files", ""])
    lines.extend(
        "- {}: `{}`".format(key, value) for key, value in sorted(files.items())
    )
    lines.extend(
        [
            "",
            "## Limits",
            "",
            "- Metric scale is provisional.",
            "- Candidate default sizes are UI placeholders.",
            "- No classroom object position was inferred automatically.",
            "- RF material values have not been calibrated against measurements.",
            "",
        ]
    )
    return "\n".join(lines)
