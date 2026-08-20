"""fwd/bwd 두 영상에서 '같은 장소'일 법한 이미지 쌍만 뽑아낸다.

두 영상이 같은 루프를 반대 방향으로 돌고 같은 지점에서 시작/종료한다는 사실을 이용해,
루프 진행률로 대응을 잡는다. bwd 진행률 s 지점은 fwd 진행률 (1 - s) 지점과 같은 장소다.

fwd 쪽은 재구성 모델의 누적 이동거리(arc length)를 쓰고, bwd 쪽은 모델이 있으면 arc length,
없으면 프레임 번호 비율을 쓴다. 프레임 번호는 걷는 속도가 일정하다는 가정이라 다소 부정확하지만
window 안에서 흡수된다.

사용법:
    # bwd 모델이 있을 때 (더 정확)
    python scripts/make_cross_pairs.py FWD_MODEL OUT_TXT --bwd-model BWD_MODEL

    # bwd 모델 없이 이미지 폴더만으로
    python scripts/make_cross_pairs.py FWD_MODEL OUT_TXT --bwd-dir path/to/input
"""
import argparse
import glob
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "preprocess"))
from read_write_model import read_model  # noqa: E402


def frame_index(name):
    return int(name.split("_")[1].split(".")[0])


def from_model(model_path):
    """모델의 카메라 중심을 프레임 순서로 정렬해 (이름, 진행률) 반환."""
    _, images, _ = read_model(model_path, ext=".bin")
    items = sorted(((frame_index(im.name), im.name, -im.qvec2rotmat().T @ im.tvec)
                    for im in images.values()), key=lambda x: x[0])
    names = [n for _, n, _ in items]
    centers = np.array([c for _, _, c in items])
    step = np.linalg.norm(np.diff(centers, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(step)])
    return names, cum / cum[-1]


def from_dir(image_dir, prefix):
    """이미지 폴더에서 (이름, 진행률) 반환. 진행률은 프레임 번호 비율."""
    names = sorted(os.path.basename(p) for p in glob.glob(os.path.join(image_dir, f"{prefix}_*.jpg")))
    if not names:
        raise SystemExit(f"{image_dir} 에서 {prefix}_*.jpg 를 찾지 못함")
    idx = np.array([frame_index(n) for n in names], dtype=float)
    return names, (idx - idx.min()) / (idx.max() - idx.min())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fwd_model")
    ap.add_argument("out_txt")
    ap.add_argument("--bwd-model", default=None)
    ap.add_argument("--bwd-dir", default=None)
    ap.add_argument("--window", type=float, default=0.08,
                    help="대응으로 인정할 진행률 차이. 루프 한 변이 0.25이므로 그보다 충분히 작게 둔다")
    ap.add_argument("--stride", type=int, default=3,
                    help="bwd 프레임을 몇 개마다 하나씩 쓸지. 쌍 개수를 줄여 매칭 시간을 아낀다")
    args = ap.parse_args()

    if not (args.bwd_model or args.bwd_dir):
        raise SystemExit("--bwd-model 또는 --bwd-dir 중 하나는 필요함")

    fwd_names, s_fwd = from_model(args.fwd_model)
    if args.bwd_model:
        bwd_names, s_bwd = from_model(args.bwd_model)
        src = "model(arc length)"
    else:
        bwd_names, s_bwd = from_dir(args.bwd_dir, "bwd")
        src = "dir(frame index)"

    pairs = []
    for k in range(0, len(bwd_names), args.stride):
        target = 1.0 - s_bwd[k]          # bwd는 반대 방향
        d = np.abs(s_fwd - target)
        d = np.minimum(d, 1.0 - d)       # 루프이므로 0/1 경계를 넘는 대응도 본다
        for i in np.where(d < args.window)[0]:
            pairs.append((bwd_names[k], fwd_names[i]))

    with open(args.out_txt, "w") as f:
        for a, b in pairs:
            f.write(f"{a} {b}\n")

    used = len(range(0, len(bwd_names), args.stride))
    print(f"fwd {len(fwd_names)}장(model), bwd {len(bwd_names)}장({src})")
    print(f"쌍 {len(pairs)}개 -> {args.out_txt}  (window={args.window}, stride={args.stride})")
    print(f"bwd 1장당 평균 {len(pairs)/max(1,used):.1f}개 대응")


if __name__ == "__main__":
    main()
