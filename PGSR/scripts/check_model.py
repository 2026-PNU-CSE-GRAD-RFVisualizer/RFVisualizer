"""재구성 결과가 쓸만한지 한눈에 본다.

reprojection error는 접힌 모델에서도 좋게 나오므로 믿지 않는다. 대신
궤적이 실제 걸은 경로(ㅁ자 한 바퀴)와 맞는지를 ratio로 본다.
ratio = 이동거리 / bbox둘레 이며, 한 바퀴면 1.0~1.5가 정상이고
2를 넘으면 복도가 자기 위로 접힌 것이다.

사용법:
    python scripts/check_model.py MODEL_OR_PARENT_DIR
"""
import glob
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "preprocess"))
from read_write_model import read_model  # noqa: E402


def report(model_dir):
    _, images, _ = read_model(model_dir, ext=".bin")
    names = [im.name for im in images.values()]
    n_fwd = sum(1 for n in names if n.startswith("fwd"))
    n_bwd = len(names) - n_fwd
    print(f"[{os.path.basename(model_dir)}] 총 {len(names)}장 (fwd {n_fwd}, bwd {n_bwd})")

    for prefix in ("fwd", "bwd"):
        items = sorted(((int(im.name.split("_")[1].split(".")[0]), -im.qvec2rotmat().T @ im.tvec)
                        for im in images.values() if im.name.startswith(prefix)), key=lambda x: x[0])
        if len(items) < 2:
            continue
        t = np.array([c for _, c in items])
        path = np.linalg.norm(np.diff(t, axis=0), axis=1).sum()
        bb = t.max(0) - t.min(0)
        per = 2 * (bb[0] + bb[2])
        ratio = path / per if per else float("nan")
        verdict = "정상" if ratio < 2.0 else "접힘 의심"
        print(f"   {prefix}: {len(t):4d}장  bbox={bb[0]:5.1f}x{bb[2]:5.1f}  ratio={ratio:4.2f}  -> {verdict}")


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    if os.path.isfile(os.path.join(target, "images.bin")):
        report(target)
        return
    subs = [d for d in sorted(glob.glob(os.path.join(target, "*")))
            if os.path.isfile(os.path.join(d, "images.bin"))]
    if not subs:
        raise SystemExit(f"{target} 에서 모델을 찾지 못함")
    for d in subs:
        report(d)
    if len(subs) > 1:
        print("\n조각이 여러 개다. 공유 이미지가 충분한 둘을 골라 합쳐야 한다:")
        sets = {}
        for d in subs:
            sets[d] = set(im.name for im in read_model(d, ext=".bin")[1].values())
        best = None
        for i, a in enumerate(subs):
            for b in subs[i + 1:]:
                shared = len(sets[a] & sets[b])
                print(f"   {os.path.basename(a)} + {os.path.basename(b)}: 공유 {shared}장"
                      f"{'  <- 합칠 수 있음' if shared >= 10 else ''}")
                if shared >= 10 and (best is None or shared > best[2]):
                    best = (a, b, shared)
        if best:
            print(f"\ncolmap model_merger --input_path1 {best[0]} --input_path2 {best[1]} "
                  f"--output_path {os.path.dirname(best[0])}/../merged")
        else:
            print("\n공유가 10장 미만이라 합칠 수 없다. "
                  "sequential_matcher를 --SequentialMatching.overlap 30 으로 다시 돌릴 것.")


if __name__ == "__main__":
    main()
