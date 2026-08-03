conda run --no-capture-output -n pgsr python -m tools.proxy_mesh_editor.main pick-envelope \
  --plane-candidates outputs/proxy_mesh/4f_corridor/phase1/plane_candidates.json \
  --wall-candidates outputs/proxy_mesh/4f_corridor/wall_extraction/wall_candidates.json \
  --envelope-config tools/proxy_mesh_editor/configs/4f_corridor_envelope.yaml \
  --output outputs/proxy_mesh/4f_corridor/room_envelope_picked \