"""RFVisualizer Phase 2-B scenario and A/B experiment CLI."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List, Optional

from tools.sionna_smoke_test.environment import diagnose_environment
from tools.sionna_smoke_test.io_utils import write_json
from tools.sionna_smoke_test.main import configure_sionna_scene

from .config import load_experiment, load_scenario
from .experiment_runner import run_ab_experiment
from .material_resolver import inspect_all_scene_materials
from .scenario_builder import build_scenario, prepare_scenario, validation_summary
from .scene_composer import annotate_runtime_objects


LOGGER = logging.getLogger("sionna_scenario")


def _prepare_from_args(args: argparse.Namespace):
    document = load_scenario(args.scenario)
    markers = getattr(args, "markers", None)
    if markers is None:
        return prepare_scenario(document)
    return prepare_scenario(document, markers)


def command_validate(args: argparse.Namespace) -> int:
    prepared = _prepare_from_args(args)
    result = validation_summary(prepared)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["success"] else 2


def command_build(args: argparse.Namespace) -> int:
    failure = Path(args.output).expanduser().resolve() / "phase2b_failure.json"
    if failure.exists():
        failure.unlink()
    prepared = _prepare_from_args(args)
    manifest = build_scenario(prepared, args.output)
    environment = diagnose_environment()
    if environment.get("status") == "available":
        scene, _ = configure_sionna_scene(
            manifest["scene_xml"], prepared.settings, prepared.positions
        )
        manifest = annotate_runtime_objects(manifest, scene, Path(args.output))
        materials = inspect_all_scene_materials(
            scene, manifest, prepared.materials
        )
        write_json(Path(args.output) / "materials_resolved.json", materials)
        material_resolution = "verified_with_installed_sionna"
    else:
        material_resolution = "deferred_until_sionna_runtime"
    result = {
        "scenario_id": manifest["scenario_id"],
        "status": manifest["status"],
        "scene_xml": manifest["scene_xml"],
        "room_object_count": manifest["room_object_count"],
        "obstacle_object_count": manifest["obstacle_object_count"],
        "total_triangle_count": manifest["total_triangle_count"],
        "position_source": getattr(prepared, "position_source", "phase2a_config"),
        "position_count": len(getattr(prepared, "positions", [])),
        "material_resolution": material_resolution,
        "scenario_manifest": str(
            (Path(args.output).expanduser().resolve() / "scenario_manifest.json")
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_run_ab(args: argparse.Namespace) -> int:
    failure = Path(args.output).expanduser().resolve() / "phase2b_failure.json"
    if failure.exists():
        failure.unlink()
    result = run_ab_experiment(load_experiment(args.experiment), args.output)
    validation = result["validation"]
    coverage = result["coverage_comparison"]
    paths = result["path_comparison"]["rx_los"]
    summary = {
        "experiment_id": result["validation"].get(
            "experiment_id", "pnu_classroom_phase2b_ab"
        ),
        "overall_success": validation["overall_success"],
        "baseline_rx_los": paths["baseline"]["los_path_exists"],
        "variant_rx_los": paths["variant"]["los_path_exists"],
        "common_valid_cells": coverage["common_valid_cell_count"],
        "mean_delta_db": coverage["mean_delta_db"],
        "mean_absolute_delta_db": coverage["mean_absolute_delta_db"],
        "maximum_absolute_delta_db": coverage["maximum_absolute_delta_db"],
        "output": str(Path(args.output).expanduser().resolve()),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if validation["overall_success"] else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="독립 Proxy Obstacle Layer와 Sionna RT A/B 실험을 실행합니다."
    )
    parser.add_argument("--verbose", action="store_true", help="상세 로그를 표시합니다.")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Scenario schema와 geometry를 검증합니다.")
    validate.add_argument("--scenario", type=Path, required=True, help="Scenario YAML")
    validate.add_argument(
        "--markers", type=Path, help="최신 AP/TX/RX 위치를 담은 실험 Marker JSON"
    )
    validate.set_defaults(handler=command_validate)
    build = commands.add_parser("build", help="Room과 obstacle을 독립 shape로 내보냅니다.")
    build.add_argument("--scenario", type=Path, required=True, help="Scenario YAML")
    build.add_argument(
        "--markers", type=Path, help="최신 AP/TX/RX 위치를 담은 실험 Marker JSON"
    )
    build.add_argument("--output", type=Path, required=True, help="Scenario 결과 폴더")
    build.set_defaults(handler=command_build)
    run_ab = commands.add_parser("run-ab", help="Empty baseline과 obstacle variant를 비교합니다.")
    run_ab.add_argument("--experiment", type=Path, required=True, help="A/B experiment YAML")
    run_ab.add_argument("--output", type=Path, required=True, help="A/B 결과 폴더")
    run_ab.set_defaults(handler=command_run_ab)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    try:
        return int(args.handler(args))
    except (ValueError, RuntimeError, OSError) as exc:
        LOGGER.error("%s", exc)
        output = getattr(args, "output", None)
        if output is not None:
            try:
                write_json(
                    Path(output).expanduser().resolve() / "phase2b_failure.json",
                    {
                        "status": "failure",
                        "success": False,
                        "exception_type": exc.__class__.__name__,
                        "reason": str(exc),
                        "reproduction_command": " ".join(sys.argv),
                    },
                )
            except Exception:
                LOGGER.exception("실패 진단 JSON도 저장하지 못했습니다.")
        return 2
    except Exception:
        LOGGER.exception("예상하지 못한 Phase 2-B 오류가 발생했습니다.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
