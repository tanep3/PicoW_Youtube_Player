"""Prepare fixed color references or hold one through the normal PWF2 RAW path."""
import argparse
import hashlib
import json
import socket
import struct
import threading
from pathlib import Path
from PIL import Image
from server.streamer import image_rgb565, packet, read_status, stream


def payload_for(path):
    with Image.open(path) as image:
        return image_rgb565(image, compensate_colors=True)


def prepare_assets(photo_dir, ramp, output):
    output.mkdir(parents=True, exist_ok=True)
    references = [("photo_bright_0600.jpg", photo_dir / "frame00000600.jpg"),
                  ("photo_dark_1400.jpg", photo_dir / "frame00001400.jpg"),
                  ("gray_rgb_reference.png", ramp)]
    items = []
    for name, source in references:
        content = source.read_bytes()
        destination = output / name
        if destination.exists() and destination.read_bytes() != content:
            raise ValueError(f"Existing reference differs: {destination}")
        with Image.open(source) as image:
            if image.size != (160, 80):
                raise ValueError(f"Reference must be 160x80: {source}")
            image.verify()
        destination.write_bytes(content)
        payload = payload_for(destination)
        wire = packet(0, payload)
        items.append({"name": name, "source": str(source), "bytes": len(content),
                      "file_sha256": hashlib.sha256(content).hexdigest(),
                      "payload_bytes": len(payload), "packet_bytes": len(wire),
                      "payload_sha256": hashlib.sha256(payload).hexdigest()})
    manifest = {"width": 160, "height": 80, "mode": "raw-display", "fps": 6,
                "color_compensation": "invert-and-swap-rb", "references": items}
    (output / "references.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--prepare-assets", action="store_true", help="Create files only; no network listener")
    action.add_argument("--image", type=Path, help="Hold one existing 160x80 JPEG/PNG (explicit future test)")
    parser.add_argument("--photo-dir", type=Path)
    parser.add_argument("--ramp", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "artifacts/lcd-gamma-ab/assets")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=16151)
    args = parser.parse_args()
    if args.prepare_assets:
        if not args.photo_dir or not args.ramp:
            parser.error("--prepare-assets requires --photo-dir and --ramp")
        print(json.dumps(prepare_assets(args.photo_dir, args.ramp, args.output), ensure_ascii=False, indent=2))
        return
    if args.port in (16150, 8080) or not 1 <= args.port <= 65535:
        parser.error("choose an unreserved valid port")
    payload = payload_for(args.image)
    print(f"reference={args.image.name} payload_sha256={hashlib.sha256(payload).hexdigest()}", flush=True)
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # If the Web player occupies this port, bind fails instead of disturbing it.
        listener.bind((args.host, args.port))
        listener.listen(1)
        print(f"reference listener {args.host}:{args.port}; raw-display / 6fps / compensation on", flush=True)
        while True:
            conn, peer = listener.accept()
            print(f"Pico connected: {peer}", flush=True)
            with conn:
                conn.settimeout(2)
                threading.Thread(target=read_status, args=(conn, True), daemon=True).start()
                try:
                    stream(conn, [payload], fps=6, mode="raw-display")
                except TimeoutError:
                    conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                    print("send timeout; waiting for reconnect", flush=True)
                except OSError as exc:
                    print(f"disconnected: {exc}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
