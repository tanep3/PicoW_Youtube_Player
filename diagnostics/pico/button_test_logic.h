#ifndef PICOW_BUTTON_TEST_LOGIC_H
#define PICOW_BUTTON_TEST_LOGIC_H
#include <stdbool.h>
#include <stdint.h>
#define BUTTON_TEST_WIDTH 160
#define BUTTON_TEST_HEIGHT 80
#define BUTTON_TEST_BYTES (BUTTON_TEST_WIDTH * BUTTON_TEST_HEIGHT * 2)
#define BUTTON_DEBOUNCE_MS 35u

typedef struct {
    uint32_t changed_ms;
    uint8_t candidate, stable;
    bool armed;
} ButtonDebouncer;

void buttons_reset(ButtonDebouncer *state, uint8_t raw, uint32_t now);
// Returns the complete stable pressed mask only on a new press; zero otherwise.
uint8_t buttons_update(ButtonDebouncer *state, uint8_t raw, uint32_t now);
void button_test_render(uint8_t pressed_mask, uint8_t frame[BUTTON_TEST_BYTES]);
#endif
