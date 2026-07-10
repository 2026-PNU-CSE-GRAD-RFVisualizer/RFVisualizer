import copy
from pathlib import Path

import numpy as np

from tools.proxy_mesh_editor.envelope.candidate_loader import EnvelopeCandidates
from tools.proxy_mesh_editor.envelope.config import DEFAULT_ENVELOPE_CONFIG
from tools.proxy_mesh_editor.models import PlaneCandidate, PlaneRectangle


def _rectangle(points, normal, up):
    points = np.asarray(points, dtype=float)
    origin = np.mean(points, axis=0)
    basis_u = points[1] - points[0]
    basis_u = basis_u / np.linalg.norm(basis_u)
    basis_v = np.asarray(up, dtype=float)
    basis_v = basis_v - np.dot(basis_v, normal) * normal
    if np.linalg.norm(basis_v) <= 1e-12:
        basis_v = np.cross(normal, basis_u)
    basis_v = basis_v / np.linalg.norm(basis_v)
    relative = points - origin
    u_values = relative @ basis_u
    v_values = relative @ basis_v
    return PlaneRectangle(
        origin=origin,
        basis_u=basis_u,
        basis_v=basis_v,
        bounds_2d={
            "u_min": float(np.min(u_values)),
            "u_max": float(np.max(u_values)),
            "v_min": float(np.min(v_values)),
            "v_max": float(np.max(v_values)),
        },
        corners=points,
        width=float(np.max(u_values) - np.min(u_values)),
        height=float(np.max(v_values) - np.min(v_values)),
        area=float(
            (np.max(u_values) - np.min(u_values))
            * (np.max(v_values) - np.min(v_values))
        ),
    )


def _candidate(candidate_id, equation, rectangle_points, orientation, semantic, up):
    equation = np.asarray(equation, dtype=float)
    normal = equation[:3] / np.linalg.norm(equation[:3])
    rectangle = _rectangle(rectangle_points, normal, up)
    return PlaneCandidate(
        candidate_id=candidate_id,
        plane_equation=equation,
        normal=normal,
        centroid=rectangle.origin,
        inlier_count=100,
        raw_ransac_inlier_count=100,
        inlier_ratio=0.1,
        remaining_inlier_ratio=0.1,
        fitting_rmse=0.0,
        mean_absolute_distance=0.0,
        rectangle=rectangle,
        orientation=orientation,
        suggested_semantic=semantic,
        semantic_confidence=1.0,
        semantic_reason="synthetic",
        color=np.asarray([0.3, 0.6, 0.9]),
        source_pass=("wall_extraction" if orientation == "vertical" else "plane_extraction"),
    )


def rotation_matrix(axis=(1.0, 2.0, 3.0), angle=0.7):
    axis = np.asarray(axis, dtype=float)
    axis = axis / np.linalg.norm(axis)
    x, y, z = axis
    skew = np.asarray([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])
    return np.eye(3) + np.sin(angle) * skew + (1.0 - np.cos(angle)) * (skew @ skew)


def make_envelope_candidates(vertices_2d, height=3.0, rotation=None, translation=None):
    polygon = np.asarray(vertices_2d, dtype=float)
    rotation = np.eye(3) if rotation is None else np.asarray(rotation, dtype=float)
    translation = np.zeros(3) if translation is None else np.asarray(translation, dtype=float)
    up = rotation @ np.asarray([0.0, 0.0, 1.0])

    def transform(points):
        return np.asarray(points, dtype=float) @ rotation.T + translation

    bottom_local = np.column_stack([polygon, np.zeros(len(polygon))])
    top_local = np.column_stack([polygon, np.full(len(polygon), height)])
    bottom = transform(bottom_local)
    top = transform(top_local)

    floor_normal = rotation @ np.asarray([0.0, 0.0, 1.0])
    floor_equation = np.r_[floor_normal, -np.dot(floor_normal, bottom[0])]
    ceiling_equation = np.r_[floor_normal, -np.dot(floor_normal, top[0])]
    floor = _candidate(
        "plane_floor",
        floor_equation,
        bottom[:4] if len(bottom) >= 4 else bottom,
        "horizontal",
        "floor",
        up,
    )
    ceiling = _candidate(
        "plane_ceiling",
        ceiling_equation,
        top[:4] if len(top) >= 4 else top,
        "horizontal",
        "ceiling",
        up,
    )

    walls = []
    for index in range(len(polygon)):
        following = (index + 1) % len(polygon)
        edge = polygon[following] - polygon[index]
        outward_local = np.asarray([edge[1], -edge[0], 0.0])
        outward_local = outward_local / np.linalg.norm(outward_local)
        normal = rotation @ outward_local
        equation = np.r_[normal, -np.dot(normal, bottom[index])]
        rectangle_points = np.asarray(
            [bottom[index], bottom[following], top[following], top[index]]
        )
        walls.append(
            _candidate(
                "wall_{:03d}".format(index),
                equation,
                rectangle_points,
                "vertical",
                "wall",
                up,
            )
        )

    scene = {"scene": {"up_vector": up.tolist(), "estimated_extent": 20.0}}
    return EnvelopeCandidates(
        floor=floor,
        ceiling=ceiling,
        walls=walls,
        up_vector=up,
        plane_document_path=Path("plane_candidates.json"),
        wall_document_path=Path("wall_candidates.json"),
        plane_document=scene,
        wall_document=scene,
    )


def make_envelope_config(candidates):
    config = copy.deepcopy(DEFAULT_ENVELOPE_CONFIG)
    room = config["room_envelope"]
    room["floor"]["candidate_id"] = candidates.floor.candidate_id
    room["ceiling"]["candidate_id"] = candidates.ceiling.candidate_id
    room["ordered_walls"] = [
        {"candidate_id": candidate.candidate_id} for candidate in candidates.walls
    ]
    return config
