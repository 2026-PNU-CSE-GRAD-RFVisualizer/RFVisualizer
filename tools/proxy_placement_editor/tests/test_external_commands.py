from pathlib import Path

from tools.proxy_placement_editor.external_commands import (
    ExternalCommandRunner,
    ExternalEnvironment,
)


def test_scenario_build_command_includes_integrated_marker_contract(tmp_path: Path):
    runner = ExternalCommandRunner(ExternalEnvironment("current"), tmp_path)
    scenario = tmp_path / "scenario.yaml"
    markers = tmp_path / "tx_rx.json"
    output = tmp_path / "build"

    command = runner.scenario_command(
        "build", scenario, output, markers=markers
    )

    assert command == [
        "python",
        "-m",
        "tools.sionna_scenario.main",
        "build",
        "--scenario",
        str(scenario.resolve()),
        "--output",
        str(output.resolve()),
        "--markers",
        str(markers.resolve()),
    ]
