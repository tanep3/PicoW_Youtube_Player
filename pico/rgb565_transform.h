#ifndef PICOW_RGB565_TRANSFORM_H
#define PICOW_RGB565_TRANSFORM_H
#include <stddef.h>
#include <stdint.h>

// Swap complete big-endian pixels; byte order and all color bits stay intact.
static inline void rgb565_rotate180(uint8_t *pixels, size_t count) {
    if (count < 2) return;
    for (size_t left = 0, right = count - 1; left < right; ++left, --right) {
        uint8_t high = pixels[2 * left], low = pixels[2 * left + 1];
        pixels[2 * left] = pixels[2 * right];
        pixels[2 * left + 1] = pixels[2 * right + 1];
        pixels[2 * right] = high;
        pixels[2 * right + 1] = low;
    }
}

// Same inverse + red/blue swap as the verified Pi5 RAW sender.
static inline uint16_t rgb565_panel_compensate(uint16_t color) {
    color ^= 0xffff;
    return (uint16_t)(((color & 0x001f) << 11) | (color & 0x07e0) | (color >> 11));
}
#endif
