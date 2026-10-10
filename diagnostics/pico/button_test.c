#include "pico/stdlib.h"
#include "lcd_display.h"
#include "button_test_logic.h"

// GP12..15 share GND, internal pull-ups, active LOW.
static const uint button_pins[4] = {12, 13, 14, 15};
static void buttons_init(void) {
    for (unsigned i = 0; i < 4; ++i) {
        gpio_init(button_pins[i]);
        gpio_set_dir(button_pins[i], GPIO_IN);
        gpio_pull_up(button_pins[i]);
    }
}
static uint8_t buttons_raw(void) {
    uint8_t mask = 0;
    for (unsigned i = 0; i < 4; ++i)
        if (!gpio_get(button_pins[i])) mask |= 1u << i;
    return mask;
}

static uint8_t frame[BUTTON_TEST_BYTES];
_Static_assert(BUTTON_TEST_BYTES == FRAME_BYTES, "button/LCD dimensions differ");
_Static_assert(DISPLAY_PROFILE == 0, "GP12/13 buttons conflict with the SPI1 LCD proposal");
_Static_assert(PLAYER_ROTATE_180 == 0, "stage1 keeps the current screen orientation");

int main(void) {
    buttons_init();
    lcd_init();
    ButtonDebouncer state;
    buttons_reset(&state, buttons_raw(), to_ms_since_boot(get_absolute_time()));
    button_test_render(0, frame);
    lcd_show(frame);
    for (;;) {
        uint8_t press = buttons_update(&state, buttons_raw(), to_ms_since_boot(get_absolute_time()));
        if (press) { button_test_render(press, frame); lcd_show(frame); }
        sleep_ms(1);
    }
}
