import os

import pytest


@pytest.mark.skipif(
    os.environ.get("RUN_SIONNA_INTEGRATION") != "1",
    reason="RUN_SIONNA_INTEGRATION=1일 때만 실제 Sionna solver 통합 시험을 실행합니다.",
)
def test_actual_sionna_empty_scene_los_solver():
    pytest.importorskip("sionna.rt", reason="현재 Python 환경에 Sionna RT가 없습니다.")
    from sionna.rt import PathSolver, PlanarArray, Receiver, Transmitter, load_scene

    scene = load_scene()
    scene.tx_array = PlanarArray(num_rows=1, num_cols=1, pattern="iso", polarization="V")
    scene.rx_array = PlanarArray(num_rows=1, num_cols=1, pattern="iso", polarization="V")
    scene.add(Transmitter(name="tx", position=[0, 0, 0]))
    scene.add(Receiver(name="rx", position=[1, 0, 0]))
    paths = PathSolver()(scene, max_depth=0, los=True, specular_reflection=False)
    assert bool(paths.valid.numpy()[0, 0, 0])
