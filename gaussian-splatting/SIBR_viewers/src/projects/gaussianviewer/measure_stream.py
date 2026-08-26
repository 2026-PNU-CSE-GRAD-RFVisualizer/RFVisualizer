"""image_relay(기본 9102)에서 RFJF Frame을 받아 저장하거나 종단 성능을 잰다.

표준 라이브러리만으로 헤더를 읽고 flags=1(RGB332+zlib)은 표준 zlib으로 해제하므로
Network 저장소가 없어도 돌아간다. 그림 저장과 JPEG 디코드 검사는 Pillow가 있을 때만 한다.

    # 받은 그림을 폴더에 저장
    python measure_stream.py --save-dir /tmp/rf_frames

    # 5초 Warm-up 뒤 300초 동안 수신 FPS·지연·누락 측정
    python measure_stream.py --warmup 5 --measure 300 --out /tmp/recv.json
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import statistics
import struct
import sys
import time
import zlib

HEADER = struct.Struct(">IBBIQI")   # magic, version, flags, seq, ts_ms, length
MAGIC, VERSION = 0x52464A46, 1      # 'RFJF'
MAX_PAYLOAD = 8 * 1024 * 1024
FLAGS_JPEG, FLAGS_RGB332_ZLIB = 0, 1
RGB332_SIZE = (800, 480)
RGB332_BYTES = RGB332_SIZE[0] * RGB332_SIZE[1]   # 384000, 픽셀당 1byte


def rgb332_palette() -> bytes:
    """RRRGGGBB 한 byte를 그대로 색인으로 쓰는 256색 팔레트."""

    palette = bytearray()
    for value in range(256):
        palette.append((value >> 5) * 255 // 7)
        palette.append(((value >> 2) & 7) * 255 // 7)
        palette.append((value & 3) * 255 // 3)
    return bytes(palette)


def _read_exactly(sock: socket.socket, count: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < count:
        chunk = sock.recv(count - len(chunks))
        if not chunk:
            return b""
        chunks.extend(chunk)
    return bytes(chunks)


def read_frame(sock: socket.socket):
    """Frame 하나를 읽어 (flags, seq, ts_ms, payload)로 돌려준다. 정상 종료면 None."""

    header = _read_exactly(sock, HEADER.size)
    if not header:
        return None
    magic, version, flags, seq, ts_ms, length = HEADER.unpack(header)
    if magic != MAGIC:
        raise ValueError("magic 불일치: 0x{:08X}".format(magic))
    if version != VERSION:
        raise ValueError("version 불일치: {}".format(version))
    if length > MAX_PAYLOAD:
        raise ValueError("length {}B 가 상한 {}B 초과".format(length, MAX_PAYLOAD))
    payload = _read_exactly(sock, length) if length else b""
    if length and not payload:
        return None
    return flags, seq, ts_ms, payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9102)
    parser.add_argument("--warmup", type=float, default=0.0, help="측정에서 뺄 앞부분(초)")
    parser.add_argument("--measure", type=float, default=0.0, help="0이면 Ctrl+C까지 계속")
    parser.add_argument("--save-dir", default="", help="받은 그림을 저장할 폴더")
    parser.add_argument("--out", default="", help="측정 결과 JSON 경로")
    args = parser.parse_args()

    if args.save_dir:
        os.makedirs(args.save_dir, exist_ok=True)

    open_image = None
    try:
        from PIL import Image
        import io as _io

        def open_image(flags: int, pixels: bytes):
            if flags == FLAGS_RGB332_ZLIB:
                image = Image.frombytes("P", RGB332_SIZE, pixels)
                image.putpalette(rgb332_palette())
                return image.convert("RGB")
            image = Image.open(_io.BytesIO(pixels))
            image.load()
            return image
    except ImportError:
        print("[알림] Pillow가 없어 그림 디코드·저장은 건너뜁니다.", file=sys.stderr)

    sock = socket.create_connection((args.host, args.port), timeout=30.0)
    print("[수신] {}:{} 연결됨".format(args.host, args.port))

    start_measure = time.time() + args.warmup
    deadline = (start_measure + args.measure) if args.measure > 0 else float("inf")
    latencies, seqs, sizes = [], [], []
    decoded = decode_failed = inflate_failed = wrong_size = 0
    flags_seen = set()
    first = last = None
    size = None
    inflated_bytes = None

    try:
        while time.time() < deadline:
            frame = read_frame(sock)
            if frame is None:
                print("[수신] 서버가 연결을 닫았습니다.")
                break
            flags, seq, ts_ms, payload = frame
            flags_seen.add(flags)

            # flags=1이면 여기서 표준 zlib으로 풀고 정확히 384,000byte인지 본다.
            pixels = payload
            if flags == FLAGS_RGB332_ZLIB:
                try:
                    pixels = zlib.decompress(payload)
                except zlib.error as error:
                    inflate_failed += 1
                    print("[수신] seq {} zlib 해제 실패: {}".format(seq, error), file=sys.stderr)
                    continue
                inflated_bytes = len(pixels)
                if inflated_bytes != RGB332_BYTES:
                    wrong_size += 1
                    print("[수신] seq {} 해제 크기 {}B 가 {}B 아님".format(
                        seq, inflated_bytes, RGB332_BYTES), file=sys.stderr)
                    continue

            if time.time() < start_measure:
                continue
            now = time.time()
            first = first if first is not None else now
            last = now
            latencies.append(now * 1000.0 - ts_ms)
            seqs.append(seq)
            sizes.append(len(payload))
            if open_image is not None:
                try:
                    image = open_image(flags, pixels)
                    size = image.size
                    decoded += 1
                    if args.save_dir:
                        image.save(os.path.join(args.save_dir, "frame_{:06d}.png".format(seq)))
                except Exception as error:
                    decode_failed += 1
                    print("[수신] seq {} 디코드 실패: {}".format(seq, error), file=sys.stderr)
            elif args.save_dir:
                with open(os.path.join(args.save_dir, "frame_{:06d}.bin".format(seq)), "wb") as handle:
                    handle.write(pixels)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()

    if not seqs:
        print("측정 구간에서 받은 Frame이 없습니다.", file=sys.stderr)
        return 2

    span = max((last or 0.0) - (first or 0.0), 1e-6)
    expected = seqs[-1] - seqs[0] + 1
    latencies.sort()
    report = {
        "schema_version": "2.0",
        "host": args.host,
        "port": args.port,
        "flags_seen": sorted(flags_seen),
        "measured_seconds": span,
        "frames_received": len(seqs),
        "received_fps": len(seqs) / span,
        "producer_seq_span": expected,
        "seq_gap_frames": expected - len(seqs),
        "drop_ratio": (expected - len(seqs)) / expected if expected else 0.0,
        "latency_ms_mean": statistics.fmean(latencies),
        "latency_ms_p95": latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))],
        "latency_ms_max": latencies[-1],
        "payload_bytes_mean": statistics.fmean(sizes),
        "payload_bytes_max": max(sizes),
        "inflated_bytes": inflated_bytes,
        "frames_decoded": decoded,
        "frames_decode_failed": decode_failed,
        "frames_inflate_failed": inflate_failed,
        "frames_wrong_inflated_size": wrong_size,
        "image_size": list(size) if size else None,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
