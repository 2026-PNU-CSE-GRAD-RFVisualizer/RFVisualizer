import json
from types import SimpleNamespace

from tools.proxy_placement_editor import main as placement_main
from tools.proxy_placement_editor.main import main


def test_validate_cli_headless(project_root, capsys):
    code = main(
        [
            "validate",
            "--scenario",
            str(
                project_root
                / "scenes/pnu_classroom/configs/sionna/synthetic_blocker.yaml"
            ),
            "--room-json",
            str(
                project_root
                / "scenes/pnu_classroom/proxy_mesh/metric_calibration/room_envelope_metric.json"
            ),
            "--calibration",
            str(
                project_root
                / "scenes/pnu_classroom/proxy_mesh/metric_calibration/calibration.json"
            ),
            "--candidates",
            str(project_root / "scenes/pnu_classroom/configs/proxy_editor/candidates.yaml"),
        ]
    )
    assert code == 0
    assert '"success": true' in capsys.readouterr().out


def test_existing_marker_tx_is_loaded_at_its_saved_position(
    project_root, tmp_path
):
    marker_path = tmp_path / "tx_rx.json"
    marker_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "scene_id": "pnu_classroom_empty",
                "coordinate_system_id": "pnu_classroom_metric_v1",
                "status": "draft",
                "requirements": {
                    "transmitter_count": 1,
                    "calibration_receiver_count": 0,
                    "test_receiver_count": 0,
                },
                "tx": [
                    {
                        "id": "tx_saved",
                        "name": "Saved TX",
                        "position_m": [-7.0, -5.0, 1.5],
                        "frequency_hz": 2.4e9,
                        "power_dbm": 20.0,
                    }
                ],
                "rx": [],
            }
        ),
        encoding="utf-8",
    )
    room = project_root / "scenes/pnu_classroom/proxy_mesh/metric_calibration"
    core = placement_main._create_core(
        SimpleNamespace(
            command="validate",
            scenario=project_root
            / "scenes/pnu_classroom/configs/sionna/empty.yaml",
            room_obj=room / "room_envelope_metric.obj",
            room_json=room / "room_envelope_metric.json",
            calibration=room / "calibration.json",
            candidates=project_root
            / "scenes/pnu_classroom/configs/proxy_editor/candidates.yaml",
            markers=marker_path,
            output=tmp_path / "output",
            point_cloud=None,
            pgsr_output_mesh=None,
            reference_mesh=None,
        )
    )

    transmitter = core.state.get_object("tx_saved")
    assert transmitter["display_name"] == "Saved TX"
    assert transmitter["enabled"] is True
    assert [
        transmitter["geometry"]["position_m"][axis]
        for axis in ("x", "y", "z")
    ] == [-7.0, -5.0, 1.5]
    assert core.validate()["success"]


def test_edit_without_display_fails_clearly(project_root, tmp_path, monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    code = main(
        [
            "edit",
            "--room-obj",
            str(
                project_root
                / "scenes/pnu_classroom/proxy_mesh/metric_calibration/room_envelope_metric.obj"
            ),
            "--room-json",
            str(
                project_root
                / "scenes/pnu_classroom/proxy_mesh/metric_calibration/room_envelope_metric.json"
            ),
            "--calibration",
            str(
                project_root
                / "scenes/pnu_classroom/proxy_mesh/metric_calibration/calibration.json"
            ),
            "--scenario",
            str(
                project_root / "scenes/pnu_classroom/configs/sionna/proxy_draft.yaml"
            ),
            "--candidates",
            str(project_root / "scenes/pnu_classroom/configs/proxy_editor/candidates.yaml"),
            "--output",
            str(tmp_path),
        ]
    )
    assert code == 2


def test_native_gui_crash_retries_with_software_rendering(monkeypatch, tmp_path):
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.delenv(placement_main.GUI_WORKER_ENV, raising=False)
    monkeypatch.delenv("LIBGL_ALWAYS_SOFTWARE", raising=False)
    monkeypatch.setattr(placement_main, "_compatible_gui_python", lambda: None)
    calls = []
    return_codes = iter((-11, 0))

    def fake_run(command, env, check):
        calls.append((command, env, check))
        return SimpleNamespace(returncode=next(return_codes))

    monkeypatch.setattr(placement_main.subprocess, "run", fake_run)
    args = SimpleNamespace(
        software_rendering=False,
        _raw_argv=["edit"],
        output=tmp_path,
    )
    assert placement_main.command_edit(args) == 0
    assert len(calls) == 2
    assert calls[1][1]["LIBGL_ALWAYS_SOFTWARE"] == "true"
    assert calls[1][1][placement_main.SOFTWARE_RENDERING_ENV] == "1"


def test_compatible_gui_runtime_is_preferred(monkeypatch, tmp_path):
    monkeypatch.setenv("DISPLAY", ":1")
    monkeypatch.delenv(placement_main.GUI_WORKER_ENV, raising=False)
    compatible_python = tmp_path / "editor-runtime/bin/python"
    monkeypatch.setattr(
        placement_main, "_compatible_gui_python", lambda: compatible_python
    )
    calls = []

    def fake_run(command, env, check):
        calls.append((command, env, check))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(placement_main.subprocess, "run", fake_run)
    args = SimpleNamespace(
        software_rendering=False,
        _raw_argv=["edit"],
        output=tmp_path,
    )
    assert placement_main.command_edit(args) == 0
    assert len(calls) == 1
    assert calls[0][0][0] == str(compatible_python)
    assert calls[0][1][placement_main.GUI_WORKER_ENV] == "1"


def test_setup_gui_runtime_uses_thin_pinned_environment(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="0.18.0\n")

    monkeypatch.setattr(placement_main.subprocess, "run", fake_run)
    runtime = tmp_path / "runtime"
    args = SimpleNamespace(runtime_dir=runtime)
    assert placement_main.command_setup_gui_runtime(args) == 0
    assert calls[0][0][1:4] == ["-m", "venv", "--system-site-packages"]
    assert placement_main.COMPATIBLE_OPEN3D_PACKAGE in calls[1][0]
    assert '"open3d_version": "0.18.0"' in capsys.readouterr().out


def test_edit_and_export_preview_share_default_pgsr_mesh_cache(tmp_path):
    source = tmp_path / "mesh.ply"
    edit_args = SimpleNamespace(
        command="edit",
        pgsr_output_mesh=source,
        pgsr_output_mesh_preview=None,
        output=tmp_path / "session",
    )
    preview_args = SimpleNamespace(
        command="export-preview",
        pgsr_output_mesh=source,
        pgsr_output_mesh_preview=None,
        output=tmp_path / "session" / "preview",
    )
    assert placement_main._pgsr_mesh_preview_path(
        edit_args
    ) == placement_main._pgsr_mesh_preview_path(preview_args)


def test_pgsr_mesh_preview_default_targets_high_quality_cache():
    args = placement_main.build_parser().parse_args(
        [
            "prepare-pgsr-mesh-preview",
            "--source",
            "source.ply",
            "--output",
            "preview.ply",
        ]
    )
    assert args.maximum_triangles == 1_000_000


def test_edit_accepts_full_resolution_pgsr_mesh_flag():
    args = placement_main.build_parser().parse_args(
        [
            "edit",
            "--room-obj",
            "room.obj",
            "--room-json",
            "room.json",
            "--calibration",
            "calibration.json",
            "--scenario",
            "scenario.yaml",
            "--candidates",
            "candidates.yaml",
            "--pgsr-output-mesh",
            "mesh.ply",
            "--pgsr-output-mesh-full-resolution",
            "--output",
            "output",
        ]
    )

    assert args.pgsr_output_mesh_full_resolution is True
