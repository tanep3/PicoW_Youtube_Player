#ifndef PICOW_LCD_GAMMA_LGFX_H
#define PICOW_LCD_GAMMA_LGFX_H

#include <stdint.h>

// One positive/negative pair from the local LovyanGFX Panel_ST7735S Rcmd2.
// Only E0/E1 are used; frame, power, VCOM, inversion and rotation stay unchanged.
static const uint8_t lcd_gamma_lgfx_positive[16] = {
    0x02, 0x1C, 0x07, 0x12, 0x37, 0x32, 0x29, 0x2D,
    0x29, 0x25, 0x2B, 0x39, 0x00, 0x01, 0x03, 0x10
};
static const uint8_t lcd_gamma_lgfx_negative[16] = {
    0x03, 0x1D, 0x07, 0x06, 0x2E, 0x2C, 0x29, 0x2D,
    0x2E, 0x2E, 0x37, 0x3F, 0x00, 0x00, 0x02, 0x10
};
_Static_assert(sizeof lcd_gamma_lgfx_positive == 16, "E0 needs 16 data bytes");
_Static_assert(sizeof lcd_gamma_lgfx_negative == 16, "E1 needs 16 data bytes");

#endif
