"""JSON 메타데이터를 안정적으로 읽고 쓴다."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


class MetadataError(ValueError):
    """메타데이터 형식이나 파일 접근에 문제가 있을 때 발생한다."""


def write_json(path: Path, data: Dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(output_path)
    except OSError as exc:
        raise MetadataError("JSON을 저장할 수 없습니다: {}".format(exc)) from exc


def read_json(path: Path) -> Dict[str, Any]:
    input_path = Path(path)
    if not input_path.is_file():
        raise MetadataError("JSON 파일을 찾을 수 없습니다: {}".format(input_path))
    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MetadataError("JSON을 읽을 수 없습니다: {}".format(exc)) from exc
    if not isinstance(data, dict):
        raise MetadataError("JSON 최상위 값은 키와 값의 모음이어야 합니다.")
    return data

