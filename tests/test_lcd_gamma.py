import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from diagnostics.server.lcd_gamma_ab import prepare_assets
from server.frame_cache import FrameReader
from server.streamer import image_rgb565

ROOT = Path(__file__).resolve().parents[1]


class LcdGammaTests(unittest.TestCase):
    def test_actual_lcd_init_adds_only_the_positive_negative_pair(self):
        source = (ROOT / 'pico/lcd_display.h').read_text()
        begin = source.index('static void lcd_register(')
        end = source.index('static void lcd_show(', begin)
        actual_init = source[begin:end]
        harness = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#if PLAYER_LCD_GAMMA_LGFX
#include "lcd_gamma_lgfx.h"
#endif
typedef unsigned uint;
#define LCD_SPI 0
#define LCD_SPI_BAUD 20000000
#define LCD_MADCTL 0x60
#define LCD_INVERT 1
#define PIN_CS 17
#define PIN_SCK 18
#define PIN_MOSI 19
#define PIN_DC 20
#define PIN_RES 21
#define SPI_CPOL_0 0
#define SPI_CPHA_0 0
#define SPI_MSB_FIRST 0
#define GPIO_FUNC_SPI 1
#define GPIO_OUT 1
static void spi_init(int spi, unsigned baud) { printf("SPI:%d:%u\n", spi, baud); }
static void spi_set_format(int spi, int bits, int cpol, int cpha, int order) { printf("FORMAT:%d:%d:%d:%d:%d\n",spi,bits,cpol,cpha,order); }
static void gpio_set_function(uint pin, int function) { printf("FUNCTION:%u:%d\n",pin,function); }
static void gpio_init(uint pin) { printf("INIT:%u\n",pin); }
static void gpio_set_dir(uint pin, int direction) { printf("DIR:%u:%d\n",pin,direction); }
static void gpio_put(uint pin, int value) { printf("PUT:%u:%d\n",pin,value); }
static void lcd_select(bool value) { printf("SELECT:%d\n",value); }
static void sleep_ms(unsigned ms) { printf("SLEEP:%u\n",ms); }
static void lcd_command(uint8_t command) { printf("C:%02x\n",command); }
static void lcd_data(const uint8_t *data, size_t length) {
    printf("D:");
    for (size_t i=0; i<length; ++i) printf("%02x",data[i]);
    printf("\n");
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            c = Path(tmp) / 'init.c'
            c.write_text(harness + actual_init + '\nint main(void) { lcd_init(); return 0; }\n')
            results = []
            for enabled in (0, 1):
                binary = Path(tmp) / str(enabled)
                subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                                '-DPLAYER_LCD_GAMMA_LGFX=' + str(enabled),
                                '-I' + str(ROOT / 'pico'), str(c), '-o', str(binary)], check=True)
                results.append(subprocess.check_output([str(binary)], text=True).splitlines())
        baseline, comparison = results
        pair = ['C:e0', 'D:021c07123732292d29252b3900010310',
                'C:e1', 'D:031d07062e2c292d2e2e373f00000210']
        index = comparison.index('C:e0')
        self.assertEqual(comparison[index:index+4], pair)
        self.assertEqual(comparison[:index] + comparison[index+4:], baseline)
        self.assertEqual([s for s in baseline if s.startswith('C:')],
                         ['C:01', 'C:11', 'C:3a', 'C:36', 'C:21', 'C:29'])
        self.assertIn('D:05', baseline)
        self.assertIn('D:60', baseline)
        self.assertIn('SPI:0:20000000', baseline)

    def test_reference_bytes_and_payload_use_the_normal_color_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            photos = directory / 'photos'
            photos.mkdir()
            for n, value in ((600, 192), (1400, 32)):
                Image.new('RGB', (160, 80), (value, value, value)).save(photos / f'frame{n:08d}.jpg', 'JPEG')
            chart = directory / 'ramp.png'
            image = Image.new('RGB', (160, 80))
            for x in range(160):
                for y in range(80):image.putpixel((x, y), (x*255//159,) * 3)
            image.save(chart)
            manifest = prepare_assets(photos, chart, directory / 'output')
            self.assertEqual(manifest, prepare_assets(photos, chart, directory / 'output'))
            reader = FrameReader(photos, {'conditions': {'storage': 'jpeg-directory'}})
            try:
                expected = [reader.read(599), reader.read(1399), image_rgb565(image, compensate_colors=True)]
            finally:reader.close()
            for item, payload in zip(manifest['references'], expected):
                self.assertEqual((directory / 'output' / item['name']).read_bytes(), Path(item['source']).read_bytes())
                self.assertEqual(item['payload_sha256'], hashlib.sha256(payload).hexdigest())
                self.assertEqual(item['payload_bytes'], 25600)
                self.assertEqual(item['packet_bytes'], 25620)


if __name__ == '__main__':
    unittest.main()
