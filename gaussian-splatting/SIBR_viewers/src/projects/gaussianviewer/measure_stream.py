"""image_relay(기본 9102)에서 RFJF Frame을 받아 저장하거나 종단 성능을 잰다.

표준 라이브러리만으로 헤더를 읽으므로 Network 저장소가 없어도 돌아간다.
JPEG 디코드 검사와 --save-dir 저장은 Pillow가 있을 때만 한다.

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

HEADER = struct.Struct(">IBBIQI")   # magic, version, flags, seq, ts_ms, length
MAGIC, VERSION = 0x52464A46, 1      # 'RFJF'
MAX_PAYLOAD = 8 * 1024 * 1024


def _read_exactly(sock: socket.socket, count: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < count:
        chunk = sock.recv(count - len(chunks))
        if not chunk:
            return b""
        chunks.extend(chunk)
    return bytes(chunks)


def read_frame(sock: socket.socket):
    """Frame 하나를 읽어 (seq, ts_ms, payload)로 돌려준다. 정상 종료면 None."""

    header = _read_exactly(sock, HEADER.size)
    if not header:
        return None
    magic, version, _flags, seq, ts_ms, length = HEADER.unpack(header)
    if magic != MAGIC:
        raise ValueError("magic 불일치: 0x{:08X}".format(magic))
    if version != VERSION:
        raise ValueError("version 불일치: {}".format(version))
    if length > MAX_PAYLOAD:
        raise ValueError("length {}B 가 상한 {}B 초과".format(length, MAX_PAYLOAD))
    payload = _read_exactly(sock, length) if length else b""
    if length and not payload:
        return None
    return seq, ts_ms, payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9102)
    parser.add_argument("--warmup", type=float, default=0.0, help="측정에서 뺄 앞부분(초)")
    parser.add_argument("--measure", type=float, default=0.0, help="0이면 Ctrl+C까지 계속")
    parser.add_argument("--save-dir", default="", help="받은 JPEG를 저장할 폴더")
    parser.add_argument("--out", default="", help="측정 결과 JSON 경로")
    args = parser.parse_args()

    if args.save_dir:
        os.makedirs(args.save_dir, exist_ok=True)

    decode = None
    try:
        from PIL import Image  # noqa: F401
        import io as _io

        def decode(payload: bytes):
            image = Image.open(_io.BytesIO(payload))
            image.load()
            return image.size
    except ImportError:
        print("[알림] Pillow가 없어 JPEG 디코드 검사는 건너뜁니다.", file=sys.stderr)

    sock = socket.create_connection((args.host, args.port), timeout=30.0)
    print("[수신] {}:{} 연결됨".format(args.host, args.port))

    start_measure = time.time() + args.warmup
    deadline = (start_measure + args.measure) if args.measure > 0 else float("inf")
    latencies, seqs, sizes = [], [], []
    decoded = decode_failed = 0
    first = last = None
    size = None

    try:
        while time.time() < deadline:
            frame = read_frame(sock)
            if frame is None:
                print("[수신] 서버가 연결을 닫았습니다.")
                break
            seq, ts_ms, payload = frame
            if args.save_dir:
                name = os.path.join(args.save_dir, "frame_{:06d}.jpg".format(seq))
                with open(name, "wb") as handle:
                    handle.write(payload)
            if time.time() < start_measure:
                continue
            now = time.time()
            first = first if first is not None else now
            last = now
            latencies.append(now * 1000.0 - ts_ms)
            seqs.append(seq)
            sizes.append(len(payload))
            if decode is not None:
                try:
                    size = decode(payload)
                    decoded += 1
                except Exception:
                    decode_failed += 1
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
        "schema_version": "1.0",
        "host": args.host,
        "port": args.port,
        "measured_seconds": span,
        "frames_received": len(seqs),
        "received_fps": len(seqs) / span,
        "producer_seq_span": expected,
        "seq_gap_frames": expected - len(seqs),
        "drop_ratio": (expected - len(seqs)) / expected if expected else 0.0,
        "latency_ms_mean": statistics.fmean(latencies),
        "latency_ms_p95": latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))],
        "latency_ms_max": latencies[-1],
        "jpeg_bytes_mean": statistics.fmean(sizes),
        "jpeg_bytes_max": max(sizes),
        "jpeg_decoded": decoded,
        "jpeg_decode_failed": decode_failed,
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
