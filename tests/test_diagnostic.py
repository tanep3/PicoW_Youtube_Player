import unittest

from diagnostics.server import lcd_pattern as diagnostic
from server.streamer import PAYLOAD_SIZE


class DiagnosticTests(unittest.TestCase):
    def test_solid_colors_have_rgb565_network_byte_order(self):
        self.assertEqual(diagnostic.solid(0xF800)[:4], bytes.fromhex("f800f800"))
        self.assertEqual(diagnostic.solid(0x07E0)[:2], bytes.fromhex("07e0"))
        self.assertEqual(diagnostic.solid(0x001F)[:2], bytes.fromhex("001f"))
        self.assertEqual(len(diagnostic.PATTERN), PAYLOAD_SIZE)

    def test_outer_rows_and_inner_rows(self):
        pixels = diagnostic.geometry()
        def at(x, y):
            position = 2 * (y * 160 + x)
            return pixels[position:position + 2]
        self.assertEqual(at(80, 0), bytes.fromhex("ffff"))
        self.assertEqual(at(80, 1), bytes.fromhex("f800"))
        self.assertEqual(at(80, 2), bytes.fromhex("07e0"))
        self.assertEqual(at(80, 3), bytes.fromhex("001f"))
        self.assertEqual(at(80, 4), bytes.fromhex("0000"))
        self.assertEqual(at(80, 10), bytes.fromhex("f800"))
        self.assertEqual(at(80, 22), bytes.fromhex("07e0"))
        self.assertEqual(at(80, 34), bytes.fromhex("001f"))
        self.assertEqual(at(80, 45), bytes.fromhex("0000"))
        self.assertEqual(at(80, 79), bytes.fromhex("ffff"))
        self.assertEqual(at(0, 40), bytes.fromhex("ffff"))
        self.assertEqual(at(159, 40), bytes.fromhex("ffff"))

    def test_color_precompensation(self):
        transform = diagnostic.compensate_inversion_and_bgr
        self.assertEqual(transform(bytes.fromhex("0000ffff")), bytes.fromhex("ffff0000"))
        self.assertEqual(transform(bytes.fromhex("f80007e0001f")), bytes.fromhex("ffe0f81f07ff"))


if __name__ == "__main__":
    unittest.main()
