"""모델의 image_id를 다른 데이터베이스의 id 체계로 갈아끼운다.

image_registrator는 입력 모델의 image_id가 database.db의 id와 일치해야 동작한다.
fwd 전용 DB에서 만든 모델을 통합 DB에 그대로 쓰면 id가 어긋나므로, 이미지 이름을
기준으로 id를 다시 매핑해 준다.

사용법:
    python scripts/remap_model_ids.py IN_MODEL DATABASE OUT_MODEL
"""
import os
import sqlite3
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "preprocess"))
from read_write_model import read_model, write_model  # noqa: E402


def main():
    in_model, db_path, out_model = sys.argv[1:4]

    cameras, images, points3D = read_model(in_model, ext=".bin")

    con = sqlite3.connect(db_path)
    name2id = dict(con.execute("SELECT name, image_id FROM images").fetchall())
    name2cam = dict(con.execute("SELECT name, camera_id FROM images").fetchall())
    db_cameras = {r[0] for r in con.execute("SELECT camera_id FROM cameras").fetchall()}
    con.close()

    missing = [im.name for im in images.values() if im.name not in name2id]
    if missing:
        raise SystemExit(f"DB에 없는 이미지 {len(missing)}장: {missing[:5]}")

    old2new = {im.id: name2id[im.name] for im in images.values()}

    new_images = {}
    for im in images.values():
        nid = name2id[im.name]
        new_images[nid] = im._replace(id=nid, camera_id=name2cam[im.name])

    new_points = {}
    for pid, pt in points3D.items():
        new_points[pid] = pt._replace(
            image_ids=np.array([old2new[i] for i in pt.image_ids], dtype=np.int64))

    # 카메라는 DB 쪽 id를 쓰므로, 모델 카메라를 그 id로 옮겨 담는다
    used_cam_ids = {im.camera_id for im in new_images.values()}
    new_cameras = {}
    for cid in used_cam_ids:
        if cid not in db_cameras:
            raise SystemExit(f"DB에 camera_id {cid} 가 없음")
        src = list(cameras.values())[0]
        new_cameras[cid] = src._replace(id=cid)

    os.makedirs(out_model, exist_ok=True)
    write_model(new_cameras, new_images, new_points, out_model, ext=".bin")
    print(f"{len(new_images)}장 remap 완료 -> {out_model}")
    print(f"  카메라 id: {sorted(used_cam_ids)}")


if __name__ == "__main__":
    main()
