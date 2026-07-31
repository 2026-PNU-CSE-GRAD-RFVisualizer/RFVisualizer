#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

exec conda run --no-capture-output -n pgsr \
  python -m tools.proxy_placement_editor.main edit \
  --room-obj outputs/proxy_mesh/4f_corridor/final_editor_proxy/room/room_envelope.obj \
  --room-json outputs/proxy_mesh/4f_corridor/final_editor_proxy/room/room_envelope.json \
  --calibration outputs/proxy_mesh/4f_corridor/final_editor_proxy/calibration.json \
  --scenario configs/sionna/scenarios/pnu_4f_corridor_proxy.yaml \
  --markers configs/rf_experiment/pnu_4f_corridor/tx_rx.json \
  --candidates configs/proxy_editor/pnu_4f_corridor_candidates.yaml \
  --editor-config configs/proxy_editor/pnu_4f_corridor_editor.yaml \
  --point-cloud PGSR/output/pnu_4f_corridor_v2/point_cloud/iteration_30000/point_cloud.ply \
  --point-cloud-coordinate-space scene \
  --pgsr-output-mesh PGSR/output/pnu_4f_corridor_v2/mesh/tsdf_fusion_post.ply \
  --pgsr-output-mesh-coordinate-space scene \
  --output outputs/proxy_placement/pnu_4f_corridor \
  "$@"
