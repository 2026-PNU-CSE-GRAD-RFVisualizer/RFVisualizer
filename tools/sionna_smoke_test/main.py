"""Phase 2-A Sionna RT Empty-Room Smoke Test 독립 명령줄 도구."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Optional

import numpy as np

from . import __version__
from .config import SmokeTestConfigError, load_config
from .coordinate_bridge import CoordinateBridge, CoordinateBridgeError
from .coverage_test import CoverageTestError, run_coverage_solver
from .environment import diagnose_environment
from .exporter import (
    SmokeTestExportError,
    export_coverage,
    export_resolved_configuration,
    export_scene_preview,
)
from .io_utils import SmokeTestIOError, write_json
from .materials import resolve_materials
from .metric_scene_loader import MetricSceneError, load_metric_scene
from .path_test import PathTestError, run_path_tests
from .placement import PlacementError, resolve_positions
from .report import write_report
from .scene_exporter import SceneExportError, export_scene
from .validator import build_validation


LOGGER = logging.getLogger("sionna_smoke_test")


class SionnaUnavailableError(RuntimeError):
    """현재 환경에서 실제 Sionna solver를 실행할 수 없을 때 발생한다."""


def _load_settings(config_path: Path):
    config = load_config(config_path)
    return config, config["sionna_smoke_test"]


def command_check_environment(args: argparse.Namespace) -> int:
    result = diagnose_environment()
    if args.output is not None:
        write_json(Path(args.output), result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "available" else 2


def command_validate_scene(args: argparse.Namespace) -> int:
    _, settings = _load_settings(args.config)
    metric_scene = load_metric_scene(settings)
    room, positions, warnings = resolve_positions(settings, metric_scene.metric_metadata)
    with tempfile.TemporaryDirectory(prefix="rfvisualizer_sionna_validate_") as temporary:
        manifest = export_scene(metric_scene, settings, Path(temporary))
    result = {
        "metric_input_valid": True,
        "scene_conversion_valid": manifest["conversion_validation"]["success"],
        "position_count": len(positions),
        "positions": positions,
        "warnings": warnings,
        "bounds": manifest["source_statistics"]["bounds"],
        "triangle_count": manifest["source_statistics"]["triangle_count"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def configure_sionna_scene(scene_xml: str, settings, positions):
    from sionna.rt import PlanarArray, Receiver, Transmitter, load_scene

    start = time.perf_counter()
    scene = load_scene(scene_xml, merge_shapes=False)
    load_time = time.perf_counter() - start
    scene.frequency = float(settings["scene"]["carrier_frequency_hz"])
    antenna = settings["antenna"]
    scene.tx_array = PlanarArray(
        num_rows=1,
        num_cols=1,
        pattern=antenna["pattern"],
        polarization=antenna["polarization"],
    )
    scene.rx_array = PlanarArray(
        num_rows=1,
        num_cols=1,
        pattern=antenna["pattern"],
        polarization=antenna["polarization"],
    )
    for value in positions:
        if value["kind"] == "transmitter":
            scene.add(
                Transmitter(
                    name=value["name"],
                    position=value["resolved_position_m"],
                    power_dbm=float(settings["transmitter"].get("power_dbm", 20.0)),
                )
            )
        else:
            scene.add(
                Receiver(name=value["name"], position=value["resolved_position_m"])
            )
    tx = next(iter(scene.transmitters.values()))
    if scene.receivers:
        tx.look_at(next(iter(scene.receivers.values())))
    return scene, load_time


# Backwards-compatible private name used by the original Phase 2-A implementation.
_configure_sionna_scene = configure_sionna_scene


def command_run(args: argparse.Namespace) -> int:
    config, settings = _load_settings(args.config)
    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    stale_failure = output / "smoke_test_failure.json"
    if stale_failure.exists():
        stale_failure.unlink()
    total_start = time.perf_counter()
    environment_start = time.perf_counter()
    environment = diagnose_environment()
    environment_time = time.perf_counter() - environment_start
    write_json(output / "environment.json", environment)
    if environment["status"] != "available":
        raise SionnaUnavailableError(
            "Sionna RT를 실행할 수 없습니다: {}".format(environment.get("reason"))
        )

    metric_scene = load_metric_scene(settings)
    export_start = time.perf_counter()
    manifest = export_scene(metric_scene, settings, output)
    scene_export_time = time.perf_counter() - export_start
    room, positions, placement_warnings = resolve_positions(
        settings, metric_scene.metric_metadata
    )
    bridge = CoordinateBridge.from_calibration(metric_scene.calibration)
    metric_position_array = np.asarray(
        [value["resolved_position_m"] for value in positions], dtype=float
    )
    original_scene_points = bridge.metric_to_scene(metric_scene.vertices)
    bridge_validation = bridge.validation_report(
        metric_position_array, original_scene_points
    )
    resolved_documents = export_resolved_configuration(
        settings,
        positions,
        bridge,
        bridge_validation,
        placement_warnings,
        output,
    )
    scene, scene_load_time = configure_sionna_scene(
        manifest["scene_xml"], settings, positions
    )
    materials = resolve_materials(scene, manifest)
    write_json(output / "materials_resolved.json", materials)
    path_results = run_path_tests(scene, settings, positions, output)
    coverage_result = run_coverage_solver(scene, settings, room, positions)
    coverage_files = export_coverage(coverage_result, bridge, positions, output)
    if settings["output"]["save_scene_preview"]:
        scene_preview = export_scene_preview(metric_scene, positions, output)
    else:
        scene_preview = None
    warnings = [
        "PROVISIONAL SCALE — NOT PHYSICALLY VALIDATED",
        "현재 재질은 실제 강의실 측정값이 아닌 Sionna ITU concrete preset입니다.",
    ]
    warnings.extend(placement_warnings)
    reflection_warning = path_results["reflection"]["validation"].get("warning")
    if reflection_warning:
        warnings.append(reflection_warning)
    performance = {
        "environment_diagnosis": environment_time,
        "scene_export": scene_export_time,
        "sionna_scene_load": scene_load_time,
        "los_path_solve": path_results["los"]["solve_time_seconds"],
        "reflection_path_solve": path_results["reflection"]["solve_time_seconds"],
        "coverage_solve": coverage_result["metadata"]["solve_time_seconds"],
    }
    performance["total_before_report"] = time.perf_counter() - total_start
    validation = build_validation(
        environment,
        manifest,
        positions,
        bridge_validation,
        path_results,
        coverage_result,
        performance,
        warnings,
    )
    files = {
        "environment_json": str((output / "environment.json").resolve()),
        "resolved_config_yaml": str((output / "resolved_config.yaml").resolve()),
        "resolved_positions_json": str((output / "resolved_positions.json").resolve()),
        "resolved_positions_scene_json": str(
            (output / "resolved_positions_scene.json").resolve()
        ),
        "materials_resolved_json": str(
            (output / "materials_resolved.json").resolve()
        ),
        "scene_manifest_json": str((output / "scene_manifest.json").resolve()),
        "scene_xml": manifest["scene_xml"],
        "scene_preview_png": scene_preview,
        "paths_los_json": str((output / "paths" / "paths_los.json").resolve()),
        "paths_los_csv": str((output / "paths" / "paths_los.csv").resolve()),
        "paths_reflection_json": str(
            (output / "paths" / "paths_reflection.json").resolve()
        ),
        "paths_reflection_csv": str(
            (output / "paths" / "paths_reflection.csv").resolve()
        ),
        **coverage_files,
        "smoke_test_validation_json": str(
            (output / "smoke_test_validation.json").resolve()
        ),
        "report_markdown": str(
            (output / "PHASE2A_SMOKE_TEST_REPORT.md").resolve()
        ),
    }
    validation["algorithm"] = {
        "name": "rfvisualizer_sionna_empty_room_smoke_test",
        "version": __version__,
    }
    validation["files"] = files
    write_json(output / "smoke_test_validation.json", validation)
    write_report(
        output / "PHASE2A_SMOKE_TEST_REPORT.md",
        environment,
        manifest,
        materials,
        resolved_documents["metric"],
        validation,
        files,
    )
    LOGGER.info(
        "Smoke Test %s: LoS error %.3g m, reflections %d, coverage valid %.1f%%",
        "통과" if validation["overall_success"] else "실패",
        validation["los_validation"]["distance_error_m"],
        validation["reflection_validation"]["reflection_path_count"],
        100.0 * validation["coverage_validation"]["valid_ratio_of_inside"],
    )
    return 0 if validation["overall_success"] else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="미터 단위 Room Envelope의 Sionna RT 연결을 검증합니다."
    )
    parser.add_argument("--verbose", action="store_true", help="상세 로그를 표시합니다.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    environment = subparsers.add_parser(
        "check-environment", help="Sionna·Mitsuba·CUDA 설치 상태를 확인합니다."
    )
    environment.add_argument("--output", type=Path, help="선택적 environment.json 경로")
    environment.set_defaults(handler=command_check_environment)
    validate = subparsers.add_parser(
        "validate-scene", help="Metric 입력, 장면 변환과 TX/RX 배치를 검증합니다."
    )
    validate.add_argument("--config", type=Path, required=True, help="Smoke Test YAML")
    validate.set_defaults(handler=command_validate_scene)
    run = subparsers.add_parser("run", help="전체 Sionna RT Smoke Test를 실행합니다.")
    run.add_argument("--config", type=Path, required=True, help="Smoke Test YAML")
    run.add_argument("--output", type=Path, required=True, help="결과 폴더")
    run.set_defaults(handler=command_run)
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
    except (
        SmokeTestConfigError,
        SmokeTestIOError,
        MetricSceneError,
        SceneExportError,
        PlacementError,
        CoordinateBridgeError,
        PathTestError,
        CoverageTestError,
        SmokeTestExportError,
        SionnaUnavailableError,
        ValueError,
    ) as exc:
        LOGGER.error("%s", exc)
        if getattr(args, "output", None) is not None and args.command == "run":
            try:
                write_json(
                    Path(args.output).expanduser().resolve() / "smoke_test_failure.json",
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
        LOGGER.exception("예상하지 못한 Smoke Test 오류가 발생했습니다.")
        if getattr(args, "output", None) is not None and args.command == "run":
            try:
                write_json(
                    Path(args.output).expanduser().resolve() / "smoke_test_failure.json",
                    {
                        "status": "failure",
                        "success": False,
                        "exception_type": "UnexpectedError",
                        "reason": "자세한 원인은 stderr traceback을 확인하세요.",
                        "reproduction_command": " ".join(sys.argv),
                    },
                )
            except Exception:
                LOGGER.exception("실패 진단 JSON도 저장하지 못했습니다.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
