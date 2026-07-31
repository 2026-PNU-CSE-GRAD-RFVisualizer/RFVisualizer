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
from .candidate_library import instantiate_candidate, load_candidate_library
from .coordinate_bridge import PlacementCoordinateBridge
from .editor_config import load_editor_config
from .editor_core import EditorCore
from .editor_state import EditorState
from .exporter import export_resolved_outputs
from .reference_loader import (
    DEFAULT_PGSR_MESH_PREVIEW_TRIANGLES,
    build_mesh_preview_cache,
    load_pgsr_output_mesh_geometry,
    load_point_cloud_geometry,
    load_reference_geometry,
    mesh_preview_cache_is_current,
)
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


def _pgsr_mesh_preview_path(args) -> Optional[Path]:
    source = getattr(args, "pgsr_output_mesh", None)
    if not source:
        return None
    configured = getattr(args, "pgsr_output_mesh_preview", None)
    if configured:
        return Path(configured).expanduser().resolve()
    output = getattr(args, "output", None)
    if not output:
        return None
    cache_root = Path(output).expanduser().resolve()
    if getattr(args, "command", None) == "export-preview":
        cache_root = cache_root.parent
    return (
        cache_root / "cache" / "pgsr_output_mesh_preview.ply"
    )


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
    marker_path = getattr(args, "markers", None)
    marker_document = None
    marker_source_path = None
    if marker_path:
        marker_source_path = Path(marker_path).expanduser().resolve()
        if not marker_source_path.is_file():
            raise ValueError("TX/RX JSON을 찾을 수 없습니다: {}".format(marker_source_path))
        try:
            marker_document = json.loads(marker_source_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("TX/RX JSON을 읽을 수 없습니다: {}".format(exc)) from exc
        if not isinstance(marker_document, dict):
            raise ValueError("TX/RX JSON 최상위 값은 객체여야 합니다.")
    state = EditorState(
        document,
        source_path=scenario_path,
        marker_document=marker_document,
        marker_source_path=marker_source_path,
    )
    candidates = load_candidate_library(getattr(args, "candidates", DEFAULT_CANDIDATES))
    configured_output = (
        getattr(args, "output", None) or PROJECT_ROOT / "outputs/proxy_placement"
    )
    output = Path(configured_output).resolve()
    core = EditorCore(scene, state, candidates, output)
    if marker_document is not None:
        ap_template = next((value for value in candidates if value.id == "ap_tx"), None)
        if ap_template is None and marker_document.get("tx"):
            raise ValueError("AP/TX Candidate가 없어 기존 TX를 통합할 수 없습니다.")
        existing = {str(value.get("id")): value for value in state.obstacles}
        for transmitter in marker_document.get("tx", []):
            transmitter_id = str(transmitter.get("id", "")).strip()
            if not transmitter_id:
                raise ValueError("TX id가 비어 있습니다.")
            obstacle = existing.get(transmitter_id)
            if obstacle is None:
                obstacle = instantiate_candidate(
                    ap_template, transmitter_id, scene.containment
                )
                state.add_object(obstacle)
                # EditorState owns a deep copy.  Continue editing that stored
                # object so the marker position is visible in the GUI.
                obstacle = state.get_object(transmitter_id)
                existing[transmitter_id] = obstacle
            obstacle["display_name"] = str(
                transmitter.get("name", obstacle.get("display_name", transmitter_id))
            )
            obstacle["enabled"] = True
            position = transmitter.get("position_m", [])
            if not isinstance(position, list) or len(position) != 3:
                raise ValueError("TX position_m에는 X/Y/Z 숫자 3개가 필요합니다.")
            obstacle["geometry"]["anchor"] = {"mode": "center"}
            obstacle["geometry"]["position_m"] = {
                axis: float(position[index])
                for index, axis in enumerate(("x", "y", "z"))
            }
            obstacle["rf_transmitter"] = {
                "frequency_hz": float(transmitter.get("frequency_hz")),
                "power_dbm": float(transmitter.get("power_dbm")),
            }
        state.dirty = False
    point_cloud = getattr(args, "point_cloud", None)
    pgsr_output_mesh = getattr(args, "pgsr_output_mesh", None)
    reference_mesh = getattr(args, "reference_mesh", None)
    if point_cloud or pgsr_output_mesh or reference_mesh:
        bridge = PlacementCoordinateBridge.from_calibration(scene.calibration)
    if point_cloud:
        LOGGER.info("Point Cloud를 읽는 중: %s", point_cloud)
        core.point_cloud = load_point_cloud_geometry(
            point_cloud,
            getattr(args, "point_cloud_coordinate_space", "scene"),
            bridge,
        )
        LOGGER.info(
            "Point Cloud 준비 완료: points=%d, discarded_nonfinite=%d, display_decimated=%s",
            len(core.point_cloud.vertices_metric),
            core.point_cloud.discarded_nonfinite_points,
            core.point_cloud.display_decimated,
        )
    elif reference_mesh:
        LOGGER.warning(
            "--reference-mesh는 이전 호환 인자입니다. --point-cloud를 사용하세요."
        )
        core.point_cloud = load_reference_geometry(
            reference_mesh,
            getattr(args, "reference_coordinate_space", "scene"),
            bridge,
        )
    if pgsr_output_mesh:
        full_resolution = bool(
            getattr(args, "pgsr_output_mesh_full_resolution", False)
        )
        preview_path = None if full_resolution else _pgsr_mesh_preview_path(args)
        LOGGER.info("PGSR Output Mesh를 읽는 중: %s", pgsr_output_mesh)
        core.pgsr_output_mesh = load_pgsr_output_mesh_geometry(
            pgsr_output_mesh,
            getattr(args, "pgsr_output_mesh_coordinate_space", "scene"),
            bridge,
            preview_path=preview_path,
            maximum_triangles=DEFAULT_PGSR_MESH_PREVIEW_TRIANGLES,
            full_resolution=full_resolution,
        )
        LOGGER.info(
            "PGSR Output Mesh 준비 완료: vertices=%d, faces=%d, preview=%s",
            len(core.pgsr_output_mesh.vertices_metric),
            len(core.pgsr_output_mesh.faces),
            core.pgsr_output_mesh.preview_path,
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


def command_prepare_pgsr_mesh_preview(args) -> int:
    metadata = build_mesh_preview_cache(
        args.source,
        args.output,
        maximum_triangles=args.maximum_triangles,
    )
    print(json.dumps({"success": True, **metadata}, ensure_ascii=False, indent=2))
    return 0


def _prepare_pgsr_mesh_preview_subprocess(args) -> None:
    source = getattr(args, "pgsr_output_mesh", None)
    if not source:
        return
    if getattr(args, "pgsr_output_mesh_full_resolution", False):
        LOGGER.info("PGSR Output Mesh 원본 해상도 모드: 단순화 캐시를 사용하지 않습니다.")
        return
    preview = _pgsr_mesh_preview_path(args)
    if preview is None:
        raise ValueError(
            "PGSR Output Mesh에는 --output 또는 --pgsr-output-mesh-preview가 필요합니다."
        )
    if mesh_preview_cache_is_current(
        source, preview, DEFAULT_PGSR_MESH_PREVIEW_TRIANGLES
    ):
        LOGGER.info("표시용 PGSR Mesh 캐시를 재사용합니다: %s", preview)
        return
    LOGGER.info(
        "표시용 PGSR Mesh 캐시를 별도 프로세스에서 준비합니다. "
        "첫 실행에는 약 1분이 걸릴 수 있습니다."
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.proxy_placement_editor.main",
            "prepare-pgsr-mesh-preview",
            "--source",
            str(Path(source).expanduser().resolve()),
            "--output",
            str(preview),
            "--maximum-triangles",
            str(DEFAULT_PGSR_MESH_PREVIEW_TRIANGLES),
        ],
        check=False,
    )
    if completed.returncode != 0:
        if completed.returncode < 0:
            raise RuntimeError(
                "표시용 PGSR Mesh 생성 프로세스가 signal {}로 종료되었습니다.".format(
                    -completed.returncode
                )
            )
        raise RuntimeError(
            "표시용 PGSR Mesh 생성에 실패했습니다 (exit code {}).".format(
                completed.returncode
            )
        )


def command_edit(args) -> int:
    # Fail before loading a multi-million-triangle reference when no GUI is possible.
    ensure_gui_display()
    if os.environ.get(GUI_WORKER_ENV) == "1":
        return _run_editor_in_process(args)

    _prepare_pgsr_mesh_preview_subprocess(args)

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
    _prepare_pgsr_mesh_preview_subprocess(args)
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
        "--point-cloud", type=Path, help="표시할 PGSR Gaussian Point Cloud PLY"
    )
    parser.add_argument(
        "--point-cloud-coordinate-space",
        choices=("scene", "metric"),
        default="scene",
    )
    parser.add_argument(
        "--pgsr-output-mesh", type=Path, help="표시할 PGSR Output Mesh OBJ/PLY"
    )
    parser.add_argument(
        "--pgsr-output-mesh-coordinate-space",
        choices=("scene", "metric"),
        default="scene",
    )
    parser.add_argument(
        "--pgsr-output-mesh-preview",
        type=Path,
        help="선택적 표시용 단순화 Mesh 캐시 PLY 경로",
    )
    parser.add_argument(
        "--pgsr-output-mesh-full-resolution",
        action="store_true",
        help="표시 캐시를 건너뛰고 PGSR Output Mesh 원본 삼각형을 모두 읽음",
    )
    parser.add_argument(
        "--reference-mesh",
        type=Path,
        help="이전 호환용 표시 reference; 새 실행에서는 --point-cloud 사용",
    )
    parser.add_argument(
        "--reference-coordinate-space", choices=("scene", "metric"), default="scene"
    )
    parser.add_argument(
        "--markers",
        type=Path,
        help="같은 창에서 편집하고 함께 저장할 TX/RX JSON",
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
    prepare_mesh = commands.add_parser(
        "prepare-pgsr-mesh-preview",
        help="대형 PGSR Output Mesh의 표시용 단순화 캐시를 생성합니다.",
    )
    prepare_mesh.add_argument("--source", type=Path, required=True)
    prepare_mesh.add_argument("--output", type=Path, required=True)
    prepare_mesh.add_argument(
        "--maximum-triangles",
        type=int,
        default=DEFAULT_PGSR_MESH_PREVIEW_TRIANGLES,
    )
    prepare_mesh.set_defaults(handler=command_prepare_pgsr_mesh_preview)
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
