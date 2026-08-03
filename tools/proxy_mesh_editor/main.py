"""Proxy Mesh Phase 1 명령줄 실행 진입점."""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import __version__
from .calibration.preflight import run_preflight
from .calibration.preflight_config import load_preflight_config
from .calibration.preview_exporter import CalibrationPreviewError
from .calibration.report import CalibrationReportError
from .calibration.metric_calibration import run_metric_calibration
from .calibration.metric_config import load_metric_config
from .calibration.metric_exporter import MetricExportError
from .calibration.metric_metadata import MetricMetadataError
from .config import load_config, normalize_vector
from .envelope.builder import build_room_envelope
from .envelope.candidate_loader import load_envelope_candidates
from .envelope.config import load_envelope_config, load_partial_envelope_config
from .envelope.exporter import EnvelopeExportError
from .envelope.report import write_envelope_outputs
from .envelope.validator import validate_envelope
from .export.obj_exporter import export_obj_bundle
from .export.preview_exporter import (
    PreviewExportError,
    write_preview,
    write_wall_preview,
)
from .geometry.normal_analyzer import write_normal_analysis_outputs
from .geometry.plane_extractor import extract_planes
from .geometry.preprocessing import preprocess_point_cloud
from .geometry.wall_extractor import extract_wall_planes
from .io.metadata_io import MetadataError, read_json, write_json
from .io.scene_loader import SceneLoadError, load_scene
from .models import PlaneCandidate


LOGGER = logging.getLogger("proxy_mesh_editor")

# pgsr conda 환경의 Open3D 0.19 GPU(OpenGL/Filament) 백엔드는 이 프로젝트가 쓰는
# RustDesk/XWayland류 디스플레이 조합에서 창 생성 중 native segfault를 낸다.
# proxy_placement_editor가 이미 겪어 해결한 문제라, 같은 재시도 전략(호환
# Open3D 0.18 venv → 소프트웨어 렌더링)을 그대로 재사용한다.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
GUI_WORKER_ENV = "RFVIS_ENVELOPE_PICKER_GUI_WORKER"
SOFTWARE_RENDERING_ENV = "RFVIS_ENVELOPE_PICKER_SOFTWARE_RENDERING"
GUI_PYTHON_ENV = "RFVIS_ENVELOPE_PICKER_GUI_PYTHON"
DEFAULT_GUI_RUNTIME = PROJECT_ROOT / ".venv/proxy-placement-editor"
NATIVE_GUI_CRASH_SIGNALS = {6, 11}


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


def _is_same_python(left: Path, right: Path) -> bool:
    # venv의 python은 원본 interpreter symlink일 수 있으므로 resolve()하지 않는다.
    return os.path.abspath(str(left)) == os.path.abspath(str(right))


def _native_signal(return_code: int) -> Optional[int]:
    return None if return_code >= 0 else -return_code


def _run_pick_envelope_worker(
    raw_argv: List[str], software_rendering: bool, python_executable: Optional[Path] = None
) -> int:
    environment = (
        _software_rendering_environment() if software_rendering else dict(os.environ)
    )
    environment[GUI_WORKER_ENV] = "1"
    command = [
        str(python_executable or sys.executable),
        "-m",
        "tools.proxy_mesh_editor.main",
        *raw_argv,
    ]
    return int(subprocess.run(command, env=environment, check=False).returncode)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _set_open3d_seed(seed: int) -> None:
    try:
        import open3d as o3d
    except ImportError as exc:
        raise SceneLoadError(
            "Open3D가 설치되어 있지 않습니다. pgsr 환경을 활성화해 주세요."
        ) from exc
    if hasattr(o3d.utility, "random"):
        o3d.utility.random.seed(seed)


def _log_scene_stats(input_stats: Dict[str, Any], preprocessing: Dict[str, Any]) -> None:
    mesh = input_stats["original_mesh"]
    bounds = mesh["bounds"]
    LOGGER.info(
        "입력 메시: 꼭짓점 %d개, 삼각형 %d개, 표면적 %.6g",
        mesh["vertex_count"],
        mesh["triangle_count"],
        mesh["surface_area"],
    )
    LOGGER.info("입력 경계 최솟값=%s 최댓값=%s", bounds["min"], bounds["max"])
    LOGGER.info(
        "장면 축별 크기=%s, 대각선 길이=%.6g",
        bounds["extent"],
        bounds["diagonal"],
    )
    LOGGER.info(
        "평면 검출점: 전처리 전 %d개, 후 %d개, 제거 %d개",
        preprocessing["before_point_count"],
        preprocessing["after_point_count"],
        preprocessing["removed_point_count"],
    )


def _load_preprocessed_scene(
    args: argparse.Namespace, config: Dict[str, Any]
) -> Tuple[Any, Any, Dict[str, Any], float]:
    """모든 분석 명령이 동일한 장면 로드와 전처리를 거치게 한다."""

    _set_open3d_seed(int(config["scene"]["random_seed"]))
    scene = load_scene(args.mesh, args.reference_point_cloud, config)
    scene_extent = float(scene.input_stats["filtered_mesh"]["bounds"]["diagonal"])
    point_cloud, preprocessing_stats = preprocess_point_cloud(
        scene.point_cloud, config, scene_extent
    )
    _log_scene_stats(scene.input_stats, preprocessing_stats)
    return scene, point_cloud, preprocessing_stats, scene_extent


def _input_metadata(scene: Any) -> Dict[str, Any]:
    return {
        "source_mesh_path": str(scene.source_mesh),
        "reference_point_cloud_path": (
            str(scene.reference_point_cloud)
            if scene.reference_point_cloud is not None
            else None
        ),
        "point_source": scene.point_source,
    }


def _scene_metadata(scene: Any, config: Dict[str, Any], scene_extent: float) -> Dict[str, Any]:
    up_vector = normalize_vector(config["scene"]["up_vector"], "scene.up_vector")
    return {
        "up_vector": up_vector.tolist(),
        "bounds": scene.input_stats["filtered_mesh"]["bounds"],
        "estimated_extent": scene_extent,
        "scale_status": "scene_unit_not_metric_calibrated",
    }


def run_extract(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    scene, point_cloud, preprocessing_stats, scene_extent = _load_preprocessed_scene(
        args, config
    )

    candidates, extraction_stats = extract_planes(point_cloud, config, scene_extent)
    output = Path(args.output).expanduser().resolve()
    preview = write_preview(point_cloud, candidates, output, config["preview"])

    candidate_document: Dict[str, Any] = {
        "schema_version": "1.0",
        "algorithm": {
            "name": "rfvisualizer_proxy_plane_extraction",
            "version": __version__,
        },
        "created_at": _utc_now(),
        "input": _input_metadata(scene),
        "scene": _scene_metadata(scene, config, scene_extent),
        "config": config,
        "input_stats": scene.input_stats,
        "mesh_component_filter": scene.mesh_filter_stats,
        "preprocessing_stats": preprocessing_stats,
        "plane_extraction_stats": extraction_stats,
        "candidate_ids": [candidate.candidate_id for candidate in candidates],
        "plane_candidates": [candidate.to_dict() for candidate in candidates],
        "preview": {
            **preview,
            "color_mapping": {
                candidate.candidate_id: candidate.color.tolist()
                for candidate in candidates
            },
        },
    }
    write_json(output / "plane_candidates.json", candidate_document)
    LOGGER.info(
        "평면 후보 %d개를 저장했습니다: %s",
        len(candidates),
        output / "plane_candidates.json",
    )
    if not candidates:
        LOGGER.warning("조건을 만족하는 평면 후보가 없습니다. YAML 기준을 완화해 주세요.")
    return 0


def run_analyze_normals(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    scene, point_cloud, preprocessing_stats, scene_extent = _load_preprocessed_scene(
        args, config
    )
    output = Path(args.output).expanduser().resolve()
    up_vector = normalize_vector(config["scene"]["up_vector"], "scene.up_vector")
    analysis = write_normal_analysis_outputs(
        point_cloud, output, config["normal_analysis"], up_vector
    )
    analysis_path = output / "normal_analysis.json"
    analysis["files"]["analysis_json"] = str(analysis_path.resolve())
    document: Dict[str, Any] = {
        "schema_version": "1.0",
        "algorithm": {
            "name": "rfvisualizer_normal_analysis",
            "version": __version__,
        },
        "created_at": _utc_now(),
        "input": _input_metadata(scene),
        "scene": _scene_metadata(scene, config, scene_extent),
        "preprocessing_settings": config["preprocessing"],
        "input_stats": scene.input_stats,
        "mesh_component_filter": scene.mesh_filter_stats,
        "preprocessing_stats": preprocessing_stats,
        "normal_analysis_settings": config["normal_analysis"],
        "normal_analysis": analysis,
        "files": analysis["files"],
    }
    write_json(analysis_path, document)
    LOGGER.info(
        "법선 분석 완료: 유효 %d개, 무효 %d개, 결과 %s",
        analysis["valid_normal_count"],
        analysis["invalid_normal_count"],
        analysis_path,
    )
    for result in analysis["threshold_results"]:
        LOGGER.info(
            "법선 기준 %.6g 이하: %d개 (유효 법선의 %.2f%%)",
            result["threshold"],
            result["point_count"],
            100.0 * result["ratio_of_valid_normals"],
        )
    return 0


def run_extract_walls(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    scene, point_cloud, preprocessing_stats, scene_extent = _load_preprocessed_scene(
        args, config
    )
    wall_cloud, candidates, extraction_stats, assigned = extract_wall_planes(
        point_cloud, config, scene_extent
    )
    output = Path(args.output).expanduser().resolve()
    preview = write_wall_preview(
        wall_cloud, candidates, assigned, output, config["preview"]
    )
    preview["color_mapping"] = {
        candidate.candidate_id: candidate.color.tolist() for candidate in candidates
    }
    document: Dict[str, Any] = {
        "schema_version": "1.0",
        "algorithm": {
            "name": "rfvisualizer_wall_plane_extraction",
            "version": __version__,
        },
        "created_at": _utc_now(),
        "input": _input_metadata(scene),
        "scene": _scene_metadata(scene, config, scene_extent),
        "config": {
            "preprocessing": config["preprocessing"],
            "wall_extraction": config["wall_extraction"],
            "plane_meshing_shared_settings": {
                "min_extent": config["plane_meshing"]["min_extent"],
                "min_extent_ratio": config["plane_meshing"]["min_extent_ratio"],
                "vertical_alignment_max_dot": config["plane_meshing"][
                    "vertical_alignment_max_dot"
                ],
            },
        },
        "input_stats": scene.input_stats,
        "mesh_component_filter": scene.mesh_filter_stats,
        "preprocessing_stats": preprocessing_stats,
        "normal_filter_settings": config["wall_extraction"]["normal_filter"],
        "normal_filter_stats": extraction_stats["normal_filter"],
        "wall_ransac_settings": config["wall_extraction"]["ransac"],
        "component_settings": config["wall_extraction"]["components"],
        "wall_meshing_settings": config["wall_extraction"]["meshing"],
        "resolved_scene_unit_thresholds": extraction_stats["resolved_thresholds"],
        "wall_extraction_stats": extraction_stats,
        "candidate_ids": [candidate.candidate_id for candidate in candidates],
        "wall_candidates": [candidate.to_dict() for candidate in candidates],
        "preview": preview,
    }
    path = output / "wall_candidates.json"
    write_json(path, document)
    LOGGER.info(
        "벽 후보 %d개를 저장했습니다: %s (법선 필터 %d점, 잔여 %d점)",
        len(candidates),
        path,
        extraction_stats["normal_filtered_point_count"],
        extraction_stats["residual_wall_point_count"],
    )
    if not candidates:
        LOGGER.warning("조건을 만족하는 벽 후보가 없습니다. 벽 전용 설정을 확인해 주세요.")
    return 0


def run_build_envelope(args: argparse.Namespace) -> int:
    envelope_config = load_envelope_config(args.envelope_config)
    selected = load_envelope_candidates(
        args.plane_candidates, args.wall_candidates, envelope_config
    )
    mesh = build_room_envelope(selected, envelope_config)
    validation_settings = envelope_config["room_envelope"]["validation"]
    topology, geometry, warnings = validate_envelope(mesh, validation_settings)

    output = Path(args.output).expanduser().resolve()
    write_envelope_outputs(
        selected,
        envelope_config,
        Path(args.envelope_config),
        mesh,
        topology,
        geometry,
        warnings,
        output,
    )
    LOGGER.info(
        "닫힌 Room Envelope 생성 완료: 벽 %d개, 꼭짓점 %d개, 삼각형 %d개, 부피 %.6g",
        len(mesh.wall_candidates),
        len(mesh.vertices),
        len(mesh.faces),
        topology["absolute_volume"],
    )
    return 0


def _run_pick_envelope_in_process(args: argparse.Namespace) -> int:
    from .envelope.interactive_app import EnvelopeAssemblyApp

    envelope_config = load_partial_envelope_config(args.envelope_config)
    output = Path(args.output).expanduser().resolve()
    app = EnvelopeAssemblyApp(
        plane_path=args.plane_candidates,
        wall_path=args.wall_candidates,
        base_envelope_config=envelope_config,
        output=output,
    )
    app.run()
    return 0


def run_pick_envelope(args: argparse.Namespace) -> int:
    from .envelope.interactive_app import ensure_gui_display

    ensure_gui_display()
    if os.environ.get(GUI_WORKER_ENV) == "1":
        return _run_pick_envelope_in_process(args)

    compatible_python = _compatible_gui_python()
    if compatible_python and not _is_same_python(compatible_python, Path(sys.executable)):
        LOGGER.info(
            "RustDesk/XWayland 호환 GUI runtime을 사용합니다: %s", compatible_python
        )
        compatible_code = _run_pick_envelope_worker(
            args._raw_argv, software_rendering=False, python_executable=compatible_python
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

    return_code = _run_pick_envelope_worker(args._raw_argv, software_rendering=False)
    if return_code >= 0:
        return return_code

    signal_number = int(_native_signal(return_code) or 0)
    if signal_number not in NATIVE_GUI_CRASH_SIGNALS:
        return 128 + signal_number
    LOGGER.warning(
        "Open3D GPU GUI가 signal %d로 종료되었습니다. Mesa 소프트웨어 렌더링으로 다시 시도합니다.",
        signal_number,
    )
    retry_code = _run_pick_envelope_worker(args._raw_argv, software_rendering=True)
    if retry_code >= 0:
        return retry_code
    raise ValueError(
        "Open3D GUI가 native signal {}로 종료되었습니다. "
        "`python -m tools.proxy_placement_editor.main setup-gui-runtime`으로 "
        "호환 GUI runtime을 준비했는지 확인하거나 GNOME의 Ubuntu on Xorg 세션을 사용하세요.".format(
            -retry_code
        )
    )


def run_calibration_preflight(args: argparse.Namespace) -> int:
    config = load_preflight_config(args.config)
    document = run_preflight(
        envelope_json_path=args.envelope_json,
        envelope_obj_path=args.envelope_obj,
        config_path=args.config,
        config=config,
        output_directory=args.output,
        algorithm_version=__version__,
        created_at=_utc_now(),
    )
    orientation = document["orientation_analysis"]
    rotation = document["rotation_analysis"]
    scale = document["scale_analysis"]
    LOGGER.info(
        "Calibration Preflight %s: 중심 높이 %.6g, 회전 %.6g도, det %.9g",
        "통과" if document["preflight_success"] else "실패",
        orientation["vertical_center_offset"],
        rotation["rotation_angle_deg"],
        rotation["determinant"],
    )
    LOGGER.info(
        "추천 provisional scale %.9g m/scene unit, reference spread %.2f%% (%s)",
        scale["recommended_meters_per_scene_unit"],
        100.0 * scale["relative_spread"],
        scale["spread_status"],
    )
    return 0 if document["preflight_success"] else 2


def run_calibrate_metric(args: argparse.Namespace) -> int:
    config = load_metric_config(args.config)
    result = run_metric_calibration(
        envelope_json_path=args.envelope_json,
        envelope_obj_path=args.envelope_obj,
        config_path=args.config,
        config=config,
        output_directory=args.output,
        algorithm_version=__version__,
        created_at=_utc_now(),
    )
    calibration = result["calibration"]
    geometry = calibration["geometry"]
    LOGGER.info(
        "Metric Calibration 완료: scale %.9g m/scene unit, det %.9g, round-trip %.3g",
        calibration["scale"]["resolved_meters_per_scene_unit"],
        calibration["transform"]["rotation_determinant"],
        calibration["round_trip_error"],
    )
    LOGGER.info(
        "Metric bounds extent=%s, surface area %.6g m^2, volume %.6g m^3",
        geometry["metric_bounds"]["extent"],
        geometry["metric_surface_area"],
        geometry["metric_absolute_volume"],
    )
    if calibration["is_provisional"]:
        LOGGER.warning("PROVISIONAL METRIC CALIBRATION - 현장 실측 전 임시 결과입니다.")
    return 0


def run_export(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    document_path = Path(args.candidates).expanduser().resolve()
    document = read_json(document_path)
    raw_candidates = document.get("plane_candidates")
    if not isinstance(raw_candidates, list):
        raise MetadataError("plane_candidates.json에 plane_candidates 목록이 없습니다.")
    candidates = [PlaneCandidate.from_dict(item) for item in raw_candidates]
    source_documents = {
        candidate.candidate_id: str(document_path) for candidate in candidates
    }
    candidate_documents = [
        {
            "path": str(document_path),
            "source_pass": "plane_extraction",
            "input": document.get("input", {}),
        }
    ]
    wall_document = None
    if args.wall_candidates is not None:
        wall_path = Path(args.wall_candidates).expanduser().resolve()
        wall_document = read_json(wall_path)
        raw_walls = wall_document.get("wall_candidates")
        if not isinstance(raw_walls, list):
            raise MetadataError("wall_candidates.json에 wall_candidates 목록이 없습니다.")
        wall_candidates = [PlaneCandidate.from_dict(item) for item in raw_walls]
        existing_ids = {candidate.candidate_id for candidate in candidates}
        duplicate_ids = sorted(
            existing_ids.intersection(candidate.candidate_id for candidate in wall_candidates)
        )
        if duplicate_ids:
            raise MetadataError(
                "일반 후보와 벽 후보 문서의 candidate_id가 충돌합니다: {}".format(
                    ", ".join(duplicate_ids)
                )
            )
        candidates.extend(wall_candidates)
        source_documents.update(
            {candidate.candidate_id: str(wall_path) for candidate in wall_candidates}
        )
        candidate_documents.append(
            {
                "path": str(wall_path),
                "source_pass": "wall_extraction",
                "input": wall_document.get("input", {}),
            }
        )
    output = Path(args.output).expanduser().resolve()
    exported = export_obj_bundle(candidates, config["selection"], output)
    for item in exported:
        item["candidate_source_document"] = source_documents[item["candidate_id"]]

    metadata = {
        "schema_version": "1.0",
        "algorithm": {
            "name": "rfvisualizer_proxy_plane_export",
            "version": __version__,
        },
        "created_at": _utc_now(),
        "source": document.get("input", {}),
        "candidate_documents": candidate_documents,
        "input_scene_bounds": document.get("scene", {}).get("bounds"),
        "up_vector": document.get("scene", {}).get("up_vector"),
        "scale_status": document.get("scene", {}).get("scale_status"),
        "preprocessing_settings": document.get("config", {}).get("preprocessing"),
        "preprocessing_stats": document.get("preprocessing_stats"),
        "plane_extraction_settings": document.get("config", {}).get(
            "plane_extraction"
        ),
        "plane_extraction_stats": document.get("plane_extraction_stats"),
        "candidate_ids": [candidate.candidate_id for candidate in candidates],
        "wall_extraction_settings": (
            wall_document.get("config", {}).get("wall_extraction")
            if wall_document is not None
            else None
        ),
        "wall_extraction_stats": (
            wall_document.get("wall_extraction_stats")
            if wall_document is not None
            else None
        ),
        "selected_candidates": exported,
        "files": {
            "combined_obj": str((output / "proxy_scene.obj").resolve()),
            "material_library": str((output / "proxy_scene.mtl").resolve()),
            "object_directory": str((output / "objects").resolve()),
        },
    }
    write_json(output / "scene_metadata.json", metadata)
    LOGGER.info("선택 평면 %d개를 OBJ로 저장했습니다: %s", len(exported), output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PGSR 메시에서 Sionna RT용 단순 평면 후보를 추출합니다."
    )
    parser.add_argument("--verbose", action="store_true", help="상세 로그를 표시합니다.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract = subparsers.add_parser("extract", help="평면 후보와 색상 미리보기를 만듭니다.")
    extract.add_argument("--mesh", type=Path, required=True, help="입력 삼각형 PLY")
    extract.add_argument(
        "--reference-point-cloud", type=Path, help="선택적 참고 PLY 점구름"
    )
    extract.add_argument("--config", type=Path, required=True, help="YAML 설정 파일")
    extract.add_argument("--output", type=Path, required=True, help="결과 폴더")
    extract.set_defaults(handler=run_extract)

    analyze_normals = subparsers.add_parser(
        "analyze-normals", help="점 법선의 높이 방향 내적 분포와 미리보기를 만듭니다."
    )
    analyze_normals.add_argument(
        "--mesh", type=Path, required=True, help="입력 삼각형 PLY"
    )
    analyze_normals.add_argument(
        "--reference-point-cloud", type=Path, help="선택적 참고 PLY 점구름"
    )
    analyze_normals.add_argument(
        "--config", type=Path, required=True, help="YAML 설정 파일"
    )
    analyze_normals.add_argument("--output", type=Path, required=True, help="결과 폴더")
    analyze_normals.set_defaults(handler=run_analyze_normals)

    extract_walls = subparsers.add_parser(
        "extract-walls", help="법선 필터를 거친 점에서 벽 평면만 추출합니다."
    )
    extract_walls.add_argument(
        "--mesh", type=Path, required=True, help="입력 삼각형 PLY"
    )
    extract_walls.add_argument(
        "--reference-point-cloud", type=Path, help="선택적 참고 PLY 점구름"
    )
    extract_walls.add_argument(
        "--config", type=Path, required=True, help="YAML 설정 파일"
    )
    extract_walls.add_argument("--output", type=Path, required=True, help="결과 폴더")
    extract_walls.set_defaults(handler=run_extract_walls)

    build_envelope = subparsers.add_parser(
        "build-envelope", help="선택된 평면으로 닫힌 Room Envelope를 만듭니다."
    )
    build_envelope.add_argument(
        "--plane-candidates", type=Path, required=True, help="plane_candidates.json"
    )
    build_envelope.add_argument(
        "--wall-candidates", type=Path, required=True, help="wall_candidates.json"
    )
    build_envelope.add_argument(
        "--envelope-config", type=Path, required=True, help="Room Envelope 선택 YAML"
    )
    build_envelope.add_argument("--output", type=Path, required=True, help="결과 폴더")
    build_envelope.set_defaults(handler=run_build_envelope)

    pick_envelope = subparsers.add_parser(
        "pick-envelope",
        help="3D Viewer에서 Floor/Ceiling/Wall 후보를 클릭으로 골라 Room Envelope를 만듭니다.",
    )
    pick_envelope.add_argument(
        "--plane-candidates", type=Path, required=True, help="plane_candidates.json"
    )
    pick_envelope.add_argument(
        "--wall-candidates", type=Path, required=True, help="wall_candidates.json"
    )
    pick_envelope.add_argument(
        "--envelope-config",
        type=Path,
        required=True,
        help="validation/output 설정만 담은 YAML (floor/ceiling/ordered_walls는 비워둠)",
    )
    pick_envelope.add_argument("--output", type=Path, required=True, help="결과 폴더")
    pick_envelope.set_defaults(handler=run_pick_envelope)

    calibration_preflight = subparsers.add_parser(
        "calibration-preflight",
        help="Metric Calibration 전 상하 방향·회전·축척·좌표 프레임을 진단합니다.",
    )
    calibration_preflight.add_argument(
        "--envelope-json", type=Path, required=True, help="room_envelope.json"
    )
    calibration_preflight.add_argument(
        "--envelope-obj", type=Path, required=True, help="room_envelope.obj"
    )
    calibration_preflight.add_argument(
        "--config", type=Path, required=True, help="Calibration Preflight YAML"
    )
    calibration_preflight.add_argument(
        "--output", type=Path, required=True, help="진단 결과 폴더"
    )
    calibration_preflight.set_defaults(handler=run_calibration_preflight)

    calibrate_metric = subparsers.add_parser(
        "calibrate-metric",
        help="Room Envelope를 미터 단위 표준 좌표계 사본으로 변환합니다.",
    )
    calibrate_metric.add_argument(
        "--envelope-json", type=Path, required=True, help="room_envelope.json"
    )
    calibrate_metric.add_argument(
        "--envelope-obj", type=Path, required=True, help="room_envelope.obj"
    )
    calibrate_metric.add_argument(
        "--config", type=Path, required=True, help="Metric Calibration YAML"
    )
    calibrate_metric.add_argument(
        "--output", type=Path, required=True, help="실제 크기 결과 폴더"
    )
    calibrate_metric.set_defaults(handler=run_calibrate_metric)

    export = subparsers.add_parser("export", help="선택한 후보를 OBJ/MTL로 내보냅니다.")
    export.add_argument(
        "--candidates", type=Path, required=True, help="plane_candidates.json"
    )
    export.add_argument(
        "--wall-candidates", type=Path, help="선택적으로 함께 읽을 wall_candidates.json"
    )
    export.add_argument("--config", type=Path, required=True, help="선택 항목이 든 YAML")
    export.add_argument("--output", type=Path, required=True, help="결과 폴더")
    export.set_defaults(handler=run_export)
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
    except (
        PreviewExportError,
        EnvelopeExportError,
        CalibrationPreviewError,
        CalibrationReportError,
        MetricExportError,
        MetricMetadataError,
        SceneLoadError,
        ValueError,
    ) as exc:
        LOGGER.error("%s", exc)
        return 2
    except Exception:
        LOGGER.exception("예상하지 못한 오류가 발생했습니다.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
