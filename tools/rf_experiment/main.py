"""RFVisualizer 논문 실험 계약 검증 명령줄 도구."""

from __future__ import annotations

import argparse
import sys
from typing import List

from tools.sionna_smoke_test.coverage_test import CoverageTestError
from tools.sionna_smoke_test.metric_scene_loader import MetricSceneError
from tools.sionna_smoke_test.scene_exporter import SceneExportError

from .analysis import AnalysisError, run_analysis
from .contracts import (
    ContractError,
    validate_contract_bundle,
    validate_csv_contract,
    write_json_report,
)
from .dry_run import DryRunError, generate_synthetic_summary
from .proxy_scene import ProxySceneError, export_proxy_envelope
from .sionna_rssi import SionnaRssiError, run_sionna_rssi


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RFVisualizer 논문 실험 입력을 검증합니다.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    contracts = subparsers.add_parser(
        "validate-contracts", help="Scene, TX/RX, 분석 설정의 교차 계약을 확인합니다."
    )
    contracts.add_argument("--scene", required=True)
    contracts.add_argument("--markers", required=True)
    contracts.add_argument("--methods", required=True)
    contracts.add_argument(
        "--require-ready",
        action="store_true",
        help="현장 실행 가능한 ready 상태와 Marker 수를 요구합니다.",
    )

    csv_parser = subparsers.add_parser(
        "validate-csv", help="Backend Raw 또는 Summary CSV 계약을 확인합니다."
    )
    csv_parser.add_argument("--kind", required=True, choices=("raw", "summary"))
    csv_parser.add_argument("--csv", required=True)
    csv_parser.add_argument("--require-rows", action="store_true")

    proxy = subparsers.add_parser(
        "build-proxy-envelope",
        help="실측 가로·깊이·높이차로 양의 좌표계 기본 Envelope를 생성합니다.",
    )
    proxy.add_argument("--scene", required=True)
    proxy.add_argument(
        "--legacy-metric-json",
        default="outputs/proxy_mesh/pnu_classroom/metric_calibration/room_envelope_metric.json",
    )
    proxy.add_argument(
        "--legacy-calibration",
        default="outputs/proxy_mesh/pnu_classroom/metric_calibration/calibration.json",
    )
    proxy.add_argument("--output", required=True)

    analysis = subparsers.add_parser(
        "analyze",
        help="Raw Sionna, Plain IDW, Residual IDW의 수치·표·히트맵을 생성합니다.",
    )
    analysis.add_argument("--summary", required=True)
    analysis.add_argument("--sionna-points", required=True)
    analysis.add_argument("--sionna-grid", required=True)
    analysis.add_argument("--methods", required=True)
    analysis.add_argument("--output", required=True)

    sionna = subparsers.add_parser(
        "run-sionna",
        help="TX/RX 지점과 2D Grid의 Sionna RSSI(dBm)를 내보냅니다.",
    )
    sionna.add_argument("--scene", required=True)
    sionna.add_argument("--markers", required=True)
    sionna.add_argument("--solver", required=True)
    sionna.add_argument("--output", required=True)
    sionna.add_argument(
        "--scene-xml",
        help="장애물 포함 Scene을 미리 만들었을 때 사용할 선택적 scene.xml",
    )
    sionna.add_argument(
        "--allow-draft",
        action="store_true",
        help="초안 Scene/Marker로 Dry Run만 허용합니다.",
    )

    synthetic = subparsers.add_parser(
        "generate-synthetic-summary",
        help="Sionna 출력으로 분석 연결용 합성 Summary를 만듭니다.",
    )
    synthetic.add_argument("--sionna-points", required=True)
    synthetic.add_argument("--output", required=True)
    synthetic.add_argument("--residual-bias-db", type=float, default=4.0)
    return parser


def main(argv: List[str] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate-contracts":
            report = validate_contract_bundle(
                args.scene,
                args.markers,
                args.methods,
                require_ready=args.require_ready,
            )
        elif args.command == "validate-csv":
            report = validate_csv_contract(args.csv, args.kind, args.require_rows)
        elif args.command == "build-proxy-envelope":
            report = export_proxy_envelope(
                args.scene,
                args.legacy_metric_json,
                args.legacy_calibration,
                args.output,
            )
        elif args.command == "analyze":
            report = run_analysis(
                args.summary,
                args.sionna_points,
                args.sionna_grid,
                args.methods,
                args.output,
            )
        elif args.command == "run-sionna":
            report = run_sionna_rssi(
                args.scene,
                args.markers,
                args.solver,
                args.output,
                allow_draft=args.allow_draft,
                scene_xml_override=args.scene_xml,
            )
        else:
            report = generate_synthetic_summary(
                args.sionna_points,
                args.output,
                residual_bias_db=args.residual_bias_db,
            )
    except (
        AnalysisError,
        ContractError,
        MetricSceneError,
        ProxySceneError,
        CoverageTestError,
        DryRunError,
        SceneExportError,
        SionnaRssiError,
    ) as exc:
        print("계약 검증 실패: {}".format(exc), file=sys.stderr)
        return 2
    print(write_json_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
