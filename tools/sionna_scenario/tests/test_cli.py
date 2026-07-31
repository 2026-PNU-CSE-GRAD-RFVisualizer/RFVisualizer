import json
from pathlib import Path

import tools.sionna_scenario.main as cli


def test_validate_cli_prints_machine_readable_success(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_scenario", lambda path: {"loaded": str(path)})
    monkeypatch.setattr(cli, "prepare_scenario", lambda document: document)
    monkeypatch.setattr(
        cli,
        "validation_summary",
        lambda prepared: {
            "scenario_id": "synthetic",
            "enabled_obstacle_count": 1,
            "success": True,
        },
    )

    assert cli.main(["validate", "--scenario", "scenario.yaml"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["scenario_id"] == "synthetic"
    assert result["success"] is True


def test_validate_cli_passes_optional_markers_to_scenario_preparation(
    monkeypatch, capsys
):
    captured = {}
    monkeypatch.setattr(cli, "load_scenario", lambda path: {"scenario": "loaded"})

    def prepare(document, markers):
        captured["document"] = document
        captured["markers"] = markers
        return object()

    monkeypatch.setattr(cli, "prepare_scenario", prepare)
    monkeypatch.setattr(
        cli,
        "validation_summary",
        lambda prepared: {"scenario_id": "field", "success": True},
    )

    assert (
        cli.main(
            [
                "validate",
                "--scenario",
                "scenario.yaml",
                "--markers",
                "tx_rx.json",
            ]
        )
        == 0
    )
    assert captured["document"] == {"scenario": "loaded"}
    assert captured["markers"] == Path("tx_rx.json")
    assert json.loads(capsys.readouterr().out)["success"] is True


def test_build_cli_reports_independent_object_counts(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(cli, "load_scenario", lambda path: {})
    monkeypatch.setattr(cli, "prepare_scenario", lambda document: object())
    monkeypatch.setattr(
        cli, "diagnose_environment", lambda: {"status": "unavailable"}
    )
    monkeypatch.setattr(
        cli,
        "build_scenario",
        lambda prepared, output: {
            "scenario_id": "synthetic",
            "status": "provisional",
            "scene_xml": str(tmp_path / "scene.xml"),
            "room_object_count": 6,
            "obstacle_object_count": 1,
            "total_triangle_count": 24,
        },
    )

    assert (
        cli.main(
            [
                "build",
                "--scenario",
                "scenario.yaml",
                "--output",
                str(tmp_path),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["room_object_count"] == 6
    assert result["obstacle_object_count"] == 1
    assert result["material_resolution"] == "deferred_until_sionna_runtime"
    assert result["scenario_manifest"] == str(
        (tmp_path / "scenario_manifest.json").resolve()
    )


def test_run_ab_cli_surfaces_los_and_coverage_evidence(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(cli, "load_experiment", lambda path: {})
    monkeypatch.setattr(
        cli,
        "run_ab_experiment",
        lambda document, output: {
            "validation": {
                "experiment_id": "phase2b_unit",
                "overall_success": True,
            },
            "path_comparison": {
                "rx_los": {
                    "baseline": {"los_path_exists": True},
                    "variant": {"los_path_exists": False},
                }
            },
            "coverage_comparison": {
                "common_valid_cell_count": 10,
                "mean_delta_db": -1.0,
                "mean_absolute_delta_db": 1.2,
                "maximum_absolute_delta_db": 5.0,
            },
        },
    )

    assert (
        cli.main(
            [
                "run-ab",
                "--experiment",
                "experiment.yaml",
                "--output",
                str(tmp_path),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["baseline_rx_los"] is True
    assert result["variant_rx_los"] is False
    assert result["common_valid_cells"] == 10
    assert result["maximum_absolute_delta_db"] == 5.0


def test_cli_expected_failure_returns_two_and_writes_diagnostic(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setattr(cli, "load_scenario", lambda path: {})
    monkeypatch.setattr(cli, "prepare_scenario", lambda document: object())
    monkeypatch.setattr(
        cli,
        "build_scenario",
        lambda prepared, output: (_ for _ in ()).throw(ValueError("invalid blocker")),
    )

    assert (
        cli.main(
            [
                "build",
                "--scenario",
                "scenario.yaml",
                "--output",
                str(tmp_path),
            ]
        )
        == 2
    )
    failure = json.loads(
        (tmp_path / "phase2b_failure.json").read_text(encoding="utf-8")
    )
    assert failure["status"] == "failure"
    assert failure["success"] is False
    assert failure["exception_type"] == "ValueError"
    assert failure["reason"] == "invalid blocker"
