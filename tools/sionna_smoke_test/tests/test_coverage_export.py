from pathlib import Path

import numpy as np

from tools.sionna_smoke_test.coordinate_bridge import CoordinateBridge
from tools.sionna_smoke_test.exporter import export_coverage


def test_synthetic_coverage_exports_numpy_csv_png_and_metadata(tmp_path: Path):
    identity = np.eye(4).tolist()
    bridge = CoordinateBridge.from_calibration(
        {"transform": {"T_metric_from_scene": identity, "T_scene_from_metric": identity}}
    )
    centers = np.asarray(
        [[[0.5, 0.5, 1.5], [1.5, 0.5, 1.5]], [[0.5, 1.5, 1.5], [1.5, 1.5, 1.5]]]
    )
    result = {
        "values": np.asarray([[1e-4, 2e-4], [3e-4, 4e-4]]),
        "centers": centers,
        "inside_mask": np.asarray([[True, True], [True, False]]),
        "valid_mask": np.asarray([[True, True], [True, False]]),
        "metadata": {"success": True, "grid_shape_yx": [2, 2]},
    }
    positions = [
        {"kind": "transmitter", "name": "tx", "resolved_position_m": [0.5, 0.5, 1.5]}
    ]
    files = export_coverage(result, bridge, positions, tmp_path)
    for value in files.values():
        assert Path(value).is_file()
    saved = np.load(tmp_path / "coverage" / "coverage_values.npy")
    assert np.isnan(saved[1, 1])
    assert (tmp_path / "coverage" / "coverage_points_scene.csv").read_text().count("\n") == 5
