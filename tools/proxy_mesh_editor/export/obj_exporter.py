"""선택한 사각형들을 객체별 OBJ와 하나의 통합 OBJ로 저장한다."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np

from ..models import ALLOWED_SEMANTICS, PlaneCandidate


class ObjExportError(ValueError):
    """선택 항목이나 OBJ 저장에 문제가 있을 때 발생한다."""


MATERIAL_COLORS: Dict[str, Tuple[float, float, float]] = {
    "floor": (0.55, 0.55, 0.55),
    "wall": (0.82, 0.80, 0.74),
    "ceiling": (0.92, 0.92, 0.88),
    "unknown": (0.70, 0.50, 0.75),
    "door": (0.52, 0.30, 0.16),
    "blackboard": (0.08, 0.20, 0.13),
    "desk": (0.66, 0.42, 0.22),
}


def _format_vector(prefix: str, values: np.ndarray) -> str:
    return "{} {}\n".format(
        prefix, " ".join("{:.12g}".format(float(value)) for value in values)
    )


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        raise ObjExportError("파일을 저장할 수 없습니다: {}".format(exc)) from exc


def _prepare_objects(
    candidates: Sequence[PlaneCandidate], selection: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    if not selection:
        raise ObjExportError(
            "선택된 평면이 없습니다. YAML의 selection에 candidate_id와 semantic을 지정해 주세요."
        )
    candidates_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    selected_ids = set()
    counters: Dict[str, int] = defaultdict(int)
    objects: List[Dict[str, Any]] = []
    for item in selection:
        if not isinstance(item, dict):
            raise ObjExportError("selection의 각 항목은 candidate_id와 semantic을 가져야 합니다.")
        candidate_id = str(item.get("candidate_id", ""))
        semantic = str(item.get("semantic", ""))
        if candidate_id not in candidates_by_id:
            raise ObjExportError("존재하지 않는 candidate_id입니다: {}".format(candidate_id))
        if candidate_id in selected_ids:
            raise ObjExportError("같은 candidate_id가 두 번 선택되었습니다: {}".format(candidate_id))
        if semantic not in ALLOWED_SEMANTICS:
            raise ObjExportError(
                "지원하지 않는 semantic입니다: {}. 가능한 값: {}".format(
                    semantic, ", ".join(ALLOWED_SEMANTICS)
                )
            )
        object_name = "{}_{:03d}".format(semantic, counters[semantic])
        counters[semantic] += 1
        selected_ids.add(candidate_id)
        objects.append(
            {
                "candidate": candidates_by_id[candidate_id],
                "candidate_id": candidate_id,
                "semantic": semantic,
                "object_name": object_name,
                "material_name": semantic,
            }
        )
    return objects


def _object_geometry_text(
    candidate: PlaneCandidate,
    object_name: str,
    semantic: str,
    vertex_offset: int = 0,
    normal_index: int = 1,
) -> str:
    lines = [
        "o {}\n".format(object_name),
        "g {}\n".format(semantic),
        "usemtl {}\n".format(semantic),
    ]
    for corner in candidate.rectangle.corners:
        lines.append(_format_vector("v", corner))
    lines.append(_format_vector("vn", candidate.normal))
    indices = [vertex_offset + index for index in (1, 2, 3, 4)]
    lines.append(
        "f {}//{} {}//{} {}//{}\n".format(
            indices[0], normal_index, indices[1], normal_index, indices[2], normal_index
        )
    )
    lines.append(
        "f {}//{} {}//{} {}//{}\n".format(
            indices[0], normal_index, indices[2], normal_index, indices[3], normal_index
        )
    )
    return "".join(lines)


def _material_text(semantics: Sequence[str]) -> str:
    blocks = ["# RFVisualizer Phase 1 proxy materials\n"]
    for semantic in semantics:
        color = MATERIAL_COLORS[semantic]
        blocks.extend(
            [
                "\nnewmtl {}\n".format(semantic),
                "Ka 0 0 0\n",
                "Kd {:.6f} {:.6f} {:.6f}\n".format(*color),
                "Ks 0 0 0\n",
                "d 1.0\n",
                "illum 1\n",
            ]
        )
    return "".join(blocks)


def export_obj_bundle(
    candidates: Sequence[PlaneCandidate],
    selection: Sequence[Dict[str, Any]],
    output_directory: Path,
) -> List[Dict[str, Any]]:
    objects = _prepare_objects(candidates, selection)
    output = Path(output_directory)
    object_directory = output / "objects"
    output.mkdir(parents=True, exist_ok=True)
    object_directory.mkdir(parents=True, exist_ok=True)
    for semantic in ALLOWED_SEMANTICS:
        for stale_path in object_directory.glob(
            "{}_[0-9][0-9][0-9].obj".format(semantic)
        ):
            stale_path.unlink()

    semantic_order: List[str] = []
    for item in objects:
        semantic = item["semantic"]
        if semantic not in semantic_order:
            semantic_order.append(semantic)
    _atomic_write_text(output / "proxy_scene.mtl", _material_text(semantic_order))

    combined = ["# RFVisualizer Phase 1 proxy scene\n", "mtllib proxy_scene.mtl\n\n"]
    vertex_offset = 0
    exported: List[Dict[str, Any]] = []
    for normal_index, item in enumerate(objects, start=1):
        candidate = item["candidate"]
        object_name = item["object_name"]
        semantic = item["semantic"]
        combined.append(
            _object_geometry_text(
                candidate,
                object_name,
                semantic,
                vertex_offset=vertex_offset,
                normal_index=normal_index,
            )
        )
        combined.append("\n")

        individual = [
            "# RFVisualizer Phase 1 proxy object\n",
            "mtllib ../proxy_scene.mtl\n\n",
            _object_geometry_text(candidate, object_name, semantic),
        ]
        object_path = object_directory / "{}.obj".format(object_name)
        _atomic_write_text(object_path, "".join(individual))
        exported.append(
            {
                "candidate_id": item["candidate_id"],
                "semantic": semantic,
                "obj_object_name": object_name,
                "obj_material_name": semantic,
                "object_obj_path": str(object_path.resolve()),
                "plane_equation": candidate.plane_equation.tolist(),
                "centroid": candidate.centroid.tolist(),
                "normal": candidate.normal.tolist(),
                "rectangle_dimensions": {
                    "width": candidate.rectangle.width,
                    "height": candidate.rectangle.height,
                    "area": candidate.rectangle.area,
                },
                "rectangle_corners": candidate.rectangle.corners.tolist(),
            }
        )
        vertex_offset += 4

    _atomic_write_text(output / "proxy_scene.obj", "".join(combined))
    return exported
