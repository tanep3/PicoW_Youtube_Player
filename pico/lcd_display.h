#ifndef PICOW_LCD_DISPLAY_H
#define PICOW_LCD_DISPLAY_H

#include <stdbool.h>
#include <stdint.h>
#include "pico/stdlib.h"
#include "hardware/spi.h"
#include "rgb565_transform.h"
#if PLAYER_LCD_GAMMA_LGFX
#include "lcd_gamma_lgfx.h"
#endif

#define LCD_W 160
#define LCD_H 80
#define FRAME_BYTES (LCD_W * LCD_H * 2)

#if DISPLAY_PROFILE == 0
#define LCD_SPI spi0
#define PIN_CS 17
#define PIN_SCK 18
#define PIN_MOSI 19
#define PIN_DC 20
#define PIN_RES 21
#elif DISPLAY_PROFILE == 1
#define LCD_SPI spi1
#define PIN_CS 9
#define PIN_SCK 10
#define PIN_MOSI 11
#define PIN_DC 12
#define PIN_RES 13
#else
#error "DISPLAY_PROFILE must be 0 or 1"
#endif

static void lcd_select(bool selected) { gpio_put(PIN_CS, !selected); }
static void lcd_command(uint8_t command) {
    gpio_put(PIN_DC, 0);
    lcd_select(true);
    spi_write_blocking(LCD_SPI, &command, 1);
    lcd_select(false);
}
static void lcd_data(const uint8_t *data, size_t length) {
    gpio_put(PIN_DC, 1);
    lcd_select(true);
    spi_write_blocking(LCD_SPI, data, length);
    lcd_select(false);
}
static void lcd_register(uint8_t command, uint8_t value) {
    lcd_command(command);
    lcd_data(&value, 1);
}
static void lcd_init(void) {
    spi_init(LCD_SPI, LCD_SPI_BAUD);
    spi_set_format(LCD_SPI, 8, SPI_CPOL_0, SPI_CPHA_0, SPI_MSB_FIRST);
    gpio_set_function(PIN_SCK, GPIO_FUNC_SPI);
    gpio_set_function(PIN_MOSI, GPIO_FUNC_SPI);
    const uint pins[] = {PIN_CS, PIN_DC, PIN_RES};
    for (unsigned i = 0; i < 3; ++i) { gpio_init(pins[i]); gpio_set_dir(pins[i], GPIO_OUT); }
    lcd_select(false);
    gpio_put(PIN_DC, 1);
    gpio_put(PIN_RES, 0);
    sleep_ms(20);
    gpio_put(PIN_RES, 1);
    sleep_ms(120);
    lcd_command(0x01);
    sleep_ms(150);
    lcd_command(0x11);
    sleep_ms(120);
    lcd_register(0x3A, 0x05); // RGB565
    lcd_register(0x36, LCD_MADCTL);
    lcd_command(LCD_INVERT ? 0x21 : 0x20);
#if PLAYER_LCD_GAMMA_LGFX
    lcd_command(0xE0);
    lcd_data(lcd_gamma_lgfx_positive, sizeof lcd_gamma_lgfx_positive);
    lcd_command(0xE1);
    lcd_data(lcd_gamma_lgfx_negative, sizeof lcd_gamma_lgfx_negative);
#endif
    lcd_command(0x29);
    sleep_ms(20);
}
static void lcd_show(uint8_t *pixels) {
#if PLAYER_ROTATE_180
    // The ready slot belongs to the display loop until SPI completes.
    rgb565_rotate180(pixels, LCD_W * LCD_H);
#endif
    uint16_t x0 = LCD_X_OFFSET, x1 = x0 + LCD_W - 1;
    uint16_t y0 = LCD_Y_OFFSET, y1 = y0 + LCD_H - 1;
    uint8_t range[4];
    range[0] = x0 >> 8; range[1] = x0; range[2] = x1 >> 8; range[3] = x1;
    lcd_command(0x2A); lcd_data(range, sizeof range);
    range[0] = y0 >> 8; range[1] = y0; range[2] = y1 >> 8; range[3] = y1;
    lcd_command(0x2B); lcd_data(range, sizeof range);
    lcd_command(0x2C); lcd_data(pixels, FRAME_BYTES);
}

#endif
