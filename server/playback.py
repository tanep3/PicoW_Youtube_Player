"""One Pico TCP stream, fed from fixed-frame cache files without loading a movie."""
import socket
import struct
import threading
import time
from .library import FRAME_BYTES
from .streamer import packet, read_status

class Playback:
    def __init__(self, library, lock):
        self.library, self.lock = library, lock
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

    def select(self, conversion):
        with self.lock:
            self.current = dict(conversion)
            self.started = time.monotonic()
            self.generation += 1
            self.force_first = True
            self.library.preference("current", conversion["key"])
            with self.library.db() as db:
                db.execute("UPDATE videos SET played=? WHERE id=?", (time.time(), conversion["video_id"]))

    def stop(self):
        with self.lock:
            self.current = None
            self.generation += 1
            self.library.preference("current", None)
            if self.conn:
                try:
                    self.conn.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def state(self):
        with self.lock:
            current = dict(self.current) if self.current else None
            if current:
                current.pop("path", None)
                current["title"] = self.library.video(current["video_id"])["title"]
                elapsed = max(0, time.monotonic() - self.started)
                current["position"] = (elapsed * current["fps"] % current["frames"]) / current["fps"]
                current["loop"] = int(elapsed * current["fps"] / current["frames"])
            return {"current": current, "connected": self.connected, "sent": self.sent,
                    "timeouts": self.timeouts, "connections": self.connections, "error": self.last_error}

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
            threading.Thread(target=read_status, args=(conn, False), daemon=True).start()
            try:
                self._stream(conn)
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

    def _stream(self, conn):
        opened_generation, source, next_sequence = None, None, 0
        try:
            while not self.closed.is_set():
                with self.lock:
                    current, generation, started = self.current, self.generation, self.started
                    first = self.force_first
                if not current:
                    self.closed.wait(0.05)
                    continue
                if generation != opened_generation:
                    if source:
                        source.close()
                    source = self.library.path(current["path"]).open("rb")
                    opened_generation = generation
                    next_sequence = 0
                due = int(max(0, time.monotonic() - started) * current["fps"])
                if first:
                    sequence = 0
                else:
                    if due < next_sequence:
                        self.closed.wait(min(0.03, (next_sequence-due)/current["fps"]))
                        continue
                    sequence = due
                source.seek(sequence % current["frames"] * FRAME_BYTES)
                payload = source.read(FRAME_BYTES)
                if len(payload) != FRAME_BYTES:
                    raise ValueError("converted cache truncated")
                # Lock through one send prevents deletion or an old frame after a completed switch.
                with self.lock:
                    if self.generation != generation:
                        continue
                    conn.sendall(packet(sequence, payload))
                    self.sent += 1
                    self.force_first = False
                    if first:
                        # Start the timeline at the first successful frame after ready.
                        self.started = time.monotonic()
                        started = self.started
                next_sequence = sequence + 1
        finally:
            if source:
                source.close()

    def close(self):
        self.closed.set()
        self.stop()
        if self.listener:
            self.listener.close()
        if self.thread:
            self.thread.join(timeout=3)
