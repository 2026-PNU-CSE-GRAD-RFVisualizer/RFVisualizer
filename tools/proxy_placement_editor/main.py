"""Phase 2-C interactive placement, headless validation, and preview CLI."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional

from tools.sionna_scenario.config import validate_scenario
from tools.sionna_smoke_test.config import load_config as load_phase2a_config
from tools.sionna_smoke_test.io_utils import write_json

from .app import ensure_gui_display, run_editor
from .candidate_library import load_candidate_library
from .coordinate_bridge import PlacementCoordinateBridge
from .editor_config import load_editor_config
from .editor_core import EditorCore
from .editor_state import EditorState
from .exporter import export_resolved_outputs
from .reference_loader import load_reference_geometry
from .scenario_io import load_editor_scenario
from .scene_loader import load_placement_scene


LOGGER = logging.getLogger("proxy_placement_editor")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CANDIDATES = PROJECT_ROOT / "configs/proxy_editor/pnu_classroom_candidates.yaml"
DEFAULT_EDITOR_CONFIG = PROJECT_ROOT / "configs/proxy_editor/pnu_classroom_editor.yaml"
GUI_WORKER_ENV = "RFVIS_PROXY_EDITOR_GUI_WORKER"
SOFTWARE_RENDERING_ENV = "RFVIS_PROXY_EDITOR_SOFTWARE_RENDERING"
GUI_PYTHON_ENV = "RFVIS_PROXY_EDITOR_GUI_PYTHON"
DEFAULT_GUI_RUNTIME = PROJECT_ROOT / ".venv/proxy-placement-editor"
COMPATIBLE_OPEN3D_PACKAGE = "open3d-cpu==0.18.0"
NATIVE_GUI_CRASH_SIGNALS = {6, 11}


def _project_path(value: str) -> Path:
    path = Path(value).expanduser()
    return (PROJECT_ROOT / path).resolve() if not path.is_absolute() else path.resolve()


def _inferred_room_inputs(document: Dict) -> Dict[str, Path]:
    checked = validate_scenario(deepcopy(document))
    phase2a = load_phase2a_config(Path(checked["scenario"]["_phase2a_config_path"]))
    values = phase2a["sionna_smoke_test"]["input"]
    return {
        "room_obj": _project_path(values["metric_obj"]),
        "room_json": _project_path(values["metric_json"]),
        "calibration": _project_path(values["calibration_json"]),
    }


def _create_core(args) -> EditorCore:
    scenario_path = Path(args.scenario).expanduser().resolve()
    document = load_editor_scenario(scenario_path)
    inferred = _inferred_room_inputs(document)
    room_obj = (
        Path(args.room_obj).resolve()
        if getattr(args, "room_obj", None)
        else inferred["room_obj"]
    )
    room_json = (
        Path(args.room_json).resolve()
        if getattr(args, "room_json", None)
        else inferred["room_json"]
    )
    calibration = (
        Path(args.calibration).resolve()
        if getattr(args, "calibration", None)
        else inferred["calibration"]
    )
    scene = load_placement_scene(room_json, calibration, room_obj=room_obj)
    state = EditorState(document, source_path=scenario_path)
    candidates = load_candidate_library(getattr(args, "candidates", DEFAULT_CANDIDATES))
    configured_output = (
        getattr(args, "output", None) or PROJECT_ROOT / "outputs/proxy_placement"
    )
    output = Path(configured_output).resolve()
    core = EditorCore(scene, state, candidates, output)
    reference_mesh = getattr(args, "reference_mesh", None)
    if reference_mesh:
        LOGGER.info("Reference geometry를 읽는 중: %s", reference_mesh)
        bridge = PlacementCoordinateBridge.from_calibration(scene.calibration)
        core.reference = load_reference_geometry(
            reference_mesh,
            getattr(args, "reference_coordinate_space", "scene"),
            bridge,
        )
        LOGGER.info(
            "Reference geometry 준비 완료: kind=%s, vertices=%d, faces=%d, display_decimated=%s",
            core.reference.kind,
            len(core.reference.vertices_metric),
            len(core.reference.faces),
            core.reference.display_decimated,
        )
    return core


def _software_rendering_environment() -> Dict[str, str]:
    environment = dict(os.environ)
    environment[GUI_WORKER_ENV] = "1"
    environment[SOFTWARE_RENDERING_ENV] = "1"
    environment["LIBGL_ALWAYS_SOFTWARE"] = "true"
    mesa_glx = Path("/usr/lib/x86_64-linux-gnu/libGLX_mesa.so.0")
    if mesa_glx.is_file():
        preload = environment.get("LD_PRELOAD", "")
        entries = [entry for entry in preload.split(":") if entry]
        if str(mesa_glx) not in entries:
            entries.insert(0, str(mesa_glx))
        environment["LD_PRELOAD"] = ":".join(entries)
    return environment


def _runtime_python(runtime_dir: Path) -> Path:
    directory = Path(runtime_dir).expanduser().absolute()
    return directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _compatible_gui_python() -> Optional[Path]:
    override = os.environ.get(GUI_PYTHON_ENV)
    python = (
        Path(override).expanduser().absolute()
        if override
        else _runtime_python(DEFAULT_GUI_RUNTIME)
    )
    return python if python.is_file() else None


def _run_editor_worker(
    args, software_rendering: bool, python_executable: Optional[Path] = None
) -> int:
    environment = (
        _software_rendering_environment()
        if software_rendering
        else dict(os.environ)
    )
    environment[GUI_WORKER_ENV] = "1"
    command = [
        str(python_executable or sys.executable),
        "-m",
        "tools.proxy_placement_editor.main",
        *args._raw_argv,
    ]
    return int(subprocess.run(command, env=environment, check=False).returncode)


def _run_editor_in_process(args) -> int:
    core = _create_core(args)
    run_editor(core, load_editor_config(args.editor_config), experiment=args.experiment)
    return 0


def _native_signal(return_code: int) -> Optional[int]:
    if return_code >= 0:
        return None
    return -return_code


def _is_same_python(left: Path, right: Path) -> bool:
    # venv의 python은 원본 interpreter symlink일 수 있으므로 resolve()하지 않는다.
    return os.path.abspath(str(left)) == os.path.abspath(str(right))


def command_setup_gui_runtime(args) -> int:
    runtime_dir = Path(args.runtime_dir).expanduser().resolve()
    python = _runtime_python(runtime_dir)
    LOGGER.info("편집기 전용 GUI runtime을 준비합니다: %s", runtime_dir)
    if not python.is_file():
        subprocess.run(
            [
                sys.executable,
                "-m",
                "venv",
                "--system-site-packages",
                str(runtime_dir),
            ],
            check=True,
        )
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--upgrade",
            "--no-deps",
            COMPATIBLE_OPEN3D_PACKAGE,
        ],
        check=True,
    )
    check = subprocess.run(
        [
            str(python),
            "-c",
            "import open3d; print(open3d.__version__)",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    version = check.stdout.strip()
    print(
        json.dumps(
            {
                "success": True,
                "runtime_dir": str(runtime_dir),
                "python": str(python),
                "open3d_version": version,
                "inherits_pgsr_packages": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_edit(args) -> int:
    # Fail before loading a multi-million-triangle reference when no GUI is possible.
    ensure_gui_display()
    if os.environ.get(GUI_WORKER_ENV) == "1":
        return _run_editor_in_process(args)

    software = bool(args.software_rendering)
    compatible_python = _compatible_gui_python()
    if compatible_python and not _is_same_python(compatible_python, Path(sys.executable)):
        LOGGER.info(
            "RustDesk/XWayland 호환 GUI runtime을 사용합니다: %s (%s)",
            compatible_python,
            COMPATIBLE_OPEN3D_PACKAGE,
        )
        compatible_code = _run_editor_worker(
            args,
            software_rendering=software,
            python_executable=compatible_python,
        )
        if compatible_code >= 0:
            return compatible_code
        compatible_signal = _native_signal(compatible_code)
        if compatible_signal not in NATIVE_GUI_CRASH_SIGNALS:
            return 128 + int(compatible_signal or 0)
        LOGGER.warning(
            "호환 GUI runtime이 signal %d로 종료되어 현재 Python runtime을 시도합니다.",
            compatible_signal,
        )

    if software:
        LOGGER.info("Open3D GUI를 Mesa 소프트웨어 렌더링으로 시작합니다.")
    return_code = _run_editor_worker(args, software_rendering=software)
    if return_code >= 0:
        return return_code

    signal_number = int(_native_signal(return_code) or 0)
    if signal_number not in NATIVE_GUI_CRASH_SIGNALS:
        return 128 + signal_number
    if not software:
        LOGGER.warning(
            "Open3D GPU GUI가 signal %d로 종료되었습니다. "
            "Mesa 소프트웨어 렌더링으로 한 번 다시 시도합니다.",
            signal_number,
        )
        retry_code = _run_editor_worker(args, software_rendering=True)
        if retry_code >= 0:
            return retry_code
        signal_number = -retry_code
    raise RuntimeError(
        "Open3D GUI가 native signal {}로 종료되었습니다. "
        "현재 Open3D 0.19와 RustDesk/XWayland 조합에서는 창 생성 충돌이 확인되었습니다. "
        "먼저 `python -m tools.proxy_placement_editor.main setup-gui-runtime`을 "
        "실행하거나 GNOME의 Ubuntu on Xorg 세션을 사용하세요.".format(signal_number)
    )


def _console_report(report: Dict) -> Dict:
    value = deepcopy(report)
    for record in value.get("objects", []):
        for key in ("metric_vertices", "scene_vertices", "faces", "source"):
            record.pop(key, None)
        validation = record.get("phase2b_validation")
        if validation:
            validation.get("containment", {}).pop("vertex_inspections", None)
    return value


def command_validate(args) -> int:
    core = _create_core(args)
    report = core.validate()
    if args.output:
        export_resolved_outputs(core.state, report, args.output, core.commands.log)
    print(json.dumps(_console_report(report), ensure_ascii=False, indent=2))
    return 0 if report["success"] else 2


def command_export_preview(args) -> int:
    core = _create_core(args)
    files = core.export_preview(
        args.output, include_reference=not args.exclude_reference
    )
    print(json.dumps({"success": True, "files": files}, ensure_ascii=False, indent=2))
    return 0


def _common_inputs(parser, require_room=False):
    parser.add_argument(
        "--scenario", type=Path, required=True, help="기존 Phase 2-B scenario YAML"
    )
    parser.add_argument(
        "--room-obj",
        type=Path,
        required=require_room,
        help="Metric Room OBJ; 생략 시 Phase 2-A config에서 읽음",
    )
    parser.add_argument(
        "--room-json", type=Path, required=require_room, help="Metric Room JSON"
    )
    parser.add_argument(
        "--calibration",
        type=Path,
        required=require_room,
        help="Phase 1.5-C calibration JSON",
    )
    parser.add_argument(
        "--candidates",
        type=Path,
        default=DEFAULT_CANDIDATES,
        help="Candidate library YAML",
    )
    parser.add_argument(
        "--reference-mesh", type=Path, help="표시 전용 OBJ/PLY reference"
    )
    parser.add_argument(
        "--reference-coordinate-space", choices=("scene", "metric"), default="scene"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Metric Room에서 Proxy Obstacle을 배치하고 Phase 2-B scenario를 작성합니다."
    )
    parser.add_argument("--verbose", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    edit = commands.add_parser(
        "edit", help="Open3D interactive placement editor를 엽니다."
    )
    _common_inputs(edit, require_room=True)
    edit.add_argument(
        "--output", type=Path, required=True, help="Editor state/autosave/output 폴더"
    )
    edit.add_argument("--editor-config", type=Path, default=DEFAULT_EDITOR_CONFIG)
    edit.add_argument(
        "--experiment", type=Path, help="GUI Run A/B 버튼에서 사용할 experiment YAML"
    )
    edit.add_argument(
        "--software-rendering",
        action="store_true",
        help="GPU GUI 대신 Mesa CPU 렌더링으로 시작",
    )
    edit.set_defaults(handler=command_edit)
    setup_gui = commands.add_parser(
        "setup-gui-runtime",
        help="RustDesk/XWayland용 Open3D 0.18 CPU runtime을 별도 .venv에 설치합니다.",
    )
    setup_gui.add_argument(
        "--runtime-dir",
        type=Path,
        default=DEFAULT_GUI_RUNTIME,
        help="편집기 전용 virtual environment 폴더",
    )
    setup_gui.set_defaults(handler=command_setup_gui_runtime)
    validate = commands.add_parser("validate", help="GUI 없이 scenario를 검증합니다.")
    _common_inputs(validate, require_room=False)
    validate.add_argument(
        "--output", type=Path, help="선택적 resolved metadata 출력 폴더"
    )
    validate.set_defaults(handler=command_validate)
    preview = commands.add_parser(
        "export-preview", help="GUI 없이 PNG/OBJ/PLY preview를 생성합니다."
    )
    _common_inputs(preview, require_room=False)
    preview.add_argument("--output", type=Path, required=True, help="Preview 출력 폴더")
    preview.add_argument(
        "--exclude-reference",
        action="store_true",
        help="Preview 이미지에서 reference geometry 제외",
    )
    preview.set_defaults(handler=command_export_preview)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    raw_argv = list(argv) if argv is not None else list(sys.argv[1:])
    args = parser.parse_args(raw_argv)
    args._raw_argv = raw_argv
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    try:
        return int(args.handler(args))
    except (ValueError, RuntimeError, OSError) as exc:
        LOGGER.error("%s", exc)
        output = getattr(args, "output", None)
        if output:
            try:
                write_json(
                    Path(output).expanduser().resolve() / "phase2c_failure.json",
                    {
                        "status": "failure",
                        "success": False,
                        "exception_type": exc.__class__.__name__,
                        "reason": str(exc),
                        "reproduction_command": " ".join(sys.argv),
                    },
                )
            except Exception:
                LOGGER.exception("Phase 2-C failure JSON도 저장하지 못했습니다.")
        return 2
    except Exception:
        LOGGER.exception("예상하지 못한 Phase 2-C 오류가 발생했습니다.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
