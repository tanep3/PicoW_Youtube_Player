#!/usr/bin/env python3
"""Hold a fixed RGB565 alignment chart over the existing Pico TCP protocol."""

import argparse
import socket
import threading
import time

from server.streamer import FPS, HEIGHT, WIDTH, compensate_inversion_and_bgr, packet, read_status

def solid(color: int) -> bytes:
    return bytes((color >> 8, color & 0xFF)) * (WIDTH * HEIGHT)


def geometry() -> bytes:
    pixels = bytearray(WIDTH * HEIGHT * 2)
    for y in range(HEIGHT):
        for x in range(WIDTH):
            color = 0x0000
            if x in (0, WIDTH - 1) or y in (0, HEIGHT - 1):
                color = 0xFFFF  # one-pixel white outer edge
            if 0 < x < WIDTH - 1:
                if y == 1:
                    color = 0xF800  # red
                elif y == 2:
                    color = 0x07E0  # green
                elif y == 3:
                    color = 0x001F  # blue
                elif 8 <= y < 16:
                    color = 0xF800  # red band, clear of the noisy top edge
                elif 20 <= y < 28:
                    color = 0x07E0  # green band
                elif 32 <= y < 40:
                    color = 0x001F  # blue band
            pos = 2 * (y * WIDTH + x)
            pixels[pos] = color >> 8
            pixels[pos + 1] = color & 0xFF
    return bytes(pixels)


PATTERN = geometry()


def stream_patterns(conn: socket.socket, payload: bytes) -> None:
    start = time.monotonic()
    sequence = 0
    print("holding alignment chart: white 1px border, top RGB rows and RGB bands", flush=True)
    while True:
        now = time.monotonic()
        due = int((now - start) * FPS)
        if due < sequence:
            time.sleep(sequence / FPS - (now - start))
            continue
        sequence = due
        conn.sendall(packet(sequence, payload))
        sequence += 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=16151)
    parser.add_argument("--compensate-colors", action="store_true",
                        help="Precompensate observed LCD inversion and red/blue swap")
    args = parser.parse_args()
    payload = compensate_inversion_and_bgr(PATTERN) if args.compensate_colors else PATTERN
    print(f"color compensation: {'inversion + R/B swap' if args.compensate_colors else 'off'}", flush=True)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((args.host, args.port))
        listener.listen(1)
        print(f"diagnostic listening on {args.host}:{args.port}", flush=True)
        while True:
            conn, address = listener.accept()
            print(f"connected: {address}", flush=True)
            with conn:
                conn.settimeout(10)
                threading.Thread(target=read_status, args=(conn,), daemon=True).start()
                try:
                    stream_patterns(conn, payload)
                except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError) as exc:
                    print(f"disconnected: {exc}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
