#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

exec conda run --no-capture-output -n pgsr \
  python -m tools.proxy_placement_editor.main edit \
  --room-obj outputs/proxy_mesh/pnu_classroom/metric_calibration/room_envelope_metric.obj \
  --room-json outputs/proxy_mesh/pnu_classroom/metric_calibration/room_envelope_metric.json \
  --calibration outputs/proxy_mesh/pnu_classroom/metric_calibration/calibration.json \
  --scenario configs/sionna/scenarios/pnu_classroom_proxy_draft.yaml \
  --reference-mesh PGSR/output/pnu_classroom/mesh/tsdf_fusion_post.ply \
  --reference-coordinate-space scene \
  --output outputs/proxy_placement/pnu_classroom \
  "$@"
