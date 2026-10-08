#include "jpeg_decode.h"
#include "third_party/tjpgd/lgfx_tjpgd.h"
#include <string.h>

#define IMAGE_W 160u
#define IMAGE_H 80u

typedef struct {
    const uint8_t *input;
    size_t length;
    size_t offset;
    uint8_t *output;
    int invalid_tile;
} JpegSession;

// The decoder's input callback also uses NULL destination to skip a segment.
static uint32_t read_jpeg(void *context, uint8_t *destination, uint32_t requested) {
    JpegSession *session = context;
    size_t remaining = session->length - session->offset;
    size_t count = requested < remaining ? requested : remaining;
    if (destination) memcpy(destination, session->input + session->offset, count);
    session->offset += count;
    return (uint32_t)count;
}

static uint32_t write_tile(void *context, void *pixels, JRECT *rect) {
    JpegSession *session = context;
    if (rect->left > rect->right || rect->top > rect->bottom ||
        rect->right >= IMAGE_W || rect->bottom >= IMAGE_H) {
        session->invalid_tile = 1;
        return 0;
    }
    const uint8_t *source = pixels;
    for (uint32_t y = rect->top; y <= rect->bottom; ++y) {
        for (uint32_t x = rect->left; x <= rect->right; ++x) {
            uint8_t red = *source++, green = *source++, blue = *source++;
            uint16_t color = ((uint16_t)(red & 0xf8) << 8) |
                             ((uint16_t)(green & 0xfc) << 3) | (blue >> 3);
            size_t index = 2 * (y * IMAGE_W + x);
            session->output[index] = color >> 8;
            session->output[index + 1] = color;
        }
    }
    return 1;
}

int jpeg_decode_frame(const uint8_t *jpeg, size_t length, uint8_t *rgb565) {
    if (!jpeg || !rgb565 || length < 4 || length > JPEG_MAX_BYTES ||
        jpeg[0] != 0xff || jpeg[1] != 0xd8 ||
        jpeg[length - 2] != 0xff || jpeg[length - 1] != 0xd9) return -1;
    // A single main-loop caller owns the decoder workspace; no concurrent decode.
    static uint8_t work[JPEG_WORK_BYTES];
    lgfxJdec decoder = {0};
    JpegSession session = {.input = jpeg, .length = length, .output = rgb565};
    JRESULT result = lgfx_jd_prepare(&decoder, read_jpeg, work, sizeof work, &session);
    if (result != JDR_OK) return -3;
    if (decoder.width != IMAGE_W || decoder.height != IMAGE_H) return -2;
    result = lgfx_jd_decomp(&decoder, write_tile, 0);
    if (result != JDR_OK || session.invalid_tile) return -3;
    return 0;
}
