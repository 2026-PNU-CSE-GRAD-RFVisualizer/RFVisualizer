#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

exec conda run --no-capture-output -n pgsr \
  python -m tools.proxy_placement_editor.main edit \
  --room-obj outputs/rf_experiment/classroom_20260723/proxy_scene/room_envelope_metric.obj \
  --room-json outputs/rf_experiment/classroom_20260723/proxy_scene/room_envelope_metric.json \
  --calibration outputs/rf_experiment/classroom_20260723/proxy_scene/calibration.json \
  --scenario configs/sionna/scenarios/pnu_classroom_field_20260723.yaml \
  --markers configs/rf_experiment/classroom_20260723/tx_rx.json \
  --point-cloud PGSR/output/pnu_classroom/point_cloud/iteration_30000/point_cloud.ply \
  --point-cloud-coordinate-space scene \
  --pgsr-output-mesh PGSR/output/pnu_classroom/mesh/tsdf_fusion_post.ply \
  --pgsr-output-mesh-coordinate-space scene \
  --pgsr-output-mesh-full-resolution \
  --output outputs/proxy_placement/classroom_20260723 \
  "$@"
