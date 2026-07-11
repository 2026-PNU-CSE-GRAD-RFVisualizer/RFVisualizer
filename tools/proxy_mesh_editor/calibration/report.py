"""Preflight Markdown 보고서와 Metric Calibration 설정 초안을 저장한다."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import yaml


class CalibrationReportError(RuntimeError):
    """진단 보고서 또는 설정 초안을 저장할 수 없을 때 발생한다."""


def _atomic_write(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        raise CalibrationReportError("보고서 파일을 저장할 수 없습니다: {}".format(exc)) from exc


def write_metric_calibration_draft(
    path: Path,
    preflight_config: Dict[str, Any],
    scale_analysis: Dict[str, Any],
    scene_up: List[float],
    target_up: List[float],
    origin: Dict[str, Any],
    x_axis: Dict[str, Any],
    warnings: List[str],
) -> None:
    source_references = preflight_config["calibration_preflight"]["scale_references"]
    references = []
    for item in source_references:
        references.append(
            {
                "name": item["name"],
                "scene_distance": float(item["scene_distance"]),
                "real_distance_m": float(item["assumed_real_distance_m"]),
                "confidence": item.get("confidence"),
                "source": item.get("source"),
            }
        )
    document = {
        "schema_version": "1.0",
        "metric_calibration": {
            "status": "provisional",
            "confidence": preflight_config["calibration_preflight"]["confidence"],
            "scale": {
                "method": scale_analysis["recommended_estimator"],
                "uniform_scale_only": True,
                "provisional_meters_per_scene_unit": scale_analysis[
                    "recommended_meters_per_scene_unit"
                ],
                "references": references,
            },
            "coordinate_frame": {
                "source_up": {
                    "type": "scene_up_vector",
                    "value": scene_up,
                },
                "target_up": target_up,
                "origin": {
                    "type": "envelope_corner",
                    "corner_index": origin["recommended_corner_index"],
                },
                "x_axis": {
                    "type": "envelope_edge",
                    "start_corner": x_axis["recommended_start_corner"],
                    "end_corner": x_axis["recommended_end_corner"],
                    "remove_up_component": True,
                },
                "preserve_handedness": True,
            },
            "warnings": warnings,
        },
    }
    _atomic_write(
        Path(path),
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
    )


def write_preflight_markdown(path: Path, document: Dict[str, Any]) -> None:
    orientation = document["orientation_analysis"]
    rotation = document["rotation_analysis"]
    scale = document["scale_analysis"]
    origin = document["frame_analysis"]["origin_candidate"]
    x_axis = document["frame_analysis"]["x_axis_candidate"]
    lines = [
        "# Metric Calibration Preflight 진단 보고서\n\n",
        "## 결론\n\n",
        "- Preflight 상태: **{}**\n".format(
            "통과" if document["preflight_success"] else "실패"
        ),
        "- Geometry 상하 관계: `{}`\n".format(
            orientation["orientation_diagnosis"]
        ),
        "- Scale 상태: `{}`\n\n".format(scale["spread_status"]),
        "## Up 방향\n\n",
        "- Scene up: `{}`\n".format(orientation["scene_up_vector"]),
        "- Floor 중심: `{}`\n".format(orientation["floor_center"]),
        "- Ceiling 중심: `{}`\n".format(orientation["ceiling_center"]),
        "- 중심 높이 차이: `{:.9g}`\n".format(
            orientation["vertical_center_offset"]
        ),
        "- Corner 높이: `{}`\n".format(
            [round(item["height_along_scene_up"], 9) for item in orientation["corner_heights"]]
        ),
        "- MeshLab 진단: {}\n\n".format(
            orientation["viewer_convention_diagnosis"]
        ),
        "### 원인별 판정\n\n",
        "- 형상 내부 상하 관계 정상: `{}`\n".format(
            orientation["diagnosis_checks"]["geometry_internal_up_consistent"]
        ),
        "- 화면 도구의 축 기준 차이 가능성: `{}`\n".format(
            orientation["diagnosis_checks"]["viewer_axis_convention_may_differ"]
        ),
        "- Scene up 부호 문제 의심: `{}`\n".format(
            orientation["diagnosis_checks"]["scene_up_sign_suspect"]
        ),
        "- 바닥·천장 또는 corner 대응 문제 의심: `{}`\n\n".format(
            orientation["diagnosis_checks"][
                "floor_ceiling_or_corner_correspondence_suspect"
            ]
        ),
        "## Proper Rotation\n\n",
        "- 회전 각도: `{:.9g}도`\n".format(rotation["rotation_angle_deg"]),
        "- Determinant: `{:.12g}`\n".format(rotation["determinant"]),
        "- Up 정렬 오차: `{:.6g}`\n".format(rotation["up_alignment_error"]),
        "- 직교 오차: `{:.6g}`\n".format(rotation["orthogonality_error"]),
        "- 왕복 오차: `{:.6g}`\n\n".format(rotation["round_trip_error"]),
        "## Provisional Scale\n\n",
    ]
    for reference in scale["references"]:
        lines.append(
            "- `{}`: `{:.9g} m/scene unit`\n".format(
                reference["name"], reference["individual_meters_per_scene_unit"]
            )
        )
    lines.append("\n추천 배율을 적용했을 때의 기준별 오차:\n\n")
    for residual in scale["recommended_reference_residuals"]:
        lines.append(
            "- `{}`: `{:+.9g} m` (`{:+.4%}`)\n".format(
                residual["reference_name"],
                residual["signed_error_m"],
                residual["relative_error"],
            )
        )
    lines.extend(
        [
            "\n",
            "- 추천 추정기: `{}`\n".format(scale["recommended_estimator"]),
            "- 추천 단일 축척: `{:.9g} m/scene unit`\n".format(
                scale["recommended_meters_per_scene_unit"]
            ),
            "- 기준 간 상대 차이: `{:.4%}`\n\n".format(scale["relative_spread"]),
            "## 좌표 프레임 후보\n\n",
            "- 추천 원점 corner: `{}`\n".format(origin["recommended_corner_index"]),
            "- 추천 X축 edge: `{} → {}`\n".format(
                x_axis["recommended_start_corner"], x_axis["recommended_end_corner"]
            ),
            "- 추천 수평 방향: `{}`\n\n".format(
                x_axis["recommended_horizontal_direction"]
            ),
            "## 미해결 경고\n\n",
        ]
    )
    for warning in document["unresolved_warnings"]:
        lines.append("- {}\n".format(warning))
    lines.extend(
        [
            "\n## 생성 파일\n\n",
        ]
    )
    for name, value in document["generated_files"].items():
        lines.append("- `{}`: `{}`\n".format(name, value))
    _atomic_write(Path(path), "".join(lines))
