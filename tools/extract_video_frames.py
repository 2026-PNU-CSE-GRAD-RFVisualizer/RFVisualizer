#!/usr/bin/env python3
"""Extract time-spaced JPEG frames from a video for COLMAP/PGSR input."""

from __future__ import annotations

import argparse
import csv
import math
import re
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import cv2


def _positive_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise argparse.ArgumentTypeError("0보다 큰 유한한 숫자여야 합니다.")
    return number


def _nonnegative_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise argparse.ArgumentTypeError("0 이상의 유한한 숫자여야 합니다.")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "영상을 시간 기준으로 샘플링해 COLMAP/PGSR 입력용 JPEG와 "
            "프레임 품질 CSV를 만듭니다."
        )
    )
    parser.add_argument(
        "--video",
        required=True,
        type=Path,
        nargs="+",
        help="입력 영상 한 개 이상(MP4, MOV, MKV, AVI 등)",
    )
    parser.add_argument("--output", required=True, type=Path, help="빈 출력 폴더")
    parser.add_argument(
        "--fps",
        type=_positive_float,
        default=5.0,
        help="초당 추출 프레임 수(기본값: 5)",
    )
    parser.add_argument(
        "--start-seconds",
        type=_nonnegative_float,
        default=0.0,
        help="추출 시작 시각(초)",
    )
    parser.add_argument(
        "--end-seconds",
        type=_positive_float,
        help="추출 종료 시각(초, 생략 시 영상 끝)",
    )
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        default=95,
        choices=range(1, 101),
        metavar="1..100",
        help="JPEG 품질(기본값: 95)",
    )
    return parser


def _prepare_output(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    existing = list(directory.iterdir())
    if existing:
        raise ValueError(
            "출력 폴더가 비어 있지 않습니다: {}. "
            "기존 사진 보호를 위해 새 빈 폴더를 사용하세요.".format(directory)
        )


def _safe_stem(path: Path) -> str:
    stem = re.sub(r"[^0-9A-Za-z_-]+", "_", path.stem).strip("_")
    return stem or "video"


def _extract_one_video(
    video: Path,
    output: Path,
    video_index: int,
    target_fps: float = 5.0,
    start_seconds: float = 0.0,
    end_seconds: Optional[float] = None,
    jpeg_quality: int = 95,
) -> Tuple[dict, List[dict]]:
    source = video.expanduser().resolve()
    destination = output.expanduser().resolve()
    if not source.is_file():
        raise ValueError("입력 영상을 찾을 수 없습니다: {}".format(source))
    if end_seconds is not None and end_seconds <= start_seconds:
        raise ValueError("end-seconds는 start-seconds보다 커야 합니다.")

    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise ValueError("OpenCV가 영상을 열 수 없습니다: {}".format(source))

    try:
        if hasattr(cv2, "CAP_PROP_ORIENTATION_AUTO"):
            capture.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1)
        source_fps = float(capture.get(cv2.CAP_PROP_FPS))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if not math.isfinite(source_fps) or source_fps <= 0.0:
            raise ValueError("영상 FPS 메타데이터가 유효하지 않습니다.")
        if target_fps > source_fps + 1.0e-9:
            raise ValueError(
                "추출 FPS({:.3f})가 원본 FPS({:.3f})보다 큽니다.".format(
                    target_fps, source_fps
                )
            )

        start_frame = max(0, int(math.floor(start_seconds * source_fps)))
        capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        source_frame = start_frame
        next_sample_time = start_seconds
        sample_interval = 1.0 / target_fps
        extracted = []
        filename_prefix = "video_{:03d}_{}".format(video_index, _safe_stem(source))

        while True:
            ok, frame = capture.read()
            if not ok:
                break
            timestamp = source_frame / source_fps
            source_frame += 1
            if end_seconds is not None and timestamp >= end_seconds:
                break
            if timestamp + 0.5 / source_fps < next_sample_time:
                continue

            sample_index = len(extracted) + 1
            timestamp_ms = int(round(timestamp * 1000.0))
            filename = "{}_frame_{:06d}_t{:09d}ms.jpg".format(
                filename_prefix, sample_index, timestamp_ms
            )
            image_path = destination / filename
            written = cv2.imwrite(
                str(image_path),
                frame,
                [cv2.IMWRITE_JPEG_QUALITY, int(jpeg_quality)],
            )
            if not written:
                raise OSError("JPEG를 저장하지 못했습니다: {}".format(image_path))

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            extracted.append(
                {
                    "video_index": video_index,
                    "video_file": str(source),
                    "filename": filename,
                    "source_frame": source_frame - 1,
                    "timestamp_seconds": "{:.6f}".format(timestamp),
                    "laplacian_variance": "{:.6f}".format(blur_score),
                }
            )
            while next_sample_time <= timestamp + 0.5 / source_fps:
                next_sample_time += sample_interval
    finally:
        capture.release()

    if not extracted:
        raise ValueError(
            "지정한 구간에서 추출된 프레임이 없습니다: {}".format(source)
        )

    return (
        {
            "video": str(source),
            "source_fps": source_fps,
            "source_frame_count": frame_count,
            "extracted_frame_count": len(extracted),
        },
        extracted,
    )


def extract_videos(
    videos: Sequence[Path],
    output: Path,
    target_fps: float = 5.0,
    start_seconds: float = 0.0,
    end_seconds: Optional[float] = None,
    jpeg_quality: int = 95,
) -> dict:
    if not videos:
        raise ValueError("입력 영상이 한 개 이상 필요합니다.")
    destination = output.expanduser().resolve()
    _prepare_output(destination)

    video_reports = []
    rows = []
    for video_index, video in enumerate(videos, start=1):
        report, extracted = _extract_one_video(
            video=video,
            output=destination,
            video_index=video_index,
            target_fps=target_fps,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            jpeg_quality=jpeg_quality,
        )
        video_reports.append(report)
        rows.extend(extracted)

    manifest = destination / "frames.csv"
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "video_index",
                "video_file",
                "filename",
                "source_frame",
                "timestamp_seconds",
                "laplacian_variance",
            ),
        )
        writer.writeheader()
        writer.writerows(rows)

    return {
        "videos": video_reports,
        "output": str(destination),
        "target_fps": target_fps,
        "extracted_frame_count": len(rows),
        "manifest": str(manifest),
    }


def extract_frames(
    video: Path,
    output: Path,
    target_fps: float = 5.0,
    start_seconds: float = 0.0,
    end_seconds: Optional[float] = None,
    jpeg_quality: int = 95,
) -> dict:
    """Backward-compatible single-video wrapper."""
    return extract_videos(
        videos=[video],
        output=output,
        target_fps=target_fps,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        jpeg_quality=jpeg_quality,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = extract_videos(
            videos=args.video,
            output=args.output,
            target_fps=args.fps,
            start_seconds=args.start_seconds,
            end_seconds=args.end_seconds,
            jpeg_quality=args.jpeg_quality,
        )
    except (OSError, ValueError) as exc:
        print("오류: {}".format(exc))
        return 2

    for item in report["videos"]:
        print(
            "원본: {} | FPS: {:.3f} | 추출: {}장".format(
                item["video"],
                item["source_fps"],
                item["extracted_frame_count"],
            )
        )
    print("추출 FPS: {:.3f}".format(report["target_fps"]))
    print("전체 추출 프레임: {}장".format(report["extracted_frame_count"]))
    print("출력 폴더: {}".format(report["output"]))
    print("품질 목록: {}".format(report["manifest"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
