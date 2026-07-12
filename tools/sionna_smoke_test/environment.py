"""Sionna RT, GPU, Mitsuba와 계산 뒷단의 실제 설치 상태를 진단한다."""

from __future__ import annotations

import importlib.metadata as metadata
import importlib.util
import platform
import subprocess
import sys
from typing import Any, Dict


def _version(*names: str):
    for name in names:
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return None


def _gpu_info() -> Dict[str, Any]:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total,memory.used",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        rows = []
        for line in result.stdout.strip().splitlines():
            name, driver, total, used = [value.strip() for value in line.split(",")]
            rows.append(
                {
                    "name": name,
                    "driver_version": driver,
                    "memory_total_mib": int(total),
                    "memory_used_mib": int(used),
                }
            )
        return {"nvidia_smi_available": True, "gpus": rows}
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return {"nvidia_smi_available": False, "gpus": [], "reason": str(exc)}


def diagnose_environment() -> Dict[str, Any]:
    try:
        sionna_rt_importable = importlib.util.find_spec("sionna.rt") is not None
    except (ImportError, ModuleNotFoundError):
        sionna_rt_importable = False
    result: Dict[str, Any] = {
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "packages": {
            "sionna": _version("sionna", "sionna-rt"),
            "sionna_rt_distribution": _version("sionna-rt"),
            "mitsuba": _version("mitsuba"),
            "drjit": _version("drjit"),
            "tensorflow": _version("tensorflow"),
            "jax": _version("jax"),
        },
        "gpu": _gpu_info(),
        "sionna_rt_importable": sionna_rt_importable,
    }
    if not result["sionna_rt_importable"]:
        result.update(
            {
                "status": "unavailable",
                "reason": "현재 Python 환경에서 sionna.rt를 찾을 수 없습니다.",
                "recommended_action": (
                    "전용 환경에서 `python -m pip install sionna-rt PyYAML` 후 다시 실행하세요."
                ),
            }
        )
        return result
    try:
        import drjit as dr
        import mitsuba as mi
        import sionna
        import sionna.rt as rt

        result["sionna_module_version"] = getattr(sionna, "__version__", None)
        result["mitsuba_variant"] = mi.variant()
        result["mitsuba_variants"] = list(mi.variants())
        result["drjit_backends"] = {
            "cuda": bool(dr.has_backend(dr.JitBackend.CUDA)),
            "llvm": bool(dr.has_backend(dr.JitBackend.LLVM)),
        }
        result["gpu_backend_active"] = bool(
            mi.variant() is not None and str(mi.variant()).startswith("cuda_")
        )
        result["api"] = {
            name: hasattr(rt, name)
            for name in (
                "load_scene",
                "PathSolver",
                "RadioMapSolver",
                "Transmitter",
                "Receiver",
                "PlanarArray",
            )
        }
        try:
            import tensorflow as tf

            result["tensorflow_backend"] = {
                "importable": True,
                "physical_gpus": [device.name for device in tf.config.list_physical_devices("GPU")],
            }
        except Exception as exc:  # TensorFlow 진단 실패는 Sionna RT 실패와 분리한다.
            result["tensorflow_backend"] = {"importable": False, "reason": repr(exc)}
        required = all(result["api"].values())
        result["status"] = "available" if required else "unavailable"
        if not required:
            result["reason"] = "설치된 Sionna RT에 필요한 API가 없습니다."
            result["recommended_action"] = "Sionna RT 1.2 이상으로 환경을 갱신하세요."
    except Exception as exc:
        result.update(
            {
                "status": "unavailable",
                "reason": repr(exc),
                "recommended_action": "Sionna/Mitsuba/Dr.Jit 설치와 CUDA 드라이버를 확인하세요.",
            }
        )
    return result
