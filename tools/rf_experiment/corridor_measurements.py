"""복도 Test 1·2의 잘못 라벨링된 고정·이동 노드 측정 복원."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, Mapping, TypeVar

import numpy as np
from pydantic import BaseModel, ConfigDict


PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
TESTS_ROOT: Final = PROJECT_ROOT / "outputs/rf_experiment/pnu_4f_corridor/Tests"
MARKERS_PATH: Final = PROJECT_ROOT / "configs/rf_experiment/pnu_4f_corridor/tx_rx.json"
MOBILE_NODE: Final = "node-02"
NODE_TO_CALIBRATION: Final = {
    "gw-01": "cal-01",
    "node-01": "cal-02",
    "node-03": "cal-03",
    "node-04": "cal-04",
}

Role = Literal["calibration", "test"]
ModelT = TypeVar("ModelT", bound=BaseModel)


class RawRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    point_id: str
    point_role: str
    node_id: str
    rssi_raw_dbm: float | None
    rssi_filtered_dbm: float | None
    valid: bool


class OffsetNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str
    device_offset_db: float


class OffsetDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    nodes: tuple[OffsetNode, ...]


class Receiver(BaseModel):
    model_config = ConfigDict(frozen=True)

    point_id: str
    position_m: tuple[float, float, float]


class MarkerDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    rx: tuple[Receiver, ...]


class Measurement(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    point_id: str
    role: Role
    node_id: str
    x: float
    y: float
    z: float
    sample_count: int
    median_raw: float
    median_filtered: float
    mean_filtered: float
    std_filtered: float
    iqr_filtered: float
    device_offset_db: float
    corrected_rssi: float


@dataclass(frozen=True, slots=True)
class MeasurementSite:
    point_id: str
    role: Role
    node_id: str
    position: tuple[float, float, float]
    offset: float


@dataclass(frozen=True, slots=True)
class MissingSamplesError(Exception):
    run_id: str
    point_id: str
    node_id: str

    def __str__(self) -> str:
        return (
            f"{self.run_id} {self.point_id} {self.node_id}: 유효 RSSI 표본이 없습니다."
        )


def _read_csv(path: Path, model: type[ModelT]) -> tuple[ModelT, ...]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return tuple(model.model_validate(row) for row in csv.DictReader(handle))


def marker_positions() -> Mapping[str, tuple[float, float, float]]:
    document = MarkerDocument.model_validate_json(
        MARKERS_PATH.read_text(encoding="utf-8")
    )
    return {receiver.point_id: receiver.position_m for receiver in document.rx}


def _summarize(
    run_id: str,
    site: MeasurementSite,
    rows: tuple[RawRow, ...],
) -> Measurement:
    raw = np.asarray([row.rssi_raw_dbm for row in rows], dtype=float)
    filtered = np.asarray([row.rssi_filtered_dbm for row in rows], dtype=float)
    if len(filtered) == 0:
        raise MissingSamplesError(
            run_id=run_id,
            point_id=site.point_id,
            node_id=site.node_id,
        )
    return Measurement(
        run_id=run_id,
        point_id=site.point_id,
        role=site.role,
        node_id=site.node_id,
        x=site.position[0],
        y=site.position[1],
        z=site.position[2],
        sample_count=len(filtered),
        median_raw=float(np.median(raw)),
        median_filtered=float(np.median(filtered)),
        mean_filtered=float(np.mean(filtered)),
        std_filtered=float(np.std(filtered, ddof=1)),
        iqr_filtered=float(np.percentile(filtered, 75) - np.percentile(filtered, 25)),
        device_offset_db=site.offset,
        corrected_rssi=float(np.median(filtered) + site.offset),
    )


def load_run(run_id: str) -> tuple[Measurement, ...]:
    directory = TESTS_ROOT / run_id
    raw_rows = _read_csv(directory / "raw/measurements_raw.csv", RawRow)
    usable = tuple(
        row
        for row in raw_rows
        if row.valid
        and row.rssi_raw_dbm is not None
        and row.rssi_filtered_dbm is not None
    )
    offsets = OffsetDocument.model_validate_json(
        (directory / "config/device_offsets.json").read_text(encoding="utf-8")
    )
    offset_by_node = {row.node_id: row.device_offset_db for row in offsets.nodes}
    positions = marker_positions()
    measurements = []
    for node_id, point_id in NODE_TO_CALIBRATION.items():
        rows = tuple(
            row
            for row in usable
            if row.node_id == node_id and row.point_role in {"calibration", "test"}
        )
        measurements.append(
            _summarize(
                run_id,
                MeasurementSite(
                    point_id=point_id,
                    role="calibration",
                    node_id=node_id,
                    position=positions[point_id],
                    offset=offset_by_node[node_id],
                ),
                rows,
            )
        )
    for index in range(1, 7):
        point_id = f"test-{index:02d}"
        rows = tuple(
            row
            for row in usable
            if row.node_id == MOBILE_NODE
            and row.point_role == "test"
            and row.point_id == point_id
        )
        measurements.append(
            _summarize(
                run_id,
                MeasurementSite(
                    point_id=point_id,
                    role="test",
                    node_id=MOBILE_NODE,
                    position=positions[point_id],
                    offset=offset_by_node[MOBILE_NODE],
                ),
                rows,
            )
        )
    return tuple(measurements)
