import copy

import pytest

from tools.proxy_mesh_editor.envelope.config import (
    DEFAULT_ENVELOPE_CONFIG,
    EnvelopeConfigError,
    validate_envelope_config,
)


def _configured():
    config = copy.deepcopy(DEFAULT_ENVELOPE_CONFIG)
    room = config["room_envelope"]
    room["floor"]["candidate_id"] = "plane_floor"
    room["ceiling"]["candidate_id"] = "plane_ceiling"
    room["ordered_walls"] = [
        {"candidate_id": "wall_000"},
        {"candidate_id": "wall_001"},
        {"candidate_id": "wall_002"},
    ]
    return config


def test_envelope_requires_three_unique_walls():
    config = _configured()
    config["room_envelope"]["ordered_walls"] = [
        {"candidate_id": "wall_000"},
        {"candidate_id": "wall_001"},
    ]
    with pytest.raises(EnvelopeConfigError, match="3개 이상"):
        validate_envelope_config(config)

    config = _configured()
    config["room_envelope"]["ordered_walls"][2]["candidate_id"] = "wall_000"
    with pytest.raises(EnvelopeConfigError, match="중복"):
        validate_envelope_config(config)


def test_invalid_interior_point_and_tolerance_are_rejected():
    config = _configured()
    config["room_envelope"]["interior_point"] = [0.0, float("nan"), 1.0]
    with pytest.raises(EnvelopeConfigError, match="interior_point"):
        validate_envelope_config(config)

    config = _configured()
    config["room_envelope"]["validation"]["plane_residual_tolerance"] = 0.0
    with pytest.raises(EnvelopeConfigError, match="양수"):
        validate_envelope_config(config)
