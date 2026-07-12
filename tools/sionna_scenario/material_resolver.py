"""Strict Sionna RT material category resolution for obstacle scenarios."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set

import numpy as np


class MaterialResolutionError(ValueError):
    """Raised when a requested RF material cannot be resolved exactly."""


CATEGORY_TO_ITU_TYPE = {
    "concrete": "concrete",
    "wood": "wood",
    "metal": "metal",
    "glass": "glass",
}


def _safe_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value)).strip("_")
    if not cleaned:
        raise MaterialResolutionError("Material ID에 사용할 obstacle ID가 비어 있습니다.")
    return cleaned


def installed_itu_types() -> Optional[Set[str]]:
    """Return types from the installed Sionna package, or ``None`` if unavailable."""

    try:
        from sionna.rt.radio_materials.itu import ITU_MATERIALS_PROPERTIES

        return set(ITU_MATERIALS_PROPERTIES)
    except (ImportError, ModuleNotFoundError):
        return None


def resolve_material_request(obstacle: Dict[str, Any]) -> Dict[str, Any]:
    material = obstacle.get("material") or {}
    category = material.get("category")
    preset = material.get("preset")
    if category is not None and preset is not None and category != preset:
        raise MaterialResolutionError(
            "Material category '{}'와 preset '{}'이 충돌합니다.".format(category, preset)
        )
    category = category if category is not None else preset
    if category not in CATEGORY_TO_ITU_TYPE:
        raise MaterialResolutionError(
            "지원하지 않는 material category '{}'; concrete/wood/metal/glass 중 하나가 필요합니다.".format(
                category
            )
        )
    source = material.get("source", "sionna_preset")
    if source != "sionna_preset":
        raise MaterialResolutionError("이번 단계는 sionna_preset material source만 지원합니다.")
    itu_type = CATEGORY_TO_ITU_TYPE[category]
    installed = installed_itu_types()
    if installed is not None and itu_type not in installed:
        raise MaterialResolutionError(
            "설치된 Sionna RT에 ITU material '{}'가 없습니다.".format(itu_type)
        )
    try:
        thickness = float(material.get("thickness_m", 0.1))
        scattering = float(material.get("scattering_coefficient", 0.0))
    except (TypeError, ValueError) as exc:
        raise MaterialResolutionError("Material thickness/scattering 값이 숫자가 아닙니다.") from exc
    if not np.isfinite(thickness) or thickness <= 0.0:
        raise MaterialResolutionError("Material thickness_m은 유한한 양수여야 합니다.")
    if not np.isfinite(scattering) or not 0.0 <= scattering <= 1.0:
        raise MaterialResolutionError("scattering_coefficient는 0~1 범위여야 합니다.")
    obstacle_id = str(obstacle["id"])
    export = obstacle.get("export")
    export = export if isinstance(export, dict) else {}
    return {
        "obstacle_id": obstacle_id,
        "object_name": str(export.get("object_name", obstacle_id)),
        "category": category,
        "actual_sionna_material_name": "itu_{}_{}".format(itu_type, _safe_id(obstacle_id)),
        "itu_type": itu_type,
        "thickness_m": thickness,
        "scattering_coefficient": scattering,
        "source": source,
        "availability_verified_against_installed_sionna": installed is not None,
        "fallback_used": False,
        "warning": None,
    }


def resolve_obstacle_materials(obstacles: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    records = [resolve_material_request(value) for value in obstacles if value.get("enabled")]
    names = [value["actual_sionna_material_name"] for value in records]
    if len(names) != len(set(names)):
        raise MaterialResolutionError("Resolved obstacle material name이 충돌합니다.")
    return {
        "schema_version": "1.0",
        "status": "provisional",
        "physically_validated": False,
        "strict_resolution": True,
        "fallback_policy": "none",
        "installed_sionna_api_checked": installed_itu_types() is not None,
        "materials": records,
        "object_mapping": [
            {
                "object_name": value["object_name"],
                "category": value["category"],
                "radio_material": value["actual_sionna_material_name"],
            }
            for value in records
        ],
    }


def material_xml(record: Dict[str, Any]) -> str:
    return "".join(
        [
            '    <bsdf type="itu-radio-material" id="{}">\n'.format(
                record["actual_sionna_material_name"]
            ),
            '        <string name="type" value="{}"/>\n'.format(record["itu_type"]),
            '        <float name="thickness" value="{:.12g}"/>\n'.format(
                record["thickness_m"]
            ),
            '        <float name="scattering_coefficient" value="{:.12g}"/>\n'.format(
                record["scattering_coefficient"]
            ),
            "    </bsdf>\n",
        ]
    )


def _scalar(value: Any) -> Optional[float]:
    try:
        array = np.asarray(value.numpy()).reshape(-1)
    except AttributeError:
        array = np.asarray(value).reshape(-1)
    return float(array[0]) if len(array) else None


def inspect_scene_materials(
    scene: Any, manifest: Dict[str, Any], requested: Dict[str, Any]
) -> Dict[str, Any]:
    """Verify material registration and record values evaluated by Sionna RT."""

    requested_by_name = {
        value["actual_sionna_material_name"]: value
        for value in requested.get("materials", [])
    }
    records: List[Dict[str, Any]] = []
    for name, expected in requested_by_name.items():
        if name not in scene.radio_materials:
            raise MaterialResolutionError(
                "Sionna scene에 obstacle material '{}'가 등록되지 않았습니다.".format(name)
            )
        material = scene.radio_materials[name]
        actual_type = getattr(material, "itu_type", None)
        if actual_type != expected["itu_type"]:
            raise MaterialResolutionError(
                "Material '{}'의 실제 ITU type '{}'가 요청 '{}'와 다릅니다.".format(
                    name, actual_type, expected["itu_type"]
                )
            )
        records.append(
            {
                "category": expected["category"],
                "actual_sionna_material_name": name,
                "itu_type": actual_type,
                "class": material.__class__.__name__,
                "relative_permittivity": _scalar(material.relative_permittivity),
                "conductivity_s_per_m": _scalar(material.conductivity),
                "thickness_m": _scalar(material.thickness),
                "scattering_coefficient": _scalar(material.scattering_coefficient),
                "source": expected["source"],
                "fallback_used": False,
                "is_used": bool(material.is_used),
            }
        )
    return {
        "schema_version": "1.0",
        "status": "provisional",
        "physically_validated": False,
        "strict_resolution": True,
        "fallback_policy": "none",
        "materials": records,
        "object_mapping": requested.get("object_mapping", []),
        "scene_object_count": len(manifest.get("objects", [])),
    }


def inspect_all_scene_materials(
    scene: Any, manifest: Dict[str, Any], requested: Dict[str, Any]
) -> Dict[str, Any]:
    """Record room and obstacle materials after Sionna evaluated frequency models."""

    expected_by_name = {
        value["actual_sionna_material_name"]: value
        for value in requested.get("materials", [])
    }
    records = []
    for name, material in scene.radio_materials.items():
        expected = expected_by_name.get(name)
        actual_type = getattr(material, "itu_type", None)
        if expected is not None and actual_type != expected["itu_type"]:
            raise MaterialResolutionError(
                "Material '{}'의 실제 ITU type '{}'가 요청 '{}'와 다릅니다.".format(
                    name, actual_type, expected["itu_type"]
                )
            )
        records.append(
            {
                "category": expected["category"] if expected else actual_type,
                "actual_sionna_material_name": name,
                "itu_type": actual_type,
                "class": material.__class__.__name__,
                "relative_permittivity": _scalar(material.relative_permittivity),
                "conductivity_s_per_m": _scalar(material.conductivity),
                "thickness_m": _scalar(material.thickness),
                "scattering_coefficient": _scalar(material.scattering_coefficient),
                "source": expected["source"] if expected else "phase2a_room_material",
                "fallback_used": False,
                "is_used": bool(material.is_used),
                "layer": "proxy_obstacle" if expected else "room_envelope",
            }
        )
    missing = sorted(set(expected_by_name) - set(scene.radio_materials))
    if missing:
        raise MaterialResolutionError(
            "Sionna scene에 obstacle material이 등록되지 않았습니다: {}".format(missing)
        )
    return {
        "schema_version": "1.0",
        "status": "provisional",
        "physically_validated": False,
        "strict_resolution": True,
        "fallback_policy": "none",
        "carrier_frequency_hz": _scalar(scene.frequency),
        "materials": records,
        "object_mapping": [
            {
                "object_name": value["object_name"],
                "layer": value.get("layer"),
                "category": value.get("source_material"),
                "radio_material": value["resolved_radio_material"],
            }
            for value in manifest.get("objects", [])
        ],
        "scene_object_count": len(manifest.get("objects", [])),
    }
