import contextlib
import ctypes
import io
import socket
import struct
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from server import streamer as server

ROOT = Path(__file__).resolve().parents[1]

class Tcp(ctypes.Structure):
    _fields_ = [('src_port', ctypes.c_uint16), ('dst_port', ctypes.c_uint16),
                ('payload_len', ctypes.c_uint16), ('flags', ctypes.c_uint8),
                ('seq', ctypes.c_uint32), ('ack', ctypes.c_uint32),
                ('payload', ctypes.c_void_p)]

class Event(ctypes.Structure):
    _fields_ = [('serial', ctypes.c_uint32), ('ms', ctypes.c_uint32),
                ('seq', ctypes.c_uint32), ('src_port', ctypes.c_uint16),
                ('dst_port', ctypes.c_uint16), ('payload_len', ctypes.c_uint16),
                ('type', ctypes.c_uint8), ('tx_class', ctypes.c_uint8)]

class Snapshot(ctypes.Structure):
    _fields_ = [('counters', ctypes.c_uint32 * 20), ('events', Event * 8)]


def ethernet_tcp(payload=b'PWS4', seq=100, src=16151, dst=50000, flags=0x18):
    ethernet = bytes(12) + bytes.fromhex('0800')
    ip = bytearray(20)
    ip[0] = 0x45
    ip[2:4] = (40 + len(payload)).to_bytes(2, 'big')
    ip[9] = 6
    tcp = bytearray(20)
    tcp[0:2] = src.to_bytes(2, 'big')
    tcp[2:4] = dst.to_bytes(2, 'big')
    tcp[4:8] = seq.to_bytes(4, 'big')
    tcp[8:12] = (500).to_bytes(4, 'big')
    tcp[12] = 0x50
    tcp[13] = flags
    return ethernet + ip + tcp + payload


class Cyw43DiagTests(unittest.TestCase):
    def test_parser_and_counter_ring(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / 'libdiag.so'
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-fPIC',
                            '-shared', str(ROOT / 'diagnostics/pico/cyw43_diag.c'),
                            '-o', str(library)], check=True)
            diag = ctypes.CDLL(str(library))
            diag.cyw43_diag_parse_tcp.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                                   ctypes.POINTER(Tcp)]
            diag.cyw43_diag_parse_tcp.restype = ctypes.c_bool
            diag.cyw43_diag_classify_tx.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
            diag.cyw43_diag_classify_tx.restype = ctypes.c_uint8
            diag.cyw43_diag_fingerprint.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
            diag.cyw43_diag_fingerprint.restype = ctypes.c_uint32
            diag.cyw43_diag_credit_drop.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                                     ctypes.c_uint8, ctypes.c_uint32]
            diag.cyw43_diag_normal_rx.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                                  ctypes.c_uint32]
            diag.cyw43_diag_pbuf_fail.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                                  ctypes.c_uint32]
            diag.cyw43_diag_wait_enter.argtypes = [ctypes.c_uint8]
            diag.cyw43_diag_wait_finish.argtypes = [ctypes.c_uint32, ctypes.c_bool]
            diag.cyw43_diag_snapshot.argtypes = [ctypes.POINTER(Snapshot)]
            pkt = ethernet_tcp()
            t = Tcp()
            self.assertTrue(diag.cyw43_diag_parse_tcp(pkt, len(pkt), ctypes.byref(t)))
            self.assertEqual((t.src_port, t.dst_port, t.seq, t.payload_len),
                             (16151, 50000, 100, 4))
            self.assertEqual(diag.cyw43_diag_classify_tx(pkt, len(pkt)), 2)
            ack = ethernet_tcp(b'', flags=0x10)
            self.assertEqual(diag.cyw43_diag_classify_tx(ack, len(ack)), 1)
            self.assertFalse(diag.cyw43_diag_parse_tcp(pkt[:-1], len(pkt)-1, ctypes.byref(t)))
            fragment = bytearray(pkt)
            fragment[20:22] = bytes.fromhex('0001')
            self.assertFalse(diag.cyw43_diag_parse_tcp(bytes(fragment), len(fragment), ctypes.byref(t)))
            changed = bytearray(pkt)
            changed[20] ^= 1
            self.assertNotEqual(diag.cyw43_diag_fingerprint(pkt, len(pkt)),
                                diag.cyw43_diag_fingerprint(bytes(changed), len(changed)))
            diag.cyw43_diag_wait_enter(1)
            diag.cyw43_diag_wait_finish(1500, True)
            diag.cyw43_diag_credit_drop(pkt, len(pkt), 1, 12345)
            diag.cyw43_diag_normal_rx(pkt, len(pkt), 12346)
            next_pkt = ethernet_tcp(b'abcd', seq=110)
            diag.cyw43_diag_normal_rx(next_pkt, len(next_pkt), 12347)
            diag.cyw43_diag_lwip_rx()
            diag.cyw43_diag_pbuf_fail(next_pkt, len(next_pkt), 12348)
            snap = Snapshot()
            diag.cyw43_diag_snapshot(ctypes.byref(snap))
            c = list(snap.counters)
            self.assertEqual(c[:8], [1, 1, 0, 0, 1, 1500, 1, 1])
            self.assertEqual((c[9], c[10], c[11], c[13], c[17], c[18], c[19]),
                             (2, 1, 1, 1, 12345, 100, 3))
            self.assertEqual([e.type for e in snap.events[:3]], [1, 2, 4])
            self.assertEqual([e.seq for e in snap.events[:3]], [100, 110, 110])
            for number in range(20):
                extra = ethernet_tcp(b'abcd', seq=200 + 4 * number)
                diag.cyw43_diag_credit_drop(extra, len(extra), 2, 13000 + number)
            diag.cyw43_diag_snapshot(ctypes.byref(snap))
            self.assertEqual(snap.counters[19], 23)
            self.assertEqual([e.serial for e in snap.events], list(range(16, 24)))
            self.assertEqual((snap.counters[17], snap.counters[18]), (12345, 100))

    def test_pws4_fragmented_status_and_event(self):
        self.assertEqual(server.STATUS_V4.size, 320)
        base = server.STATUS_V3.pack(b'PWS4', bytes.fromhex('28cd01020304'), 1,
                                     0x80, 10, 8, 2, 15500, 22000,
                                     -127, 18, 0, 0, 0, 300, 800,
                                     1, 0, 0, 0, 0)
        counters = [1, 1, 0, 0, 0, 1500, 1, 1, 1, 12,
                    12, 0, 0, 0, 0, 0, 0, 12345, 100, 1]
        events = struct.pack('>IIIHHHBB', 1, 12345, 100, 16151, 50000, 4, 1, 1)
        message = base + struct.pack('>20I', *counters) + events + bytes(7 * 20)
        left, right = socket.socketpair()
        output = io.StringIO()
        def receive():
            with contextlib.redirect_stdout(output):
                server.read_status(left)
        worker = threading.Thread(target=receive)
        worker.start()
        right.sendall(message[:31]); right.sendall(message[31:])
        right.close()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        text = output.getvalue()
        for item in ('credit_drop=1', 'credit_tcp_data=1', 'tx_buffer_changed=1',
                     'CYW43 event=1', 'tcp_seq=0x00000064', 'mode=raw-display'):
            self.assertIn(item, text)
        left.close()

if __name__ == '__main__':
    unittest.main()
