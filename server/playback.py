"""One Pico TCP stream, fed from fixed-frame cache files without loading a movie."""
import socket
import struct
import threading
import time
from .library import FRAME_BYTES
from .streamer import packet, read_status
from .frame_cache import FrameReader

class Playback:
    def __init__(self, library, lock):
        self.library, self.lock = library, lock
        self.send_gate = threading.Condition(lock)
        self.reading = False
        self.sending = False
        self.transitions = 0
        self.current = None
        self.started = 0.0
        self.generation = 0
        self.connected = False
        self.sent = self.timeouts = self.connections = 0
        self.last_error = None
        self.conn = None
        self.closed = threading.Event()
        self.listener = None
        self.thread = None
        self.force_first = False
        self.last_decode_us = self.max_decode_us = 0

    def select(self, conversion, check=None):
        with self.send_gate:
            self.transitions += 1
            try:
                while self.reading or self.sending:
                    self.send_gate.wait()
                if check:
                    check()
                self.current = dict(conversion)
                self.started = time.monotonic()
                self.generation += 1
                self.force_first = True
                self.library.preference("current", conversion["key"])
                with self.library.db() as db:
                    db.execute("UPDATE videos SET played=? WHERE id=?", (time.time(), conversion["video_id"]))
            finally:
                self.transitions -= 1
                self.send_gate.notify_all()

    def stop(self):
        with self.send_gate:
            self.transitions += 1
            try:
                while self.reading or self.sending:
                    self.send_gate.wait()
                self.current = None
                self.generation += 1
                self.library.preference("current", None)
                conn = self.conn
            finally:
                self.transitions -= 1
                self.send_gate.notify_all()
        if conn:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def state(self):
        with self.lock:
            current = dict(self.current) if self.current else None
            result = {"connected": self.connected, "sent": self.sent,
                      "timeouts": self.timeouts, "connections": self.connections, "error": self.last_error,
                      "decode_us": self.last_decode_us, "decode_max_us": self.max_decode_us}
            started = self.started
            if current:
                current.pop("path", None)
                elapsed = max(0, time.monotonic() - started)
                current["position"] = (elapsed * current["fps"] % current["frames"]) / current["fps"]
                current["loop"] = int(elapsed * current["fps"] / current["frames"])
        if current:
            video = self.library.video(current["video_id"])
            current["title"] = video["title"] if video else ""
        return {"current": current, **result}

    def start(self, host, port):
        self.listener = socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind((host, port))
        self.listener.listen(1)
        self.listener.settimeout(0.5)
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()
        return self.listener.getsockname()[1]

    def _serve(self):
        while not self.closed.is_set():
            try:
                conn, peer = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with self.lock:
                self.conn, self.connected = conn, True
                self.connections += 1
            print(f"Web player Pico connected: {peer}", flush=True)
            conn.settimeout(2)
            peer_closed = threading.Event()
            def statuses(connection=conn, done=peer_closed):
                try:
                    read_status(connection, False)
                finally:
                    done.set()
            threading.Thread(target=statuses, daemon=True).start()
            try:
                self._stream(conn, peer_closed)
            except TimeoutError:
                with self.lock:
                    self.timeouts += 1
                try:
                    conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                except OSError:
                    pass
            except (OSError, ValueError) as exc:
                self.last_error = str(exc)
            finally:
                conn.close()
                with self.lock:
                    self.connected, self.conn = False, None

    def _stream(self, conn, peer_closed=None):
        opened_generation, source, next_sequence = None, None, 0
        try:
            while not self.closed.is_set():
                if peer_closed is not None and peer_closed.is_set():
                    return
                with self.lock:
                    current, generation, started = self.current, self.generation, self.started
                    first = self.force_first
                if not current:
                    if opened_generation is not None:
                        return
                    self.closed.wait(0.05)
                    continue
                if generation != opened_generation:
                    next_sequence = 0
                due = int(max(0, time.monotonic() - started) * current["fps"])
                if first:
                    sequence = 0
                else:
                    if due < next_sequence:
                        self.closed.wait(min(0.03, (next_sequence-due)/current["fps"]))
                        continue
                    sequence = due
                with self.send_gate:
                    if self.generation != generation or self.transitions:
                        continue
                    self.reading = True
                try:
                    if generation != opened_generation:
                        if source:
                            source.close()
                        source = FrameReader(self.library.path(current["path"]), current)
                        opened_generation = generation
                    decode_started = time.monotonic_ns()
                    payload = source.read(sequence % current["frames"])
                    self.last_decode_us = (time.monotonic_ns()-decode_started)//1000 if source.kind == "jpeg" else 0
                    self.max_decode_us = max(self.max_decode_us, self.last_decode_us)
                    frame = packet(sequence, payload)
                finally:
                    with self.send_gate:
                        self.reading = False
                        self.send_gate.notify_all()
                with self.send_gate:
                    if self.generation != generation or self.transitions:
                        continue
                    self.sending = True
                sent_ok = False
                try:
                    conn.sendall(frame)  # No application lock held during network I/O.
                    sent_ok = True
                finally:
                    with self.send_gate:
                        if sent_ok:
                            self.sent += 1
                            self.force_first = False
                            if first:
                                self.started = time.monotonic()
                                started = self.started
                        self.sending = False
                        self.send_gate.notify_all()
                next_sequence = sequence + 1
        finally:
            if source:
                source.close()

    def close(self):
        self.closed.set()
        with self.send_gate:
            self.transitions += 1
            try:
                while self.reading or self.sending:
                    self.send_gate.wait()
                conn = self.conn
            finally:
                self.transitions -= 1
                self.send_gate.notify_all()
        if conn:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        # Preserve the chosen cache on shutdown; only the user's Stop clears it.
        if self.listener:
            self.listener.close()
        if self.thread:
            self.thread.join(timeout=3)
