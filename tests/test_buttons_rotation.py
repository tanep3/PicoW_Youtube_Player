import ctypes
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRAME_BYTES = 160 * 80 * 2


class ButtonRotationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        path = Path(cls.directory.name)
        wrapper = path / 'buttons.c'
        wrapper.write_text('''
#include "button_test_logic.h"
static ButtonDebouncer state;
void reset(unsigned raw, unsigned now) { buttons_reset(&state, raw, now); }
unsigned update(unsigned raw, unsigned now) { return buttons_update(&state, raw, now); }
unsigned armed(void) { return state.armed; }
''')
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                        '-I' + str(ROOT / 'pico'), '-I' + str(ROOT / 'diagnostics/pico'),
                        str(wrapper), str(ROOT / 'diagnostics/pico/button_test_logic.c'),
                        '-o', str(path / 'buttons.so')], check=True)
        cls.buttons = ctypes.CDLL(str(path / 'buttons.so'))
        cls.buttons.reset.argtypes = (ctypes.c_uint, ctypes.c_uint)
        cls.buttons.update.argtypes = (ctypes.c_uint, ctypes.c_uint)
        cls.buttons.update.restype = ctypes.c_uint
        cls.buttons.armed.restype = ctypes.c_uint
        cls.buttons.button_test_render.argtypes = (ctypes.c_uint8, ctypes.POINTER(ctypes.c_uint8))

        source = (ROOT / 'diagnostics/pico/button_test.c').read_text()
        gpio = source[source.index('static const uint button_pins'):source.index('static uint8_t frame')]
        wrapper = path / 'gpio.c'
        wrapper.write_text('''
#include <stdint.h>
typedef unsigned uint;
#define GPIO_IN 0
unsigned initialized[30], direction[30], pullup[30], levels[30];
void gpio_init(uint n) { initialized[n]++; }
void gpio_set_dir(uint n, uint d) { direction[n] = d; }
void gpio_pull_up(uint n) { pullup[n]++; levels[n] = 1; }
unsigned gpio_get(uint n) { return levels[n]; }
''' + gpio + '''
void setup(void) { buttons_init(); }
unsigned raw(unsigned pressed) {
    for (unsigned i=0; i<4; ++i) levels[button_pins[i]] = !(pressed & (1u << i));
    return buttons_raw();
}
''')
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                        str(wrapper), '-o', str(path / 'gpio.so')], check=True)
        cls.gpio = ctypes.CDLL(str(path / 'gpio.so'))
        cls.gpio.raw.argtypes = (ctypes.c_uint,)
        cls.gpio.raw.restype = ctypes.c_uint

        source = (ROOT / 'pico/lcd_display.h').read_text()
        show = source[source.index('static void lcd_show('):source.rindex('#endif')]
        wrapper = path / 'show.c'
        wrapper.write_text('''
#include <stdint.h>
#include <string.h>
#include "rgb565_transform.h"
#define LCD_W 160
#define LCD_H 80
#define FRAME_BYTES 25600
#define LCD_X_OFFSET 0
#define LCD_Y_OFFSET 24
uint8_t commands[3], ranges[8], payload[FRAME_BYTES];
unsigned command_count, payload_length;
static uint8_t last_command;
static void lcd_command(uint8_t c) { commands[command_count++] = c; last_command = c; }
static void lcd_data(const uint8_t *p, size_t n) {
    if (last_command == 0x2a) memcpy(ranges, p, n);
    if (last_command == 0x2b) memcpy(ranges + 4, p, n);
    if (last_command == 0x2c) { memcpy(payload, p, n); payload_length = n; }
}
''' + show + '\nvoid display(uint8_t *p) { command_count = 0; lcd_show(p); }\n')
        cls.displays = []
        for enabled in (0, 1):
            out = path / f'show{enabled}.so'
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                            '-DPLAYER_ROTATE_180=' + str(enabled), '-I' + str(ROOT / 'pico'),
                            str(wrapper), '-o', str(out)], check=True)
            dll = ctypes.CDLL(str(out))
            dll.display.argtypes = (ctypes.POINTER(ctypes.c_uint8),)
            cls.displays.append(dll)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_boot_held_button_requires_stable_release_and_new_press(self):
        b = self.buttons
        b.reset(1, 0)
        self.assertEqual(b.update(1, 1000), 0)
        self.assertFalse(b.armed())
        self.assertEqual(b.update(0, 1100), 0)
        self.assertEqual(b.update(0, 1134), 0)
        self.assertFalse(b.armed())
        self.assertEqual(b.update(0, 1135), 0)
        self.assertTrue(b.armed())
        self.assertEqual(b.update(1, 1200), 0)
        self.assertEqual(b.update(1, 1234), 0)
        self.assertEqual(b.update(1, 1235), 1)
        self.assertEqual(b.update(1, 2000), 0)

    def test_bounce_hold_release_multiple_press_and_timer_wrap(self):
        b = self.buttons
        b.reset(0, 0)
        self.assertEqual(b.update(0, 35), 0)
        for raw, now in ((1,100), (0,106), (1,112), (0,114), (1,120), (1,154)):
            self.assertEqual(b.update(raw, now), 0)
        self.assertEqual(b.update(1,155), 1)
        self.assertEqual(b.update(1,300), 0)
        self.assertEqual(b.update(0,310), 0)
        self.assertEqual(b.update(0,345), 0)
        self.assertEqual(b.update(3,400), 0)
        self.assertEqual(b.update(3,435), 3)
        b.reset(0, 0xfffffff0)
        self.assertEqual(b.update(0, 0x13), 0)
        self.assertTrue(b.armed())
        self.assertEqual(b.update(8, 0x20), 0)
        self.assertEqual(b.update(8, 0x42), 0)
        self.assertEqual(b.update(8, 0x43), 8)

    def test_actual_gpio_setup_and_active_low_mapping(self):
        g = self.gpio
        g.setup()
        for name in ('initialized', 'pullup'):
            values = (ctypes.c_uint * 30).in_dll(g, name)
            self.assertEqual([i for i, value in enumerate(values) if value], [12,13,14,15])
        directions = (ctypes.c_uint * 30).in_dll(g, 'direction')
        self.assertEqual([directions[n] for n in (12,13,14,15)], [0]*4)
        for mask in (0,1,2,4,8,3,15):
            self.assertEqual(g.raw(mask), mask)

    def render(self, mask):
        out = (ctypes.c_uint8 * FRAME_BYTES)()
        self.buttons.button_test_render(mask, out)
        def logical(x, y):
            i = 2*(y*160+x)
            wire = ((out[i] << 8) | out[i+1]) ^ 0xffff
            return ((wire & 31) << 11) | (wire & 0x07e0) | (wire >> 11)
        return logical

    def test_shapes_colors_and_unambiguous_wait_multiple_screen(self):
        for mask, color in ((1,0xf800),(2,0x07e0),(4,0x001f),(8,0xffe0)):
            p = self.render(mask)
            self.assertEqual(p(80,40), color)
            self.assertEqual(p(0,0), 0)
        self.assertEqual(self.render(1)(60,20), 0)
        self.assertEqual(self.render(4)(60,20), 0x001f)
        self.assertEqual(self.render(2)(80,18), 0x07e0)
        self.assertEqual(self.render(2)(60,18), 0)
        self.assertEqual(self.render(8)(80,15), 0xffe0)
        self.assertEqual(self.render(8)(55,40), 0xffe0)
        self.assertEqual(self.render(8)(55,15), 0)
        for mask in (0,3):
            p = self.render(mask)
            self.assertEqual({p(x,y) for y in range(80) for x in range(160)}, {0,0x8410})

    def test_actual_lcd_transfer_rotation_preserves_window_color_bits_and_size(self):
        original = b''.join(i.to_bytes(2, 'big') for i in range(12800))
        expected_rotated = b''.join(original[i:i+2] for i in range(FRAME_BYTES-2,-1,-2))
        for enabled, d in enumerate(self.displays):
            data = (ctypes.c_uint8 * FRAME_BYTES).from_buffer_copy(original)
            d.display(data)
            self.assertEqual(bytes((ctypes.c_uint8 * 3).in_dll(d, 'commands')), b'\x2a\x2b\x2c')
            self.assertEqual(bytes((ctypes.c_uint8 * 8).in_dll(d, 'ranges')), b'\x00\x00\x00\x9f\x00\x18\x00\x67')
            self.assertEqual(ctypes.c_uint.in_dll(d, 'payload_length').value, FRAME_BYTES)
            self.assertEqual(bytes((ctypes.c_uint8 * FRAME_BYTES).in_dll(d, 'payload')),
                             expected_rotated if enabled else original)
            if enabled:
                d.display(data)
                self.assertEqual(bytes(data), original)


if __name__ == '__main__':
    unittest.main()
