import json

import numpy as np

from tools.proxy_mesh_editor.rebuild_4f_corridor_proxy import (
    Y_MAX_M,
    _finalize_metadata,
)


def test_finalize_metadata_removes_explicit_y_reflection_from_pgsr_transform(tmp_path):
    output = tmp_path / "final_editor_proxy"
    room = output / "room"
    room.mkdir(parents=True)

    mirrored = np.eye(4)
    mirrored[1, 1] = -1.0
    mirrored[1, 3] = Y_MAX_M
    transform = {
        "alignment_type": "orthogonal_similarity_with_explicit_y_reflection",
        "reflection_reason": "regression fixture",
        "T_metric_from_scene": mirrored.tolist(),
        "T_scene_from_metric": mirrored.tolist(),
        "linear_determinant": -1.0,
        "orthogonal_basis_determinant": -1.0,
        "source_x_axis": [1.0, 0.0, 0.0],
        "source_y_axis": [0.0, -1.0, 0.0],
        "source_z_axis_floor_normal": [0.0, 0.0, 1.0],
        "origin_scene_coordinate": [0.0, Y_MAX_M, 0.0],
        "origin_metric_coordinate": [0.0, 0.0, 0.0],
    }
    (room / "room_envelope.json").write_text("{}", encoding="utf-8")
    (room / "topology_report.json").write_text(
        json.dumps({"success": True, "topology": {}, "geometry": {}}),
        encoding="utf-8",
    )
    (output / "calibration.json").write_text(
        json.dumps({"transform": transform, "geometry": {}}),
        encoding="utf-8",
    )

    _finalize_metadata(output)

    calibration = json.loads((output / "calibration.json").read_text(encoding="utf-8"))
    corrected = calibration["transform"]
    np.testing.assert_allclose(corrected["T_metric_from_scene"], np.eye(4))
    assert corrected["linear_determinant"] > 0.0
    assert corrected["orthogonal_basis_determinant"] > 0.0
    assert corrected["alignment_type"] == "orthogonal_similarity_proper_rotation"
    assert "reflection_reason" not in corrected
