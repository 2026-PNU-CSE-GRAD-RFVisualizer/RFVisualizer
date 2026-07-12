"""설정한 ITU 재질이 Sionna 장면에서 실제로 해석된 값을 기록한다."""

from __future__ import annotations

from typing import Any, Dict

import numpy as np


def _scalar(value):
    try:
        array = np.asarray(value.numpy()).reshape(-1)
    except AttributeError:
        array = np.asarray(value).reshape(-1)
    return float(array[0]) if len(array) else None


def resolve_materials(scene, manifest: Dict[str, Any]) -> Dict[str, Any]:
    records = []
    for name, material in scene.radio_materials.items():
        records.append(
            {
                "sionna_material_name": name,
                "class": material.__class__.__name__,
                "itu_type": getattr(material, "itu_type", None),
                "thickness_m": _scalar(material.thickness),
                "relative_permittivity": _scalar(material.relative_permittivity),
                "conductivity_s_per_m": _scalar(material.conductivity),
                "scattering_coefficient": _scalar(material.scattering_coefficient),
                "is_used": bool(material.is_used),
            }
        )
    return {
        "schema_version": "1.0",
        "status": manifest["status"],
        "physically_validated": False,
        "selection_reason": "설치된 Sionna RT의 공식 ITU concrete preset을 빈 방 연결 시험에 사용",
        "materials": records,
        "object_mapping": [
            {
                "object_name": value["object_name"],
                "semantic": value["semantic"],
                "radio_material": value["resolved_radio_material"],
            }
            for value in manifest["objects"]
        ],
    }
