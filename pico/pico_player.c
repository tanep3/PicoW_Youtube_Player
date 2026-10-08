#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include "jpeg_decode.h"
#if PLAYER_LCD_GAMMA_LGFX
#include "lcd_gamma_lgfx.h"
#endif

#include "pico/stdlib.h"
#include "pico/cyw43_arch.h"
#include "hardware/spi.h"
#include "lwip/pbuf.h"
#include "lwip/tcp.h"
#include "lwip/ip_addr.h"
#include "lwip/memp.h"
#include "lwip/stats.h"
#if PLAYER_CYW43_DIAG
#include "cyw43_diag.h"
#define STATUS_BYTES 320
#else
#define STATUS_BYTES 80
#endif

#if __has_include("config.h")
#include "config.h"
#else
#include "config.example.h"
#endif

#define LCD_W 160
#define LCD_H 80
#define FRAME_BYTES (LCD_W * LCD_H * 2)
#define HEADER_BYTES 20
// PWF2 mode: 0=RAW receive, 1=RAW display, 2=JPEG receive,
// 3=JPEG decode only, 4=JPEG decode and display.
#define MODE_RAW_RX 0u
#define MODE_RAW_DISPLAY 1u
#define MODE_JPEG_RX 2u
#define MODE_JPEG_DECODE 3u
#define MODE_JPEG_DISPLAY 4u
// A/B comparison: leave the PWS2 RSSI field at -127 and skip only its ioctl.
#define SAMPLE_RSSI 0
// Public cyw43_ioctl command encoding is (WLC_GET_PM << 1); WLC_GET_PM is 85.
#define CYW43_IOCTL_GET_PM (85u << 1)

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

// Network callbacks may run during SPI transfer. Ready slots are never overwritten.
static uint8_t frames[2][FRAME_BYTES];
static uint8_t jpeg_slots[2][JPEG_MAX_BYTES];
static uint8_t jpeg_pixels[FRAME_BYTES];
static volatile bool ready[2];
static uint32_t slot_sequence[2];
static size_t slot_length[2];
static uint32_t incoming_sequence;
static uint8_t header[HEADER_BYTES];
static size_t received;
static bool reading_header = true;
static bool discard_frame;
static size_t payload_bytes;
static uint32_t active_mode;
static int connection_mode = -1;
static int fill_slot;
static struct tcp_pcb *volatile connection;
static volatile bool connected;
static uint32_t last_receive_ms;
static uint8_t sta_mac[6];
static bool wifi_pm_disabled;
// PWS2 byte 11: 0=pending, 0x80|mode=read success, 0x40|error=read failure.
static uint8_t wifi_pm_readback;
static bool wifi_pm_readback_done;
static volatile uint32_t frames_received;
static volatile uint32_t frames_displayed;
static volatile uint32_t frames_dropped;
static volatile uint32_t frames_decoded;
static volatile uint32_t decode_failed;
static volatile uint32_t last_decode_us;
static volatile uint32_t max_decode_us;
static volatile uint32_t last_spi_us;
static volatile uint32_t max_spi_us;
static uint32_t last_status_ms;
static uint32_t last_rssi_ms;
static int32_t rssi_dbm = -127; // sentinel until a successful sample
static volatile uint32_t max_receive_callback_us;
static volatile uint32_t max_receive_gap_ms;

static uint16_t be16(const uint8_t *p) { return ((uint16_t)p[0] << 8) | p[1]; }
static uint32_t be32(const uint8_t *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
}

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
static void lcd_show(const uint8_t *pixels) {
    uint16_t x0 = LCD_X_OFFSET, x1 = x0 + LCD_W - 1;
    uint16_t y0 = LCD_Y_OFFSET, y1 = y0 + LCD_H - 1;
    uint8_t range[4];
    range[0] = x0 >> 8; range[1] = x0; range[2] = x1 >> 8; range[3] = x1;
    lcd_command(0x2A); lcd_data(range, sizeof range);
    range[0] = y0 >> 8; range[1] = y0; range[2] = y1 >> 8; range[3] = y1;
    lcd_command(0x2B); lcd_data(range, sizeof range);
    lcd_command(0x2C); lcd_data(pixels, FRAME_BYTES);
}

static void show_test_pattern(void) {
    // White edge and red/green/blue bands expose inversion and clipped edges.
    for (unsigned y = 0; y < LCD_H; ++y) {
        for (unsigned x = 0; x < LCD_W; ++x) {
            uint16_t color = (x == 0 || y == 0 || x == LCD_W - 1 || y == LCD_H - 1)
                ? 0xFFFF : (y < 27 ? 0xF800 : (y < 54 ? 0x07E0 : 0x001F));
            unsigned pos = 2 * (y * LCD_W + x);
            frames[0][pos] = color >> 8;
            frames[0][pos + 1] = color;
        }
    }
    lcd_show(frames[0]);
    sleep_ms(3000);
}

static void put_be32(uint8_t *p, uint32_t value) {
    p[0] = value >> 24; p[1] = value >> 16; p[2] = value >> 8; p[3] = value;
}
#if PLAYER_CYW43_DIAG
static void put_be16(uint8_t *p, uint16_t value) {
    p[0] = value >> 8; p[1] = value;
}
#endif
static void send_status(void) {
    uint32_t now = to_ms_since_boot(get_absolute_time());
    if ((uint32_t)(now - last_status_ms) < 1000) return;
    // Keep the CYW43 ioctl in the main loop, outside the TCP receive callback.
    // The driver takes its own recursive lock; avoid nesting it in our lwIP section.
#if SAMPLE_RSSI
    if ((uint32_t)(now - last_rssi_ms) >= 10000) {
        int32_t sample;
        if (cyw43_wifi_get_rssi(&cyw43_state, &sample) == 0) rssi_dbm = sample;
        last_rssi_ms = now;
    }
#endif
    cyw43_arch_lwip_begin();
    if (connected && connection && tcp_sndbuf(connection) >= STATUS_BYTES) {
        uint8_t message[STATUS_BYTES] = {'P','W','S',
#if PLAYER_CYW43_DIAG
            '4'
#else
            '3'
#endif
        };
        memcpy(message + 4, sta_mac, 6);
        message[10] = (wifi_pm_disabled ? 1 : 0) |
                      (active_mode == MODE_RAW_RX || active_mode == MODE_JPEG_RX ||
                       active_mode == MODE_JPEG_DECODE ? 2 : 0);
        message[11] = wifi_pm_readback;
        put_be32(message + 12, frames_received);
        put_be32(message + 16, frames_displayed);
        put_be32(message + 20, frames_dropped);
        put_be32(message + 24, last_spi_us);
        put_be32(message + 28, max_spi_us);
        put_be32(message + 32, (uint32_t)rssi_dbm);
        const struct stats_mem *pool = lwip_stats.memp[MEMP_PBUF_POOL];
        put_be32(message + 36, pool ? pool->max : 0);
        put_be32(message + 40, pool ? pool->err : 0);
        put_be32(message + 44, lwip_stats.tcp.drop);
        put_be32(message + 48, lwip_stats.tcp.memerr);
        put_be32(message + 52, max_receive_callback_us);
        put_be32(message + 56, max_receive_gap_ms);
        put_be32(message + 60, active_mode);
        put_be32(message + 64, frames_decoded);
        put_be32(message + 68, decode_failed);
        put_be32(message + 72, last_decode_us);
        put_be32(message + 76, max_decode_us);
#if PLAYER_CYW43_DIAG
        cyw43_diag_snapshot_t diag;
        cyw43_diag_snapshot(&diag);
        const uint32_t counts[CYW43_DIAG_COUNTERS] = {
            diag.waits_total, diag.waits_ack, diag.waits_status, diag.waits_other,
            diag.waits_timeout, diag.wait_max_us, diag.discard_all,
            diag.discard_tcp_data, diag.tx_buffer_changed, diag.normal_data_delivered,
            diag.lwip_seen, diag.pbuf_fail, diag.netif_input_fail, diag.tcp_gap,
            diag.sdpcm_invalid, diag.spi_read_error, diag.spi_status_invalid,
            diag.first_drop_ms, diag.first_drop_seq, diag.event_serial
        };
        for (unsigned i = 0; i < CYW43_DIAG_COUNTERS; ++i)
            put_be32(message + 80 + i * 4, counts[i]);
        for (unsigned i = 0; i < CYW43_DIAG_WIRE_EVENTS; ++i) {
            const cyw43_diag_event *e = &diag.events[i];
            uint8_t *p = message + 160 + 20 * i;
            put_be32(p, e->serial); put_be32(p + 4, e->ms);
            put_be32(p + 8, e->seq); put_be16(p + 12, e->src_port);
            put_be16(p + 14, e->dst_port); put_be16(p + 16, e->payload_len);
            p[18] = e->type; p[19] = e->tx_class;
        }
#endif
        if (tcp_write(connection, message, sizeof message, TCP_WRITE_FLAG_COPY) == ERR_OK) {
            tcp_output(connection);
            last_status_ms = now;
        }
    }
    cyw43_arch_lwip_end();
}

static err_t close_connection(void) {
    if (connection) {
        struct tcp_pcb *pcb = connection;
        connection = NULL;
        connected = false;
        tcp_arg(pcb, NULL);
        tcp_recv(pcb, NULL);
        tcp_poll(pcb, NULL, 0);
        tcp_err(pcb, NULL);
        if (tcp_close(pcb) != ERR_OK) {
            tcp_abort(pcb);
            return ERR_ABRT;
        }
    }
    return ERR_OK;
}
static void on_error(void *arg, err_t error) {
    (void)arg; (void)error;
    connection = NULL; // lwIP has already freed the PCB
    connected = false;
}
static err_t on_poll(void *arg, struct tcp_pcb *pcb) {
    (void)arg; (void)pcb;
    if ((uint32_t)(to_ms_since_boot(get_absolute_time()) - last_receive_ms) >= 5000)
        return close_connection();
    return ERR_OK;
}
static err_t on_connected(void *arg, struct tcp_pcb *pcb, err_t error) {
    (void)arg; (void)pcb;
    if (error != ERR_OK) { close_connection(); return error; }
    connected = true;
    last_receive_ms = to_ms_since_boot(get_absolute_time());
    last_status_ms = 0;
    return ERR_OK;
}

// Consume an arbitrary TCP chunk; a frame may span any number of pbufs.
static bool consume(const uint8_t *src, size_t length) {
    while (length) {
        size_t target = reading_header ? HEADER_BYTES : payload_bytes;
        size_t count = target - received;
        if (count > length) count = length;
        if (reading_header) memcpy(header + received, src, count);
        else if (!discard_frame) {
            uint8_t *destination = active_mode <= MODE_RAW_DISPLAY ? frames[fill_slot] : jpeg_slots[fill_slot];
            memcpy(destination + received, src, count);
        }
        received += count;
        src += count;
        length -= count;
        if (received != target) continue;
        received = 0;
        if (reading_header) {
            uint32_t mode = be32(header + 16);
            size_t length = be32(header + 12);
            if (memcmp(header, "PWF2", 4) || be16(header + 8) != LCD_W ||
                be16(header + 10) != LCD_H || mode > MODE_JPEG_DISPLAY ||
                (connection_mode >= 0 && mode != (uint32_t)connection_mode) ||
                (mode <= MODE_RAW_DISPLAY ? length != FRAME_BYTES :
                 length < 4 || length > JPEG_MAX_BYTES)) return false;
            if (connection_mode < 0 && mode != active_mode) {
                last_decode_us = max_decode_us = 0;
                last_spi_us = max_spi_us = 0;
                max_receive_callback_us = max_receive_gap_ms = 0;
            }
            connection_mode = (int)mode;
            active_mode = mode;
            payload_bytes = length;
            fill_slot = !ready[0] ? 0 : (!ready[1] ? 1 : 0);
            discard_frame = ready[0] && ready[1];
            incoming_sequence = be32(header + 4);
            reading_header = false;
        } else {
            if (!discard_frame) {
                slot_sequence[fill_slot] = incoming_sequence;
                slot_length[fill_slot] = payload_bytes;
                ready[fill_slot] = true;
                ++frames_received;
            } else ++frames_dropped;
            reading_header = true;
        }
    }
    return true;
}
static err_t on_receive(void *arg, struct tcp_pcb *pcb, struct pbuf *p, err_t error) {
    (void)arg;
    if (!p || error != ERR_OK) {
        if (p) pbuf_free(p);
        return close_connection();
    }
    uint64_t began = time_us_64();
    uint32_t now = (uint32_t)(began / 1000);
    uint32_t gap = now - last_receive_ms;
    if (gap > max_receive_gap_ms) max_receive_gap_ms = gap;
    last_receive_ms = now;
    bool valid = true;
    for (struct pbuf *q = p; q && valid; q = q->next)
        valid = consume(q->payload, q->len);
    if (valid) tcp_recved(pcb, p->tot_len);
    pbuf_free(p);
    uint32_t elapsed = (uint32_t)(time_us_64() - began);
    if (elapsed > max_receive_callback_us) max_receive_callback_us = elapsed;
    if (!valid) return close_connection();
    return ERR_OK;
}
static bool open_connection(void) {
    ip_addr_t remote;
    if (!ipaddr_aton(SERVER_IP, &remote)) return false;
    cyw43_arch_lwip_begin();
    connection = tcp_new_ip_type(IP_GET_TYPE(&remote));
    if (!connection) { cyw43_arch_lwip_end(); return false; }
    received = 0;
    reading_header = true;
    connection_mode = -1;
    ready[0] = ready[1] = false;
    connected = false;
    tcp_arg(connection, NULL);
    tcp_recv(connection, on_receive);
    tcp_poll(connection, on_poll, 10); // 10 * 500 ms
    tcp_err(connection, on_error);
    err_t result = tcp_connect(connection, &remote, SERVER_PORT, on_connected);
    if (result != ERR_OK) close_connection();
    cyw43_arch_lwip_end();
    return result == ERR_OK;
}

int main(void) {
    if (cyw43_arch_init()) for (;;) sleep_ms(1000);
    cyw43_arch_enable_sta_mode();
    // Streaming is latency-sensitive; PM2 is the SDK default even in performance mode.
    cyw43_arch_lwip_begin();
    wifi_pm_disabled = cyw43_wifi_pm(&cyw43_state, CYW43_NONE_PM) == 0;
    cyw43_arch_lwip_end();
    cyw43_wifi_get_mac(&cyw43_state, CYW43_ITF_STA, sta_mac);
    lcd_init();
    show_test_pattern();
    for (;;) {
        // A TCP reset does not require joining the Wi-Fi network again.
        if (cyw43_tcpip_link_status(&cyw43_state, CYW43_ITF_STA) != CYW43_LINK_UP) {
            if (cyw43_arch_wifi_connect_timeout_ms(WIFI_SSID, WIFI_PASSWORD,
                    CYW43_AUTH_WPA2_AES_PSK, 15000)) { sleep_ms(3000); continue; }
        }
        // Read the firmware's actual PM mode once, after the first Wi-Fi join.
        if (!wifi_pm_readback_done) {
            uint8_t value[4] = {0};
            int rc = cyw43_ioctl(&cyw43_state, CYW43_IOCTL_GET_PM,
                                 sizeof value, value, CYW43_ITF_STA);
            if (rc == 0) {
                uint32_t mode = (uint32_t)value[0] | (uint32_t)value[1] << 8 |
                                (uint32_t)value[2] << 16 | (uint32_t)value[3] << 24;
                wifi_pm_readback = mode <= 2 ? (uint8_t)(0x80 | mode) : 0xc0;
            } else {
                uint32_t error = rc < 0 ? (uint32_t)(-(int64_t)rc) : (uint32_t)rc;
                wifi_pm_readback = (uint8_t)(0x40 | (error > 63 ? 63 : error));
            }
            wifi_pm_readback_done = true;
        }
        if (!open_connection()) { sleep_ms(1000); continue; }
        while (connection) {
            int slot = ready[0] ? 0 : (ready[1] ? 1 : -1);
            if (ready[0] && ready[1] && (int32_t)(slot_sequence[1] - slot_sequence[0]) < 0)
                slot = 1;
            if (slot >= 0) {
                if (active_mode == MODE_JPEG_DECODE || active_mode == MODE_JPEG_DISPLAY) {
                    uint64_t began = time_us_64();
                    int result = jpeg_decode_frame(jpeg_slots[slot], slot_length[slot], jpeg_pixels);
                    last_decode_us = (uint32_t)(time_us_64() - began);
                    if (last_decode_us > max_decode_us) max_decode_us = last_decode_us;
                    if (result == 0) {
                        ++frames_decoded;
                        if (active_mode == MODE_JPEG_DISPLAY) {
                            began = time_us_64();
                            lcd_show(jpeg_pixels);
                            last_spi_us = (uint32_t)(time_us_64() - began);
                            if (last_spi_us > max_spi_us) max_spi_us = last_spi_us;
                            ++frames_displayed;
                        }
                    } else ++decode_failed;
                }
                if (active_mode == MODE_RAW_DISPLAY) {
                    uint64_t began = time_us_64();
                    lcd_show(frames[slot]);
                    last_spi_us = (uint32_t)(time_us_64() - began);
                    if (last_spi_us > max_spi_us) max_spi_us = last_spi_us;
                    ++frames_displayed;
                }
                cyw43_arch_lwip_begin();
                ready[slot] = false;
                cyw43_arch_lwip_end();
            }
            send_status();
            sleep_ms(1);
        }
        sleep_ms(1000);
    }
}
