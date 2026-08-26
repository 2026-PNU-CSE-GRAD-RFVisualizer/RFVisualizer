"""Viewer 없이 image_relay(기본 9101)로 RFJF 시험 Frame을 보낸다.

Graphics 장비나 Display 없이 Relay와 Handheld LCD만 먼저 검증할 때 쓴다.
표준 라이브러리만 쓰므로(zlib) rgb332-zlib 송신에는 아무 의존성도 필요 없다.

시험 무늬는 LCD 고장을 눈으로 가르도록 만들었다.

    위 띠   순수 빨강      아래 띠가 파랑이라 상하가 뒤집히면 바로 보인다
    색 막대 R G B W K Y C M   채널 순서와 bit 배치가 틀리면 색이 어긋난다
    사선 격자              줄 밀림·찢어짐이 사선의 끊김으로 드러난다
    흰 사각형              Frame마다 오른쪽으로 이동한다. 멈추면 갱신이 멈춘 것

    # 기본: RGB332+zlib(flags=1) 10 fps로 계속
    python send_test_pattern.py --host 100.85.80.106

    # 완전히 같은 Frame만 반복. LCD 노이즈가 자리를 바꾸면 전송 쪽, 고정이면 논리 쪽이다
    python send_test_pattern.py --host 100.85.80.106 --pattern static

    # 단색 한 판. 여기서도 점이 튀면 무늬 계산과 무관한 전송·DMA·신호 문제다
    python send_test_pattern.py --host 100.85.80.106 --pattern solid --color 128,128,128

    # 예비 경로 확인(Pillow 필요)
    python send_test_pattern.py --host 100.85.80.106 --format jpeg --seconds 30
"""

from __future__ import annotations

import argparse
import io
import socket
import struct
import sys
import time
import zlib

HEADER = struct.Struct(">IBBIQI")   # magic, version, flags, seq, ts_ms, length
MAGIC, VERSION = 0x52464A46, 1      # 'RFJF'
FLAGS_JPEG, FLAGS_RGB332_ZLIB = 0, 1
WIDTH, HEIGHT = 800, 480
MARKER = 40


def rgb332(red: int, green: int, blue: int) -> int:
    """0-255 세 채널을 RRRGGGBB 한 byte로. FrameCodec.hpp와 같은 식이다."""

    return (red & 0xE0) | ((green & 0xE0) >> 3) | (blue >> 6)


def quantized(red: int, green: int, blue: int):
    """RGB332를 거친 뒤 실제로 화면에 나올 색. 정확한 중간 회색은 표현할 수 없다."""

    value = rgb332(red, green, blue)
    return (value >> 5) * 255 // 7, ((value >> 2) & 7) * 255 // 7, (value & 3) * 255 // 3


def base_pattern(solid=None) -> bytearray:
    """Frame마다 바뀌지 않는 부분을 한 번만 그린다."""

    if solid is not None:
        return bytearray([rgb332(*solid)]) * (WIDTH * HEIGHT)

    bars = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255),
            (0, 0, 0), (255, 255, 0), (0, 255, 255), (255, 0, 255)]
    top = rgb332(255, 0, 0)        # 위 = 빨강
    bottom = rgb332(0, 0, 255)     # 아래 = 파랑
    grid = rgb332(255, 255, 255)
    background = rgb332(64, 64, 64)

    pixels = bytearray(WIDTH * HEIGHT)
    for row in range(HEIGHT):
        offset = row * WIDTH
        if row < 40:
            value = top
        elif row >= HEIGHT - 40:
            value = bottom
        elif row < 140:
            value = None               # 색 막대 구간
        else:
            value = background
        if value is not None:
            for column in range(WIDTH):
                pixels[offset + column] = value
            continue
        for column in range(WIDTH):
            pixels[offset + column] = rgb332(*bars[column * len(bars) // WIDTH])

    # 사선 격자는 배경 구간에만 그린다.
    for row in range(140, HEIGHT - 40):
        offset = row * WIDTH
        for column in range((row * 3) % 24, WIDTH, 24):
            pixels[offset + column] = grid
    return pixels


def rgb332_frame(base: bytearray, sequence: int, marker: bool = True) -> bytes:
    """흰 사각형만 옮겨 그린 뒤 표준 zlib으로 압축한다."""

    if not marker:
        return zlib.compress(bytes(base), 1)
    pixels = bytearray(base)
    left = (sequence * 20) % (WIDTH - MARKER)
    top = HEIGHT // 2 - MARKER // 2
    white = rgb332(255, 255, 255)
    for row in range(top, top + MARKER):
        offset = row * WIDTH + left
        pixels[offset:offset + MARKER] = bytes([white]) * MARKER
    return zlib.compress(bytes(pixels), 1)


def jpeg_encoder(marker: bool):
    """예비 경로용. 같은 무늬를 JPEG로 만든다."""

    try:
        from PIL import Image
    except ImportError:
        print("--format jpeg에는 Pillow가 필요합니다. rgb332-zlib를 쓰거나 Pillow를 설치하세요.",
              file=sys.stderr)
        raise SystemExit(2)

    palette = bytearray()
    for value in range(256):
        palette.append((value >> 5) * 255 // 7)
        palette.append(((value >> 2) & 7) * 255 // 7)
        palette.append((value & 3) * 255 // 3)

    def encode(base: bytearray, sequence: int) -> bytes:
        pixels = zlib.decompress(rgb332_frame(base, sequence, marker))
        image = Image.frombytes("P", (WIDTH, HEIGHT), pixels)
        image.putpalette(bytes(palette))
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, "JPEG", quality=80)
        return buffer.getvalue()

    return encode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9101, help="image_relay ingest")
    parser.add_argument("--fps", type=float, default=10.0)
    parser.add_argument("--format", default="rgb332-zlib", choices=["rgb332-zlib", "jpeg"])
    parser.add_argument("--pattern", default="bars", choices=["bars", "static", "solid"],
                        help="bars=움직이는 표식, static=완전히 같은 Frame 반복, solid=단색 한 판")
    parser.add_argument("--color", default="128,128,128", help="--pattern solid의 R,G,B")
    parser.add_argument("--seconds", type=float, default=0.0, help="0이면 Ctrl+C까지 계속")
    args = parser.parse_args()

    flags = FLAGS_RGB332_ZLIB if args.format == "rgb332-zlib" else FLAGS_JPEG
    marker = args.pattern == "bars"
    if flags == FLAGS_RGB332_ZLIB:
        def encode(base, sequence):
            return rgb332_frame(base, sequence, marker)
    else:
        encode = jpeg_encoder(marker)

    solid = None
    if args.pattern == "solid":
        try:
            solid = tuple(int(part) for part in args.color.split(","))
            if len(solid) != 3 or not all(0 <= part <= 255 for part in solid):
                raise ValueError
        except ValueError:
            print("--color는 0-255 범위의 R,G,B 여야 합니다. 예: --color 128,128,128", file=sys.stderr)
            return 2
    if solid is not None:
        actual = quantized(*solid)
        if actual != solid:
            print("[송신] --color {} 는 RGB332로 표현할 수 없어 {} 로 나갑니다. "
                  "화면의 이 색조는 정상입니다.".format(
                      ",".join(str(part) for part in solid),
                      ",".join(str(part) for part in actual)))
    base = base_pattern(solid)
    period = 1.0 / args.fps if args.fps > 0 else 0.0
    deadline = time.time() + args.seconds if args.seconds > 0 else float("inf")

    sock = socket.create_connection((args.host, args.port), timeout=10.0)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    print("[송신] {}:{} 연결됨, {} {} {}x{} {:.0f} fps".format(
        args.host, args.port, args.format, args.pattern, WIDTH, HEIGHT, args.fps))

    sequence, sent, payload_max = 0, 0, 0
    started = time.time()
    next_frame = started
    try:
        while time.time() < deadline:
            payload = encode(base, sequence)
            header = HEADER.pack(MAGIC, VERSION, flags, sequence,
                                 int(time.time() * 1000), len(payload))
            sock.sendall(header + payload)
            sequence += 1
            sent += 1
            payload_max = max(payload_max, len(payload))
            next_frame += period
            time.sleep(max(next_frame - time.time(), 0.0))
    except KeyboardInterrupt:
        pass
    except OSError as error:
        print("[송신] 끊김: {}".format(error), file=sys.stderr)
        return 1
    finally:
        sock.close()

    span = max(time.time() - started, 1e-6)
    print("[송신] {}장, {:.1f} fps, payload 최대 {}B".format(sent, sent / span, payload_max))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
