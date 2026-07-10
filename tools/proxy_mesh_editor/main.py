"""Proxy Mesh Phase 1 명령줄 실행 진입점."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__
from .config import ConfigError, load_config, normalize_vector
from .export.obj_exporter import ObjExportError, export_obj_bundle
from .export.preview_exporter import PreviewExportError, write_preview
from .geometry.plane_extractor import extract_planes
from .geometry.preprocessing import preprocess_point_cloud
from .io.metadata_io import MetadataError, read_json, write_json
from .io.scene_loader import SceneLoadError, load_scene
from .models import PlaneCandidate


LOGGER = logging.getLogger("proxy_mesh_editor")


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


def run_extract(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    _set_open3d_seed(int(config["scene"]["random_seed"]))
    scene = load_scene(args.mesh, args.reference_point_cloud, config)
    scene_extent = float(scene.input_stats["filtered_mesh"]["bounds"]["diagonal"])
    point_cloud, preprocessing_stats = preprocess_point_cloud(
        scene.point_cloud, config, scene_extent
    )
    _log_scene_stats(scene.input_stats, preprocessing_stats)

    candidates, extraction_stats = extract_planes(point_cloud, config, scene_extent)
    output = Path(args.output).expanduser().resolve()
    preview = write_preview(point_cloud, candidates, output, config["preview"])

    up_vector = normalize_vector(config["scene"]["up_vector"], "scene.up_vector")
    candidate_document: Dict[str, Any] = {
        "schema_version": "1.0",
        "algorithm": {
            "name": "rfvisualizer_proxy_plane_extraction",
            "version": __version__,
        },
        "created_at": _utc_now(),
        "input": {
            "source_mesh_path": str(scene.source_mesh),
            "reference_point_cloud_path": (
                str(scene.reference_point_cloud)
                if scene.reference_point_cloud is not None
                else None
            ),
            "point_source": scene.point_source,
        },
        "scene": {
            "up_vector": up_vector.tolist(),
            "bounds": scene.input_stats["filtered_mesh"]["bounds"],
            "estimated_extent": scene_extent,
            "scale_status": "scene_unit_not_metric_calibrated",
        },
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


def run_export(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    document = read_json(args.candidates)
    raw_candidates = document.get("plane_candidates")
    if not isinstance(raw_candidates, list):
        raise MetadataError("plane_candidates.json에 plane_candidates 목록이 없습니다.")
    candidates = [PlaneCandidate.from_dict(item) for item in raw_candidates]
    output = Path(args.output).expanduser().resolve()
    exported = export_obj_bundle(candidates, config["selection"], output)

    metadata = {
        "schema_version": "1.0",
        "algorithm": {
            "name": "rfvisualizer_proxy_plane_export",
            "version": __version__,
        },
        "created_at": _utc_now(),
        "source": document.get("input", {}),
        "input_scene_bounds": document.get("scene", {}).get("bounds"),
        "up_vector": document.get("scene", {}).get("up_vector"),
        "scale_status": document.get("scene", {}).get("scale_status"),
        "preprocessing_settings": document.get("config", {}).get("preprocessing"),
        "preprocessing_stats": document.get("preprocessing_stats"),
        "plane_extraction_settings": document.get("config", {}).get(
            "plane_extraction"
        ),
        "plane_extraction_stats": document.get("plane_extraction_stats"),
        "candidate_ids": document.get("candidate_ids", []),
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

    export = subparsers.add_parser("export", help="선택한 후보를 OBJ/MTL로 내보냅니다.")
    export.add_argument(
        "--candidates", type=Path, required=True, help="plane_candidates.json"
    )
    export.add_argument("--config", type=Path, required=True, help="선택 항목이 든 YAML")
    export.add_argument("--output", type=Path, required=True, help="결과 폴더")
    export.set_defaults(handler=run_export)
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
        ConfigError,
        MetadataError,
        ObjExportError,
        PreviewExportError,
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

