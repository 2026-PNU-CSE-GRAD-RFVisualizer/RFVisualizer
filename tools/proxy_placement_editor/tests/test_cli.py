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
                / "configs/sionna/scenarios/pnu_classroom_synthetic_blocker.yaml"
            ),
            "--room-json",
            str(
                project_root
                / "outputs/proxy_mesh/pnu_classroom/metric_calibration/room_envelope_metric.json"
            ),
            "--calibration",
            str(
                project_root
                / "outputs/proxy_mesh/pnu_classroom/metric_calibration/calibration.json"
            ),
        ]
    )
    assert code == 0
    assert '"success": true' in capsys.readouterr().out


def test_edit_without_display_fails_clearly(project_root, tmp_path, monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    code = main(
        [
            "edit",
            "--room-obj",
            str(
                project_root
                / "outputs/proxy_mesh/pnu_classroom/metric_calibration/room_envelope_metric.obj"
            ),
            "--room-json",
            str(
                project_root
                / "outputs/proxy_mesh/pnu_classroom/metric_calibration/room_envelope_metric.json"
            ),
            "--calibration",
            str(
                project_root
                / "outputs/proxy_mesh/pnu_classroom/metric_calibration/calibration.json"
            ),
            "--scenario",
            str(
                project_root / "configs/sionna/scenarios/pnu_classroom_proxy_draft.yaml"
            ),
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
