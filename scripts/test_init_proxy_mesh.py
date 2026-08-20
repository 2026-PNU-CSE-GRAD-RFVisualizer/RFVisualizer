import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from init_proxy_mesh import _latest_point_cloud  # noqa: E402


def test_latest_point_cloud_picks_highest_iteration_number(tmp_path):
    for iteration in (7000, 30000, 15000):
        directory = tmp_path / f"point_cloud/iteration_{iteration}"
        directory.mkdir(parents=True)
        (directory / "point_cloud.ply").write_text("")

    result = _latest_point_cloud(tmp_path)

    assert result == tmp_path / "point_cloud/iteration_30000/point_cloud.ply"


def test_latest_point_cloud_missing_raises(tmp_path):
    try:
        _latest_point_cloud(tmp_path)
    except SystemExit:
        return
    raise AssertionError("point_cloud가 없으면 SystemExit이 나야 한다.")
