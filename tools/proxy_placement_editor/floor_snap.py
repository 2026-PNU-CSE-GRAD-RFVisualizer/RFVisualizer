"""Floor-contact helpers shared by the headless core and GUI."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

import numpy as np

from tools.sionna_scenario.obstacle_schema import parse_obstacle
from tools.sionna_scenario.primitive_builder import build_obstacle_mesh


def build_preview_mesh(obstacle: Dict[str, Any], room: Any):
    """Build disabled drafts by validating a temporary enabled copy."""

    value = deepcopy(obstacle)
    value["enabled"] = True
    spec = parse_obstacle(value)
    return build_obstacle_mesh(spec, room=room)


def floor_contact_report(obstacle: Dict[str, Any], room: Any) -> Dict[str, Any]:
    mesh = build_preview_mesh(obstacle, room)
    clearances = [
        room.inspect_point(vertex, 0.0)["floor_clearance_m"] for vertex in mesh.vertices
    ]
    geometry = obstacle.get("geometry", {})
    anchor = geometry.get("anchor", {})
    if isinstance(anchor, str):
        mode, policy, configured = (
            anchor,
            "anchor_point",
            geometry.get("floor_clearance_m", 0.0),
        )
    else:
        mode = anchor.get("mode", "center")
        contact = anchor.get("floor_contact_policy", {}) or {}
        if isinstance(contact, str):
            policy, configured = contact, 0.0
        else:
            policy = contact.get("type", "anchor_point")
            configured = contact.get(
                "clearance_m", geometry.get("floor_clearance_m", 0.0)
            )
    return {
        "anchor_mode": mode,
        "policy": policy,
        "configured_clearance_m": float(configured),
        "minimum_bottom_vertex_clearance_m": float(np.min(clearances)),
        "maximum_bottom_vertex_clearance_m": float(np.max(clearances)),
        "resolved_transform": np.asarray(mesh.transform, dtype=float).tolist(),
    }
