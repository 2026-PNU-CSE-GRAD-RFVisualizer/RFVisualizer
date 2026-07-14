"""Headless PNG/OBJ/PLY preview export for metric and PGSR coordinates."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

import numpy as np

from tools.sionna_smoke_test.io_utils import atomic_write_text

from .reference_loader import ReferenceGeometry
from .report import placement_report_markdown
from .scene_loader import PlacementScene


MATERIAL_COLORS = {
    "concrete": (0.55, 0.55, 0.58),
    "wood": (0.55, 0.31, 0.12),
    "metal": (0.25, 0.45, 0.68),
    "glass": (0.25, 0.75, 0.85),
}


def _edges(faces: np.ndarray):
    return sorted(
        {
            tuple(sorted((int(face[index]), int(face[(index + 1) % 3]))))
            for face in faces
            for index in range(3)
        }
    )


def _write_obj(path: Path, records: Iterable[Dict[str, Any]], vertex_key: str) -> None:
    lines = ["# RFVisualizer Phase 2-C provisional proxy objects"]
    offset = 1
    for record in records:
        if not record.get("renderable"):
            continue
        vertices = record[vertex_key]
        lines.append("o {}".format(record["id"]))
        lines.append("g {}".format(record["source"].get("semantic_class", "proxy")))
        for vertex in vertices:
            lines.append("v {:.9f} {:.9f} {:.9f}".format(*vertex))
        for face in record["faces"]:
            lines.append(
                "f {} {} {}".format(
                    face[0] + offset, face[1] + offset, face[2] + offset
                )
            )
        offset += len(vertices)
    atomic_write_text(path, "\n".join(lines) + "\n")


def _write_ply(path: Path, records: Iterable[Dict[str, Any]]) -> None:
    values = [value for value in records if value.get("renderable")]
    vertex_count = sum(len(value["metric_vertices"]) for value in values)
    face_count = sum(len(value["faces"]) for value in values)
    lines = [
        "ply",
        "format ascii 1.0",
        "comment RFVisualizer Phase 2-C provisional proxy objects",
        "element vertex {}".format(vertex_count),
        "property float x",
        "property float y",
        "property float z",
        "property uchar red",
        "property uchar green",
        "property uchar blue",
        "element face {}".format(face_count),
        "property list uchar int vertex_indices",
        "end_header",
    ]
    for record in values:
        color = MATERIAL_COLORS.get(record["material"]["category"], (0.7, 0.7, 0.7))
        rgb = [int(round(channel * 255)) for channel in color]
        for vertex in record["metric_vertices"]:
            lines.append(
                "{:.9f} {:.9f} {:.9f} {} {} {}".format(
                    vertex[0], vertex[1], vertex[2], *rgb
                )
            )
    offset = 0
    for record in values:
        for face in record["faces"]:
            lines.append(
                "3 {} {} {}".format(
                    face[0] + offset, face[1] + offset, face[2] + offset
                )
            )
        offset += len(record["metric_vertices"])
    atomic_write_text(path, "\n".join(lines) + "\n")


def _draw_room_projection(ax, scene: PlacementScene, axes: Tuple[int, int]) -> None:
    for first, second in _edges(scene.room_faces):
        segment = scene.room_vertices[[first, second]][:, axes]
        ax.plot(
            segment[:, 0], segment[:, 1], color="#777777", linewidth=1.0, alpha=0.75
        )


def _draw_reference_projection(
    ax, reference: ReferenceGeometry, axes: Tuple[int, int]
) -> None:
    points = reference.vertices_metric
    # A display-only reference can contain hundreds of thousands of triangles.
    # Drawing each edge as a separate Matplotlib artist stalls preview export,
    # so both meshes and point clouds use the same deterministic point sample.
    stride = max(1, len(points) // 30000)
    ax.scatter(
        points[::stride, axes[0]],
        points[::stride, axes[1]],
        s=0.15,
        c="#aab1b8",
        alpha=0.18,
    )


def _projection(
    path: Path,
    scene: PlacementScene,
    records: Iterable[Dict[str, Any]],
    axes: Tuple[int, int],
    labels: Tuple[str, str],
    title: str,
    reference: Optional[ReferenceGeometry],
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon

    figure, ax = plt.subplots(figsize=(10, 7), dpi=150)
    _draw_room_projection(ax, scene, axes)
    if reference is not None:
        _draw_reference_projection(ax, reference, axes)
    for record in records:
        if not record.get("renderable"):
            continue
        vertices = np.asarray(record["metric_vertices"], dtype=float)
        color = MATERIAL_COLORS.get(record["material"]["category"], (0.7, 0.7, 0.7))
        alpha = 0.65 if record["enabled"] else 0.22
        if record["status"] in {"INVALID", "DISABLED_INVALID"}:
            color = (0.85, 0.1, 0.1)
        points = vertices[:, axes]
        center = np.mean(points, axis=0)
        try:
            from scipy.spatial import ConvexHull

            hull = points[ConvexHull(points).vertices]
        except Exception:
            order = np.argsort(
                np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0])
            )
            hull = points[order]
        ax.add_patch(
            Polygon(
                hull,
                closed=True,
                facecolor=color,
                edgecolor=color,
                alpha=alpha,
                linewidth=1.5,
            )
        )
        ax.text(
            center[0], center[1], record["id"], fontsize=7, ha="center", va="center"
        )
    ax.plot([0.0, 1.0], [0.0, 0.0], color="black", linewidth=3)
    ax.text(0.5, 0.08, "1 m", fontsize=8, ha="center")
    ax.set_xlabel(labels[0])
    ax.set_ylabel(labels[1])
    ax.set_title("{} — PROVISIONAL".format(title))
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, alpha=0.2)
    figure.tight_layout()
    figure.savefig(path)
    plt.close(figure)


def _perspective(
    path: Path,
    scene: PlacementScene,
    records: Iterable[Dict[str, Any]],
    reference: Optional[ReferenceGeometry],
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    figure = plt.figure(figsize=(10, 7), dpi=150)
    ax = figure.add_subplot(111, projection="3d")
    for first, second in _edges(scene.room_faces):
        segment = scene.room_vertices[[first, second]]
        ax.plot(
            segment[:, 0],
            segment[:, 1],
            segment[:, 2],
            color="#777777",
            linewidth=1.0,
            alpha=0.7,
        )
    if reference is not None:
        points = reference.vertices_metric
        stride = max(1, len(points) // 40000)
        ax.scatter(
            points[::stride, 0],
            points[::stride, 1],
            points[::stride, 2],
            s=0.1,
            c="#aab1b8",
            alpha=0.08,
        )
    for record in records:
        if not record.get("renderable"):
            continue
        vertices = np.asarray(record["metric_vertices"], dtype=float)
        faces = np.asarray(record["faces"], dtype=int)
        color = MATERIAL_COLORS.get(record["material"]["category"], (0.7, 0.7, 0.7))
        if record["status"] in {"INVALID", "DISABLED_INVALID"}:
            color = (0.85, 0.1, 0.1)
        collection = Poly3DCollection(
            vertices[faces],
            facecolor=color,
            edgecolor=color,
            linewidth=0.25,
            alpha=0.65 if record["enabled"] else 0.2,
        )
        ax.add_collection3d(collection)
        center = np.mean(vertices, axis=0)
        ax.text(center[0], center[1], center[2], record["id"], fontsize=7)
    bounds = scene.room_metadata["bounds"]
    minimum, maximum = np.asarray(bounds["min"]), np.asarray(bounds["max"])
    ax.set_xlim(minimum[0], maximum[0])
    ax.set_ylim(minimum[1], maximum[1])
    ax.set_zlim(minimum[2], maximum[2])
    ax.set_xlabel("X [m]")
    ax.set_ylabel("Y [m]")
    ax.set_zlabel("Z [m]")
    ax.set_title("Perspective — PROVISIONAL GEOMETRY")
    ax.view_init(elev=24, azim=-56)
    figure.tight_layout()
    figure.savefig(path)
    plt.close(figure)


def export_preview(
    scene: PlacementScene,
    report: Dict[str, Any],
    output: Path,
    reference: Optional[ReferenceGeometry] = None,
    include_reference: bool = True,
) -> Dict[str, str]:
    directory = Path(output).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    values = report["objects"]
    active_reference = reference if include_reference else None
    paths = {
        "top_view_png": directory / "top_view.png",
        "front_view_png": directory / "front_view.png",
        "side_view_png": directory / "side_view.png",
        "perspective_view_png": directory / "perspective_view.png",
        "proxy_objects_metric_obj": directory / "proxy_objects_metric.obj",
        "proxy_objects_metric_ply": directory / "proxy_objects_metric.ply",
        "proxy_objects_scene_obj": directory / "proxy_objects_scene.obj",
        "placement_report_md": directory / "placement_report.md",
    }
    _projection(
        paths["top_view_png"],
        scene,
        values,
        (0, 1),
        ("X [m]", "Y [m]"),
        "Top view",
        active_reference,
    )
    _projection(
        paths["front_view_png"],
        scene,
        values,
        (0, 2),
        ("X [m]", "Z [m]"),
        "Front view",
        active_reference,
    )
    _projection(
        paths["side_view_png"],
        scene,
        values,
        (1, 2),
        ("Y [m]", "Z [m]"),
        "Side view",
        active_reference,
    )
    _perspective(paths["perspective_view_png"], scene, values, active_reference)
    _write_obj(paths["proxy_objects_metric_obj"], values, "metric_vertices")
    _write_ply(paths["proxy_objects_metric_ply"], values)
    _write_obj(paths["proxy_objects_scene_obj"], values, "scene_vertices")
    string_paths = {key: str(value) for key, value in paths.items()}
    atomic_write_text(
        paths["placement_report_md"], placement_report_markdown(report, string_paths)
    )
    return string_paths
