"""Non-blocking invocation of the existing Phase 2-B CLI."""

from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional


@dataclass(frozen=True)
class ExternalEnvironment:
    type: str = "conda"
    name: str = "sionna"

    def prefix(self) -> List[str]:
        if self.type == "conda":
            return ["conda", "run", "-n", self.name]
        if self.type == "current":
            return []
        raise ValueError("external environment type은 conda/current만 지원합니다.")


class ExternalCommandRunner:
    def __init__(self, environment: ExternalEnvironment, project_root: Path):
        self.environment = environment
        self.project_root = Path(project_root).resolve()
        self.process: Optional[subprocess.Popen] = None

    def scenario_command(
        self,
        action: str,
        scenario: Path,
        output: Optional[Path] = None,
        markers: Optional[Path] = None,
    ) -> List[str]:
        if action not in {"validate", "build"}:
            raise ValueError("Scenario action은 validate/build만 지원합니다.")
        command = self.environment.prefix() + [
            "python",
            "-m",
            "tools.sionna_scenario.main",
            action,
            "--scenario",
            str(Path(scenario).resolve()),
        ]
        if action == "build":
            if output is None:
                raise ValueError("build output이 필요합니다.")
            command += ["--output", str(Path(output).resolve())]
        if markers is not None:
            command += ["--markers", str(Path(markers).resolve())]
        return command

    def experiment_command(self, experiment: Path, output: Path) -> List[str]:
        return self.environment.prefix() + [
            "python",
            "-m",
            "tools.sionna_scenario.main",
            "run-ab",
            "--experiment",
            str(Path(experiment).resolve()),
            "--output",
            str(Path(output).resolve()),
        ]

    def run_async(
        self,
        command: List[str],
        on_output: Callable[[str], None],
        on_complete: Callable[[int], None],
    ) -> threading.Thread:
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("이미 외부 명령이 실행 중입니다.")

        def worker() -> None:
            try:
                self.process = subprocess.Popen(
                    command,
                    cwd=str(self.project_root),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                assert self.process.stdout is not None
                for line in self.process.stdout:
                    on_output(line.rstrip())
                code = int(self.process.wait())
            except Exception as exc:
                on_output("External command error: {}".format(exc))
                code = 1
            on_complete(code)

        thread = threading.Thread(target=worker, name="phase2b-command", daemon=True)
        thread.start()
        return thread
