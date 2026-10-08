#!/usr/bin/env python3
"""Read existing JPEG frames and stream fixed-size RGB565 packets to one Pico W."""

import argparse
import io
import socket
import struct
import threading
import time
from pathlib import Path

from PIL import Image, ImageOps

WIDTH, HEIGHT, FPS = 160, 80, 6
PAYLOAD_SIZE = WIDTH * HEIGHT * 2
JPEG_MAX_BYTES = 8192
HEADER = struct.Struct(">4sIHHII")  # magic, sequence, width, height, bytes, mode
MAGIC = b"PWF2"
MODES = {"raw-rx": 0, "raw-display": 1, "jpeg-rx": 2,
         "jpeg-decode": 3, "jpeg-display": 4}
STATUS = struct.Struct(">4s6sB1xIIIII")  # magic, STA MAC, PM off, counts, last/max SPI us
STATUS_V2 = struct.Struct(">4s6sBBIIIIIiIIIIII")  # byte 11 carries one-time PM readback
STATUS_V3 = struct.Struct(">4s6sBBIIIIIiIIIIIIIIIII")  # PWS2 fields plus five u32 JPEG metrics
STATUS_V4 = struct.Struct(STATUS_V3.format + "I" * 20 + "IIIHHHBB" * 8)  # 320B


def pm_readback_text(marker: int) -> str:
    if marker & 0xc0 == 0x80:
        return f"mode={marker & 0x3f}"
    if marker & 0xc0 == 0x40:
        return f"error={marker & 0x3f}"
    if marker == 0xc0:
        return "invalid-value"
    return "pending"


def compensate_inversion_and_bgr(payload: bytes) -> bytes:
    """Precompensate the observed inverted, red/blue-swapped panel colors."""
    result = bytearray(len(payload))
    for position in range(0, len(payload), 2):
        source = (payload[position] << 8 | payload[position + 1]) ^ 0xFFFF
        adjusted = ((source & 0x001F) << 11) | (source & 0x07E0) | (source >> 11)
        result[position] = adjusted >> 8
        result[position + 1] = adjusted & 0xFF
    return bytes(result)


def load_frames(directory: Path, compensate_colors: bool = False, codec: str = "raw") -> list[bytes]:
    paths = sorted(directory.iterdir())
    expected = [f"frame{i:04d}.jpg" for i in range(1, len(paths) + 1)]
    if [p.name for p in paths] != expected:
        raise ValueError("frames must be contiguous frame0001.jpg ... frameNNNN.jpg, with no extra files")
    if not paths:
        raise ValueError("no JPEG frames found")
    frames = []
    for path in paths:
        with Image.open(path) as image:
            if image.size != (WIDTH, HEIGHT):
                raise ValueError(f"{path.name}: expected {WIDTH}x{HEIGHT}, got {image.size}")
            color = image.convert("RGB")
        if codec == "jpeg":
            if compensate_colors:
                red, green, blue = color.split()
                color = Image.merge("RGB", (ImageOps.invert(blue),
                                            ImageOps.invert(green), ImageOps.invert(red)))
            buffer = io.BytesIO()
            color.save(buffer, "JPEG", quality=90)
            frame = buffer.getvalue()
            if len(frame) > JPEG_MAX_BYTES:
                raise ValueError(f"{path.name}: JPEG quality 90 is {len(frame)} bytes; "
                                 f"{JPEG_MAX_BYTES} byte slot exceeded")
            frames.append(frame)
            continue
        if codec != "raw":
            raise ValueError(f"unknown codec: {codec}")
        rgb = color.tobytes()
        payload = bytearray(PAYLOAD_SIZE)
        for i in range(WIDTH * HEIGHT):
            r, g, b = rgb[3*i:3*i+3]
            value = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            payload[2*i] = value >> 8
            payload[2*i+1] = value & 0xFF
        frame = bytes(payload)
        frames.append(compensate_inversion_and_bgr(frame) if compensate_colors else frame)
    return frames


def packet(sequence: int, payload: bytes, mode: str = "raw-display") -> bytes:
    if mode not in MODES:
        raise ValueError(f"unknown mode: {mode}")
    if mode.startswith("raw"):
        if len(payload) != PAYLOAD_SIZE:
            raise ValueError("incorrect RGB565 frame length")
    elif not 4 <= len(payload) <= JPEG_MAX_BYTES:
        raise ValueError(f"JPEG frame must be 4..{JPEG_MAX_BYTES} bytes")
    return HEADER.pack(MAGIC, sequence & 0xFFFFFFFF, WIDTH, HEIGHT,
                       len(payload), MODES[mode]) + payload


def read_status(conn: socket.socket, trace_motion: bool = False) -> None:
    """Read optional Pico diagnostics in the TCP reverse direction."""
    previous = None
    previous_event_serial = 0
    while True:
        data = bytearray()
        def receive_to(length: int) -> bool:
            while len(data) < length:
                try:
                    chunk = conn.recv(length - len(data))
                except TimeoutError:
                    continue  # preserve a partially received status message
                except OSError:
                    return False
                if not chunk:
                    return False
                data.extend(chunk)
            return True

        if not receive_to(4):
            return
        status_format = {b"PWS1": STATUS, b"PWS2": STATUS_V2,
                         b"PWS3": STATUS_V3, b"PWS4": STATUS_V4}.get(bytes(data))
        if status_format is None or not receive_to(status_format.size):
            return
        fields = status_format.unpack(data)
        magic, mac, pm_flags = fields[:3]
        pm_off = pm_flags & 1
        receive_only = bool(pm_flags & 2)
        diagnostics = ""
        if magic in (b"PWS2", b"PWS3", b"PWS4"):
            pm_readback, received, displayed, dropped, spi_us, max_spi_us = fields[3:9]
            rssi, pool_max, pool_err, tcp_drop, tcp_memerr, rx_us, rx_gap_ms = fields[9:16]
            if magic in (b"PWS3", b"PWS4"):
                mode, decoded, failed, decode_us, max_decode_us = fields[16:21]
                mode_name = next((name for name, number in MODES.items() if number == mode), f"unknown-{mode}")
                diagnostics = (f" mode={mode_name} decoded={decoded} decode_failed={failed} "
                               f"decode_us={decode_us}/{max_decode_us}")
            if magic == b"PWS4":
                c = fields[21:41]
                diagnostics += (f" credit_wait={c[0]} ack={c[1]} status={c[2]} other={c[3]}"
                                f" wait_timeout={c[4]} wait_max_us={c[5]}"
                                f" credit_drop={c[6]} credit_tcp_data={c[7]}"
                                f" tx_buffer_changed={c[8]} normal_rx={c[9]} lwip_seen={c[10]}"
                                f" pbuf_fail={c[11]} netif_input_fail={c[12]} tcp_gap={c[13]}"
                                f" sdpcm_invalid={c[14]} spi_read_error={c[15]}"
                                f" spi_status_invalid={c[16]} first_drop_ms={c[17]}"
                                f" first_drop_seq=0x{c[18]:08x} event_serial={c[19]}")
                for i in range(8):
                    event = fields[41 + i * 8:41 + (i + 1) * 8]
                    serial, ms, seq, src, dst, length, kind, tx_class = event
                    if serial and serial > previous_event_serial:
                        if serial > previous_event_serial + 1:
                            print(f"CYW43 event_serial_gap={serial - previous_event_serial - 1} "
                                  f"before={serial}", flush=True)
                        print(f"CYW43 event={serial} t_pico_ms={ms} kind={kind} "
                              f"tcp_seq=0x{seq:08x} src={src} dst={dst} "
                              f"tcp_payload={length} tx_class={tx_class}", flush=True)
                        previous_event_serial = serial
            diagnostics += (f" pm_request=0x10(mode=0) pm_readback={pm_readback_text(pm_readback)}"
                           f" RSSI={rssi}dBm pbuf_max={pool_max} pbuf_err={pool_err} "
                           f"tcp_drop={tcp_drop} tcp_memerr={tcp_memerr} "
                           f"rx_callback_max={rx_us}us rx_gap_max={rx_gap_ms}ms")
        else:
            received, displayed, dropped, spi_us, max_spi_us = fields[3:8]
        now = time.monotonic()
        if trace_motion or previous is None or now - previous[0] >= 5:
            interval = None if previous is None else now - previous[0]
            completed = received + dropped
            complete_rate = ("starting" if previous is None else
                             f"{(completed - previous[2] - previous[3]) / interval:.1f} fps")
            rate = ("disabled" if receive_only else
                    "starting" if previous is None else f"{(displayed - previous[1]) / interval:.1f} fps")
            address = ":".join(f"{byte:02x}" for byte in mac)
            if trace_motion and previous is not None:
                print(f"t={now:.3f} Pico interval={interval:.3f}s received={received} displayed={displayed} "
                      f"dropped={dropped} rx_delta={received-previous[2]} "
                      f"display_delta={displayed-previous[1]} drop_delta={dropped-previous[3]} "
                      f"complete_delta={completed-previous[2]-previous[3]} "
                      f"complete_rate={complete_rate} render={'off' if receive_only else 'on'} "
                      f"display_rate={rate} SPI={spi_us}/{max_spi_us} us pm_off={pm_off}"
                      f"{diagnostics}", flush=True)
            else:
                print(f"t={now:.3f} Pico STA MAC={address} received={received} displayed={displayed} "
                      f"dropped={dropped} completed={completed} complete_rate={complete_rate} "
                      f"render={'off' if receive_only else 'on'} display_rate={rate} "
                      f"SPI={spi_us}/{max_spi_us} us "
                      f"pm_off={pm_off}{diagnostics}", flush=True)
            previous = (now, displayed, received, dropped)


def stream(conn: socket.socket, frames: list[bytes], fps: int = FPS,
           limit: int | None = None, start: float | None = None,
           log_progress: bool = False, mode: str = "raw-display") -> None:
    """Use elapsed time for sequence and frame selection; skip late frames."""
    if start is None:
        start = time.monotonic()
    next_seq = 0
    last_sent_seq = None
    last_cycle = None
    last_report = time.monotonic()
    sent_since_report = 0
    skipped_since_report = 0
    previous_send_end = None
    max_send_gap_ms = 0.0
    max_send_block_ms = 0.0
    long_send_count = 0
    while limit is None or next_seq < limit:
        now = time.monotonic()
        due = int((now - start) * fps)
        if due < next_seq:
            time.sleep((next_seq / fps) - (now - start))
            continue
        next_seq = due
        if limit is not None and next_seq >= limit:
            return
        before_send = time.monotonic()
        try:
            conn.sendall(packet(next_seq, frames[next_seq % len(frames)], mode=mode))
        except TimeoutError:
            if log_progress:
                print(f"send timeout sequence={next_seq} "
                      f"block_ms={(time.monotonic()-before_send)*1000:.0f}", flush=True)
            raise
        after_send = time.monotonic()
        if log_progress:
            block_ms = (after_send - before_send) * 1000
            max_send_block_ms = max(max_send_block_ms, block_ms)
            if previous_send_end is not None:
                max_send_gap_ms = max(max_send_gap_ms, (after_send - previous_send_end) * 1000)
            if block_ms >= 500:
                long_send_count += 1
                print(f"send stall sequence={next_seq} block_ms={block_ms:.0f}", flush=True)
            previous_send_end = after_send
            cycle, frame_index = divmod(next_seq, len(frames))
            if last_cycle is None or cycle != last_cycle:
                print(f"playback loop={cycle} sequence={next_seq} frame=frame{frame_index+1:04d}", flush=True)
                last_cycle = cycle
            if last_sent_seq is not None:
                skipped_since_report += max(0, next_seq - last_sent_seq - 1)
            last_sent_seq = next_seq
            sent_since_report += 1
            if after_send - last_report >= 5:
                print(f"stream sent_rate={sent_since_report/(after_send-last_report):.2f} fps "
                      f"skipped={skipped_since_report} sequence={next_seq} "
                      f"frame=frame{frame_index+1:04d} "
                      f"max_send_gap_ms={max_send_gap_ms:.0f} "
                      f"max_send_block_ms={max_send_block_ms:.0f} "
                      f"long_sends={long_send_count}", flush=True)
                last_report = after_send
                sent_since_report = 0
                skipped_since_report = 0
                max_send_gap_ms = 0.0
                max_send_block_ms = 0.0
                long_send_count = 0
        next_seq += 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=Path, default=Path("/home/tane/Videos/voltesV_6frame"))
    parser.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 for the Pico on a trusted LAN")
    parser.add_argument("--port", type=int, default=16151)
    parser.add_argument("--mode", choices=MODES, default="raw-display",
                        help="RAW/JPEG receive, decode, or display comparison")
    parser.add_argument("--fps", type=int, default=FPS,
                        help="send frames per second (default: 6; lower values for diagnostics)")
    parser.add_argument("--once", action="store_true", help="send one pass then close")
    parser.add_argument("--compensate-colors", action="store_true",
                        help="use the inversion and R/B correction confirmed with diagnostic.py")
    parser.add_argument("--trace-motion", action="store_true",
                        help="log per-second Pico counts and server send stalls")
    parser.add_argument("--send-timeout", type=float, default=2.0,
                        help="seconds before aborting a stalled TCP send (default: 2)")
    args = parser.parse_args()
    if args.send_timeout <= 0:
        parser.error("--send-timeout must be positive")
    if args.fps <= 0:
        parser.error("--fps must be positive")
    frames = load_frames(args.frames, compensate_colors=args.compensate_colors,
                         codec=args.mode.split("-")[0])
    print(f"loaded {len(frames)} frames ({sum(map(len, frames)):,} payload bytes); "
          f"mode={args.mode} {args.fps} fps", flush=True)
    print(f"color compensation: {'inversion + R/B swap' if args.compensate_colors else 'off'}", flush=True)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((args.host, args.port))
        listener.listen(1)
        print(f"listening on {args.host}:{args.port}", flush=True)
        playback_start = time.monotonic()
        connection_count = 0
        while True:
            conn, addr = listener.accept()
            connection_count += 1
            print(f"connected #{connection_count}: {addr}", flush=True)
            with conn:
                conn.settimeout(args.send_timeout)
                threading.Thread(target=read_status, args=(conn, args.trace_motion), daemon=True).start()
                try:
                    stream(conn, frames, fps=args.fps, limit=len(frames) if args.once else None,
                           start=playback_start if not args.once else None,
                           log_progress=True, mode=args.mode)
                except TimeoutError as exc:
                    print(f"disconnected: {exc}", flush=True)
                    conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
                except OSError as exc:
                    print(f"disconnected: {exc}", flush=True)
            if args.once:
                break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
