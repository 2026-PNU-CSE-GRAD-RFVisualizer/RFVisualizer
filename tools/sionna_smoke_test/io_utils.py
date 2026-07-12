"""Phase 2-A 산출물을 안전하게 저장하는 공통 함수."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


class SmokeTestIOError(RuntimeError):
    """입출력 파일을 읽거나 쓸 수 없을 때 발생한다."""


def read_json(path: Path) -> Dict[str, Any]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise SmokeTestIOError("JSON 파일을 찾을 수 없습니다: {}".format(source))
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SmokeTestIOError("JSON 파일을 읽을 수 없습니다: {}".format(exc)) from exc
    if not isinstance(value, dict):
        raise SmokeTestIOError("JSON 최상위 값은 키와 값의 모음이어야 합니다.")
    return value


def write_json(path: Path, value: Dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(output)
    except OSError as exc:
        raise SmokeTestIOError("JSON 파일을 저장할 수 없습니다: {}".format(exc)) from exc


def atomic_write_text(path: Path, text: str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(output)
    except OSError as exc:
        raise SmokeTestIOError("텍스트 파일을 저장할 수 없습니다: {}".format(exc)) from exc
