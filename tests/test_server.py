import contextlib
import ctypes
import subprocess
import io
import random
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from PIL import Image

from server import streamer as server


class ServerTests(unittest.TestCase):
    def test_rgb565_and_frame_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            image = Image.new("RGB", (160, 80), (255, 0, 0))
            image.save(folder / "frame0001.jpg", quality=100, subsampling=0)
            frames = server.load_frames(folder)
            self.assertEqual(len(frames[0]), 25600)
            self.assertEqual(frames[0][:2], bytes.fromhex("f800"))
            corrected = server.load_frames(folder, compensate_colors=True)
            self.assertEqual(corrected[0][:2], bytes.fromhex("ffe0"))
            image.save(folder / "frame0003.jpg")
            with self.assertRaises(ValueError):
                server.load_frames(folder)

    def test_socket_packet_and_one_pass(self):
        left, right = socket.socketpair()
        payload = bytes(server.PAYLOAD_SIZE)
        worker = threading.Thread(target=server.stream, args=(left, [payload], 600, 2))
        worker.start()
        received = b""
        expected = 2 * (server.HEADER.size + server.PAYLOAD_SIZE)
        while len(received) < expected:
            received += right.recv(expected - len(received))
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(received), expected)
        for index in range(2):
            part = received[index * (server.HEADER.size + server.PAYLOAD_SIZE):]
            magic, seq, width, height, size, mode = server.HEADER.unpack_from(part)
            self.assertEqual((magic, seq, width, height, size, mode), (b"PWF2", index, 160, 80, 25600, 1))
        left.close()
        right.close()

    def test_six_fps_pacing(self):
        class Capture:
            def __init__(self):
                self.times = []

            def sendall(self, data):
                self.times.append(time.monotonic())
                self.length = len(data)

        capture = Capture()
        server.stream(capture, [bytes(server.PAYLOAD_SIZE)], fps=6, limit=3)
        self.assertEqual(len(capture.times), 3)
        self.assertEqual(capture.length, 25620)
        self.assertGreaterEqual(capture.times[1] - capture.times[0], 0.14)
        self.assertGreaterEqual(capture.times[2] - capture.times[1], 0.14)

    def test_tcp_listener_receives_frames_and_reconnects(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            Image.new("RGB", (160, 80), (255, 0, 0)).save(folder / "frame0001.jpg", quality=100)
            Image.new("RGB", (160, 80), (0, 255, 0)).save(folder / "frame0002.jpg", quality=100)
            frames = server.load_frames(folder)
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                port = listener.getsockname()[1]
                failures = []

                def serve_twice():
                    try:
                        for _ in range(2):
                            conn, _ = listener.accept()
                            with conn:
                                server.stream(conn, frames, fps=6, limit=3)
                    except Exception as exc:
                        failures.append(exc)

                worker = threading.Thread(target=serve_twice)
                worker.start()
                for _ in range(2):
                    received_at = []
                    with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
                        client.settimeout(2)

                        def exact(length):
                            chunks = bytearray()
                            while len(chunks) < length:
                                piece = client.recv(min(7, length - len(chunks)))
                                if not piece:
                                    raise AssertionError("early TCP close")
                                chunks.extend(piece)
                            return bytes(chunks)

                        for seq in range(3):
                            header = exact(server.HEADER.size)
                            magic, number, width, height, size, mode = server.HEADER.unpack(header)
                            payload = exact(size)
                            received_at.append(time.monotonic())
                            self.assertEqual((magic, number, width, height, size, mode),
                                             (b"PWF2", seq, 160, 80, 25600, 1))
                            self.assertEqual(payload, frames[seq % 2])
                    self.assertGreaterEqual(received_at[1] - received_at[0], 0.13)
                    self.assertGreaterEqual(received_at[2] - received_at[1], 0.13)
                worker.join(timeout=3)
                self.assertFalse(worker.is_alive())
                self.assertEqual(failures, [])

    def test_reconnect_uses_shared_playback_clock(self):
        class StopAfterOne:
            def sendall(self, data):
                self.first = data
                raise StopIteration

        capture = StopAfterOne()
        with self.assertRaises(StopIteration):
            server.stream(capture, [bytes(server.PAYLOAD_SIZE)],
                          start=time.monotonic() - 5)
        self.assertGreaterEqual(server.HEADER.unpack_from(capture.first)[1], 30)

    def test_frame_selection_wraps_to_first_frame(self):
        class Capture:
            def __init__(self):
                self.packets = []

            def sendall(self, data):
                self.packets.append(data)

        capture = Capture()
        first = bytes.fromhex("1111") * (server.PAYLOAD_SIZE // 2)
        second = bytes.fromhex("2222") * (server.PAYLOAD_SIZE // 2)
        server.stream(capture, [first, second], fps=60, limit=5)
        self.assertEqual([server.HEADER.unpack_from(p)[1] for p in capture.packets], list(range(5)))
        self.assertEqual([p[server.HEADER.size:server.HEADER.size+2] for p in capture.packets],
                         [bytes.fromhex(s) for s in ("1111", "2222", "1111", "2222", "1111")])

    def test_status_message_reports_sta_mac_and_spi_time(self):
        left, right = socket.socketpair()
        output = io.StringIO()

        def receive():
            with contextlib.redirect_stdout(output):
                server.read_status(left)

        worker = threading.Thread(target=receive)
        worker.start()
        right.sendall(server.STATUS.pack(b"PWS1", bytes.fromhex("280102030405"), 1,
                                         6, 5, 1, 10200, 11000))
        right.close()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertIn("28:01:02:03:04:05", output.getvalue())
        self.assertIn("displayed=5", output.getvalue())
        self.assertIn("pm_off=1", output.getvalue())
        left.close()

    def test_status_read_survives_timeout_between_fragments(self):
        left, right = socket.socketpair()
        left.settimeout(0.02)
        output = io.StringIO()

        def receive():
            with contextlib.redirect_stdout(output):
                server.read_status(left)

        worker = threading.Thread(target=receive)
        worker.start()
        status = server.STATUS.pack(b"PWS1", bytes.fromhex("280102030405"), 1,
                                    6, 5, 1, 10200, 11000)
        right.sendall(status[:10])
        time.sleep(0.05)
        right.sendall(status[10:])
        right.close()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertIn("displayed=5", output.getvalue())
        left.close()

    def test_status_v2_reports_network_diagnostics_after_fragment_timeout(self):
        self.assertEqual(server.STATUS_V2.size, 60)
        left, right = socket.socketpair()
        left.settimeout(0.02)
        output = io.StringIO()

        def receive():
            with contextlib.redirect_stdout(output):
                server.read_status(left)

        worker = threading.Thread(target=receive)
        worker.start()
        status = server.STATUS_V2.pack(b"PWS2", bytes.fromhex("28cd01020304"), 1, 0x80,
                                       12, 10, 2, 15600, 41000,
                                       -58, 25, 3, 7, 2, 420, 2100)
        right.sendall(status[:2])
        time.sleep(0.04)
        right.sendall(status[2:36])
        time.sleep(0.04)
        right.sendall(status[36:])
        right.close()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        message = output.getvalue()
        for field in ("28:cd:01:02:03:04", "displayed=10", "pm_request=0x10(mode=0)",
                      "pm_readback=mode=0", "render=on", "completed=14", "RSSI=-58dBm",
                      "pbuf_max=25", "pbuf_err=3", "tcp_drop=7", "tcp_memerr=2",
                      "rx_callback_max=420us", "rx_gap_max=2100ms"):
            self.assertIn(field, message)
        left.close()

    def test_pm_readback_status_distinguishes_error_and_pending(self):
        self.assertEqual(server.pm_readback_text(0), "pending")
        self.assertEqual(server.pm_readback_text(0x82), "mode=2")
        self.assertEqual(server.pm_readback_text(0x42), "error=2")
        self.assertEqual(server.pm_readback_text(0xc0), "invalid-value")

    def test_receive_only_status_counts_completed_frames_without_display_fps(self):
        left, right = socket.socketpair()
        output = io.StringIO()

        def receive():
            with contextlib.redirect_stdout(output):
                server.read_status(left, trace_motion=True)

        worker = threading.Thread(target=receive)
        worker.start()
        common = (b"PWS2", bytes.fromhex("28cd01020304"), 3, 0x80)
        right.sendall(server.STATUS_V2.pack(*common, 12, 0, 2, 0, 0,
                                            -127, 18, 0, 0, 0, 500, 1000))
        right.sendall(server.STATUS_V2.pack(*common, 18, 0, 3, 0, 0,
                                            -127, 18, 0, 0, 0, 500, 1200))
        right.close()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        message = output.getvalue()
        for field in ("render=off", "display_rate=disabled", "completed=14",
                      "complete_delta=7", "display_delta=0", "rx_gap_max=1200ms"):
            self.assertIn(field, message)
        left.close()

    def test_jpeg_modes_size_and_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            Image.new("RGB", (160, 80), (40, 80, 120)).save(folder / "frame0001.jpg")
            jpeg = server.load_frames(folder, codec="jpeg", compensate_colors=True)[0]
            self.assertLessEqual(len(jpeg), server.JPEG_MAX_BYTES)
            data = server.packet(3, jpeg, mode="jpeg-display")
            self.assertEqual(server.HEADER.unpack_from(data),
                             (b"PWF2", 3, 160, 80, len(jpeg), 4))
            self.assertEqual(data[server.HEADER.size:], jpeg)
            with self.assertRaises(ValueError):
                server.packet(3, b"x" * 8193, mode="jpeg-rx")
            with self.assertRaises(ValueError):
                server.packet(3, b"x" * 10, mode="raw-rx")
            Image.new("RGB", (161, 80)).save(folder / "frame0001.jpg")
            with self.assertRaises(ValueError):
                server.load_frames(folder, codec="jpeg")
            random_pixels = random.Random(7).randbytes(160 * 80 * 3)
            Image.frombytes("RGB", (160, 80), random_pixels).save(folder / "frame0001.jpg", quality=100)
            with self.assertRaisesRegex(ValueError, "slot exceeded"):
                server.load_frames(folder, codec="jpeg")

    def test_native_jpeg_decoder_valid_and_invalid_inputs(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / "decoder.so"
            subprocess.run(["cc", "-std=c11", "-fPIC", "-shared", "-I", str(root / "pico"),
                            str(root / "pico/jpeg_decode.c"),
                            str(root / "pico/third_party/tjpgd/lgfx_tjpgd.c"),
                            "-o", str(library)], check=True)
            decode = ctypes.CDLL(str(library)).jpeg_decode_frame
            decode.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
            decode.restype = ctypes.c_int
            output = ctypes.create_string_buffer(server.PAYLOAD_SIZE)
            def call(data):
                source = ctypes.create_string_buffer(data)
                return decode(source, len(data), output)
            jpeg = io.BytesIO()
            Image.new("RGB", (160, 80), (255, 0, 0)).save(jpeg, "JPEG", quality=90)
            valid = jpeg.getvalue()
            self.assertEqual(call(valid), 0)
            self.assertEqual(output.raw[:2], bytes.fromhex("f800"))
            self.assertNotEqual(call(valid[:-8]), 0)
            self.assertNotEqual(call(valid + bytes(8193 - len(valid))), 0)
            self.assertNotEqual(call(b"\xff\xd8" + bytes(100) + b"\xff\xd9"), 0)
            wrong = io.BytesIO()
            Image.new("RGB", (159, 80)).save(wrong, "JPEG", quality=90)
            self.assertEqual(call(wrong.getvalue()), -2)

    def test_status_v3_jpeg_counters(self):
        self.assertEqual(server.STATUS_V3.size, 80)
        left, right = socket.socketpair()
        output = io.StringIO()
        def receive():
            with contextlib.redirect_stdout(output):
                server.read_status(left)
        worker = threading.Thread(target=receive)
        worker.start()
        right.sendall(server.STATUS_V3.pack(b"PWS3", bytes.fromhex("28cd01020304"),
                                            3, 0x80, 12, 0, 2, 0, 0,
                                            -127, 18, 0, 0, 0, 500, 1000,
                                            3, 11, 1, 12000, 20000))
        right.close()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        message = output.getvalue()
        for field in ("mode=jpeg-decode", "decoded=11", "decode_failed=1",
                      "decode_us=12000/20000", "render=off"):
            self.assertIn(field, message)
        left.close()


if __name__ == "__main__":
    unittest.main()
