#!/usr/bin/env python3
"""PGSR output 폴더 하나로 TUTORIAL.md 5.1~5.4를 이어서 실행한다.

사용법:
    conda run -n pgsr python scripts/init_proxy_mesh.py <pgsr_output_dir> \\
        [--scene-id ID] [--up-vector X Y Z] [--skip-picker] [--force]

예:
    conda run -n pgsr python scripts/init_proxy_mesh.py PGSR/output/pnu_3f_corridor \\
        --up-vector 0.0 0.0 1.0

수행 단계:
    5.1  scenes/<scene_id>/configs/proxy_mesh/를 scenes/_template/에서 복사 (이미 있으면 건너뜀)
    5.2  extract   (평면 후보 추출)
    5.3  analyze-normals + extract-walls (벽 후보 추출)
    5.4  pick-envelope를 곧바로 실행 (--skip-picker면 명령만 출력)

5.4는 사람이 3D Viewer에서 바닥·천장·벽을 직접 골라야 하므로 완전히 자동화할 수
없다. 이 스크립트는 그 직전까지의 반복 작업(폴더 생성, 설정 복사, extract류 3개
명령 실행)만 대신하고, 마지막 pick-envelope는 그대로 사람이 조작한다.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = REPO_ROOT / "scenes/_template/configs/proxy_mesh"


def _latest_point_cloud(pgsr_dir: Path) -> Path:
    candidates = sorted(
        pgsr_dir.glob("point_cloud/iteration_*/point_cloud.ply"),
        key=lambda path: int(path.parent.name.replace("iteration_", "")),
    )
    if not candidates:
        raise SystemExit(f"오류: {pgsr_dir}에 point_cloud/iteration_*/point_cloud.ply가 없습니다.")
    return candidates[-1]


def _run(command: list[str]) -> None:
    print("+ " + " ".join(str(part) for part in command))
    result = subprocess.run(command, cwd=REPO_ROOT, check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pgsr_output_dir", type=Path, help="예: PGSR/output/pnu_3f_corridor")
    parser.add_argument("--scene-id", help="기본값: pgsr_output_dir의 폴더 이름")
    parser.add_argument("--up-vector", nargs=3, type=float, metavar=("X", "Y", "Z"), help="base.yaml의 scene.up_vector를 이 값으로 바꾼다")
    parser.add_argument("--skip-picker", action="store_true", help="5.4 pick-envelope를 실행하지 않고 명령만 출력한다")
    parser.add_argument("--force", action="store_true", help="이미 있는 5.2/5.3 결과도 다시 만든다")
    args = parser.parse_args(argv)

    pgsr_dir = (REPO_ROOT / args.pgsr_output_dir).resolve()
    mesh_path = pgsr_dir / "mesh/tsdf_fusion_post.ply"
    if not mesh_path.is_file():
        raise SystemExit(f"오류: {mesh_path}가 없습니다. PGSR 학습·Mesh 추출(4절)을 먼저 끝낸다.")
    point_cloud_path = _latest_point_cloud(pgsr_dir)

    scene_id = args.scene_id or pgsr_dir.name
    scene_root = REPO_ROOT / "scenes" / scene_id
    config_dir = scene_root / "configs/proxy_mesh"
    base_yaml = config_dir / "base.yaml"

    # 5.1
    if config_dir.is_dir():
        print(f"[5.1] {config_dir} 가 이미 있어 복사를 건너뜁니다.")
    else:
        config_dir.mkdir(parents=True)
        for template_file in TEMPLATE_DIR.glob("*.yaml"):
            shutil.copy2(template_file, config_dir / template_file.name)
        print(f"[5.1] {TEMPLATE_DIR} -> {config_dir}")
        if args.up_vector:
            text = base_yaml.read_text(encoding="utf-8")
            old_line = next(line for line in text.splitlines() if line.strip().startswith("up_vector:"))
            new_line = "  up_vector: [{}, {}, {}]".format(*args.up_vector)
            base_yaml.write_text(text.replace(old_line, new_line), encoding="utf-8")
            print(f"[5.1] up_vector -> {list(args.up_vector)}")
        else:
            print("[5.1] --up-vector를 지정하지 않았다. base.yaml의 scene.up_vector가 실제 위쪽인지 직접 확인한다.")

    proxy_mesh_root = scene_root / "proxy_mesh"
    phase1_dir = proxy_mesh_root / "phase1"
    normal_analysis_dir = proxy_mesh_root / "normal_analysis"
    wall_extraction_dir = proxy_mesh_root / "wall_extraction"

    # 5.2
    if not args.force and (phase1_dir / "plane_candidates.json").is_file():
        print(f"[5.2] {phase1_dir}/plane_candidates.json 가 이미 있어 건너뜁니다. (--force로 재실행)")
    else:
        _run([
            sys.executable, "-m", "tools.proxy_mesh_editor.main", "extract",
            "--mesh", str(mesh_path),
            "--reference-point-cloud", str(point_cloud_path),
            "--config", str(base_yaml),
            "--output", str(phase1_dir),
        ])

    # 5.3
    if not args.force and (normal_analysis_dir / "normal_analysis.json").is_file():
        print(f"[5.3] {normal_analysis_dir} 가 이미 있어 건너뜁니다. (--force로 재실행)")
    else:
        _run([
            sys.executable, "-m", "tools.proxy_mesh_editor.main", "analyze-normals",
            "--mesh", str(mesh_path),
            "--reference-point-cloud", str(point_cloud_path),
            "--config", str(base_yaml),
            "--output", str(normal_analysis_dir),
        ])

    if not args.force and (wall_extraction_dir / "wall_candidates.json").is_file():
        print(f"[5.3] {wall_extraction_dir}/wall_candidates.json 가 이미 있어 건너뜁니다. (--force로 재실행)")
    else:
        _run([
            sys.executable, "-m", "tools.proxy_mesh_editor.main", "extract-walls",
            "--mesh", str(mesh_path),
            "--reference-point-cloud", str(point_cloud_path),
            "--config", str(base_yaml),
            "--output", str(wall_extraction_dir),
        ])

    # 5.4
    pick_command = [
        sys.executable, "-m", "tools.proxy_mesh_editor.main", "pick-envelope",
        "--plane-candidates", str(phase1_dir / "plane_candidates.json"),
        "--wall-candidates", str(wall_extraction_dir / "wall_candidates.json"),
        "--envelope-config", str(config_dir / "envelope.yaml"),
        "--output", str(proxy_mesh_root / "room_envelope"),
    ]
    if args.skip_picker:
        print("\n[5.4] 다음 명령으로 3D Viewer에서 바닥·천장·벽을 고른다:")
        print("  " + " ".join(str(part) for part in pick_command))
        return 0

    print("\n[5.4] pick-envelope 실행 (3D Viewer가 열립니다)")
    _run(pick_command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
