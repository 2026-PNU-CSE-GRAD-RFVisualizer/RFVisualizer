#!/usr/bin/env python3
"""씬 레지스트리(scenes/**/scene.yaml)를 읽어 tools.<package>.main을 실행한다.

사용법:
    python scripts/run_scene.py <scene_id> <package> <subcommand> [-- 추가 인자...]

예:
    python scripts/run_scene.py <scene_id> proxy_placement_editor edit --software-rendering
    python scripts/run_scene.py <session_id> proxy_placement_editor validate
    python scripts/run_scene.py <scene_id> rf_experiment validate-contracts

scene.yaml의 tools.<package>.<subcommand> 아래 각 키는 그대로 --key 플래그가 된다
(값이 true인 항목은 store_true 플래그로, false/생략은 플래그 자체를 뺀다).
뒤에 붙이는 추가 인자는 그대로 전달되며, argparse는 같은 플래그가 반복되면 마지막
값을 쓰므로 레지스트리 값을 임시로 덮어쓰고 싶을 때 그대로 다시 넘기면 된다.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def _find_scene(scene_id: str) -> Dict[str, Any]:
    matches = []
    for path in sorted((REPO_ROOT / "scenes").glob("**/scene.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if document.get("id") == scene_id:
            matches.append((path, document))
    if not matches:
        raise SystemExit(f"오류: scenes/**/scene.yaml 중 id: {scene_id} 를 찾지 못했습니다.")
    if len(matches) > 1:
        found = ", ".join(str(path.relative_to(REPO_ROOT)) for path, _ in matches)
        raise SystemExit(f"오류: id: {scene_id} 가 여러 scene.yaml에 중복됩니다: {found}")
    return matches[0][1]


def _flags_from_registry(flag_map: Dict[str, Any]) -> list[str]:
    args: list[str] = []
    for key, value in flag_map.items():
        if isinstance(value, bool):
            if value:
                args.append(f"--{key}")
            continue
        args.extend([f"--{key}", str(value)])
    return args


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    scene_id, package, subcommand, *passthrough = argv

    scene = _find_scene(scene_id)
    try:
        flag_map = scene["tools"][package][subcommand]
    except KeyError:
        raise SystemExit(
            "오류: scene '{}'에 tools.{}.{} 항목이 없습니다.".format(
                scene_id, package, subcommand
            )
        )

    command = [
        sys.executable,
        "-m",
        f"tools.{package}.main",
        subcommand,
        *_flags_from_registry(flag_map),
        *passthrough,
    ]
    return subprocess.run(command, cwd=REPO_ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
