"""Phase 2-A 전체 성공 조건을 한 문서로 합친다."""

from __future__ import annotations

from typing import Any, Dict, List


def build_validation(
    environment: Dict[str, Any],
    manifest: Dict[str, Any],
    positions: List[Dict[str, Any]],
    bridge_validation: Dict[str, Any],
    path_results: Dict[str, Any],
    coverage: Dict[str, Any],
    performance: Dict[str, Any],
    warnings: List[str],
) -> Dict[str, Any]:
    position_success = all(value["validation"]["safe_with_clearance"] for value in positions)
    los_success = bool(path_results["los"]["validation"]["success"])
    reflection_status = path_results["reflection"]["validation"]["status"]
    coverage_success = bool(coverage["metadata"]["success"])
    checks = {
        "environment_available": environment.get("status") == "available",
        "metric_scene_conversion": bool(manifest["conversion_validation"]["success"]),
        "positions_inside_and_clear": position_success,
        "los_solver_and_distance": los_success,
        "reflection_solver_finite": reflection_status != "failure",
        "coverage_solver_and_valid_ratio": coverage_success,
        "coordinate_bridge_round_trip": bool(bridge_validation["success"]),
    }
    overall = all(checks.values())
    return {
        "schema_version": "1.0",
        "status": "pass" if overall else "failure",
        "physically_validated": False,
        "overall_success": overall,
        "checks": checks,
        "reflection_status": reflection_status,
        "position_validation": positions,
        "coordinate_bridge_validation": bridge_validation,
        "los_validation": path_results["los"]["validation"],
        "reflection_validation": path_results["reflection"]["validation"],
        "coverage_validation": coverage["metadata"],
        "performance_seconds": performance,
        "warnings": warnings,
    }
