#include "button_test_logic.h"
#include "rgb565_transform.h"

void buttons_reset(ButtonDebouncer *s, uint8_t raw, uint32_t now) {
    s->changed_ms = now;
    s->candidate = s->stable = raw & 15u;
    s->armed = false;
}

uint8_t buttons_update(ButtonDebouncer *s, uint8_t raw, uint32_t now) {
    raw &= 15u;
    if (raw != s->candidate) { s->candidate = raw; s->changed_ms = now; }
    if ((uint32_t)(now - s->changed_ms) < BUTTON_DEBOUNCE_MS) return 0;
    if (!s->armed) {
        s->stable = raw;
        if (raw == 0) s->armed = true; // Require a stable release after startup.
        return 0;
    }
    uint8_t pressed = raw & (uint8_t)~s->stable;
    s->stable = raw;
    return pressed ? raw : 0;
}

static void pixel(uint8_t *frame, int x, int y, uint16_t color) {
    if (x < 0 || y < 0 || x >= BUTTON_TEST_WIDTH || y >= BUTTON_TEST_HEIGHT) return;
    uint16_t wire = rgb565_panel_compensate(color);
    unsigned at = 2u * (unsigned)(y * BUTTON_TEST_WIDTH + x);
    frame[at] = wire >> 8;
    frame[at + 1] = wire;
}

static const uint8_t *glyph(char c) {
    static const uint8_t chars[][5] = {
        {0x3f,0x40,0x38,0x40,0x3f}, // W
        {0x7e,0x11,0x11,0x11,0x7e}, // A
        {0,0x41,0x7f,0x41,0},       // I
        {1,1,0x7f,1,1},             // T
        {0x7f,2,0x0c,2,0x7f},       // M
        {0x3f,0x40,0x40,0x40,0x3f}, // U
        {0x7f,0x40,0x40,0x40,0x40}, // L
        {0,0x42,0x7f,0x40,0},       // 1
        {0x42,0x61,0x51,0x49,0x46}, // 2
        {0x21,0x41,0x45,0x4b,0x31}, // 3
        {0x18,0x14,0x12,0x7f,0x10}  // 4
    };
    switch (c) {
        case 'W': return chars[0]; case 'A': return chars[1];
        case 'I': return chars[2]; case 'T': return chars[3];
        case 'M': return chars[4]; case 'U': return chars[5]; case 'L': return chars[6];
        case '1': return chars[7]; case '2': return chars[8];
        case '3': return chars[9]; case '4': return chars[10];
        default: return 0;
    }
}

static void text(uint8_t *frame, int x, int y, const char *s, uint16_t color) {
    for (; *s; ++s, x += 12) {
        const uint8_t *g = glyph(*s);
        if (!g) continue;
        for (int col = 0; col < 5; ++col)
            for (int row = 0; row < 7; ++row)
                if (g[col] & (1u << row))
                    for (int dx = 0; dx < 2; ++dx)
                        for (int dy = 0; dy < 2; ++dy)
                            pixel(frame, x + 2 * col + dx, y + 2 * row + dy, color);
    }
}

void button_test_render(uint8_t mask, uint8_t frame[BUTTON_TEST_BYTES]) {
    mask &= 15u;
    for (int y = 0; y < BUTTON_TEST_HEIGHT; ++y)
        for (int x = 0; x < BUTTON_TEST_WIDTH; ++x) pixel(frame, x, y, 0);
    if (!mask || (mask & (mask - 1u))) {
        for (int x = 0; x < BUTTON_TEST_WIDTH; ++x) {
            pixel(frame, x, 0, 0x8410); pixel(frame, x, BUTTON_TEST_HEIGHT-1, 0x8410);
        }
        for (int y = 0; y < BUTTON_TEST_HEIGHT; ++y) {
            pixel(frame, 0, y, 0x8410); pixel(frame, BUTTON_TEST_WIDTH-1, y, 0x8410);
        }
        text(frame, mask ? 50 : 56, 32, mask ? "MULTI" : "WAIT", 0x8410);
        return;
    }
    unsigned button = mask == 1 ? 1 : (mask == 2 ? 2 : (mask == 4 ? 3 : 4));
    uint16_t color = button == 1 ? 0xf800 : (button == 2 ? 0x07e0 : (button == 3 ? 0x001f : 0xffe0));
    for (int y = 0; y < BUTTON_TEST_HEIGHT; ++y) {
        for (int x = 0; x < BUTTON_TEST_WIDTH; ++x) {
            int dx = x - 80, dy = y - 40;
            int ax = dx < 0 ? -dx : dx, ay = dy < 0 ? -dy : dy;
            bool inside = button == 1 ? dx*dx + dy*dy <= 25*25 :
                (button == 2 ? y >= 18 && y <= 62 && ax*44 <= (y-18)*27 :
                (button == 3 ? ax <= 25 && ay <= 25 :
                ((ax <= 5 && ay <= 25) || (ay <= 5 && ax <= 25))));
            if (inside) pixel(frame, x, y, color);
        }
    }
    char number[2] = {(char)('0' + button), 0};
    text(frame, 8, 8, number, 0xffff);
}
