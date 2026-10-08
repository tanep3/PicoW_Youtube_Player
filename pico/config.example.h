#pragma once

// Copy to config.h and edit locally. The example values cannot reach a real server.
#define WIFI_SSID "SET_WIFI_SSID"
#define WIFI_PASSWORD "SET_WIFI_PASSWORD"
#define SERVER_IP "192.0.2.1"
#define SERVER_PORT 16151

// 0: existing breadboard SPI0 pins; 1: proposed back-to-back SPI1 pins.
#ifndef DISPLAY_PROFILE
#define DISPLAY_PROFILE 0
#endif

// Board back silkscreen identifies ST7735S; offsets/colors still need display test.
#define LCD_SPI_BAUD 20000000
#define LCD_MADCTL 0x60  // landscape: MV | MX; toggle BGR bit 0x08 if colors swap
#define LCD_X_OFFSET 0
#define LCD_Y_OFFSET 24
#define LCD_INVERT 1
