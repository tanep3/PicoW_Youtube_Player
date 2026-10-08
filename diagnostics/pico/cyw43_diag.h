#ifndef PICOW_CYW43_DIAG_H
#define PICOW_CYW43_DIAG_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define CYW43_DIAG_RING_SLOTS 16u
#define CYW43_DIAG_WIRE_EVENTS 8u
#define CYW43_DIAG_COUNTERS 20u

enum { CYW43_DIAG_TX_OTHER = 0, CYW43_DIAG_TX_ACK = 1,
       CYW43_DIAG_TX_STATUS = 2, CYW43_DIAG_TX_CONTROL = 3 };
enum { CYW43_DIAG_CREDIT_DROP = 1, CYW43_DIAG_TCP_GAP = 2,
       CYW43_DIAG_TX_CLOBBER = 3, CYW43_DIAG_PBUF_FAIL = 4 };

typedef struct {
    uint16_t src_port, dst_port, payload_len;
    uint8_t flags;
    uint32_t seq, ack;
    const uint8_t *payload;
} cyw43_diag_tcp;

typedef struct {
    uint32_t serial, ms, seq;
    uint16_t src_port, dst_port, payload_len;
    uint8_t type, tx_class;
} cyw43_diag_event;

typedef struct {
    // Fixed wire order; all values are cumulative or maxima since boot unless stated.
    uint32_t waits_total, waits_ack, waits_status, waits_other;
    uint32_t waits_timeout, wait_max_us, discard_all, discard_tcp_data;
    uint32_t tx_buffer_changed, normal_data_delivered, lwip_seen;
    uint32_t pbuf_fail, netif_input_fail, tcp_gap;
    uint32_t sdpcm_invalid, spi_read_error, spi_status_invalid;
    uint32_t first_drop_ms, first_drop_seq, event_serial;
    cyw43_diag_event events[CYW43_DIAG_WIRE_EVENTS];
} cyw43_diag_snapshot_t;

// Strict bounds: Ethernet II + IPv4 (no non-first fragments) + TCP only.
bool cyw43_diag_parse_tcp(const uint8_t *frame, size_t len, cyw43_diag_tcp *result);
uint8_t cyw43_diag_classify_tx(const uint8_t *frame, size_t len);
uint32_t cyw43_diag_fingerprint(const uint8_t *frame, size_t len);
void cyw43_diag_wait_enter(uint8_t tx_class);
void cyw43_diag_wait_finish(uint32_t us, bool timed_out);
void cyw43_diag_credit_drop(const uint8_t *frame, size_t len, uint8_t tx_class, uint32_t now_ms);
void cyw43_diag_tx_clobber(const cyw43_diag_tcp *tx, uint8_t tx_class, uint32_t now_ms);
void cyw43_diag_normal_rx(const uint8_t *frame, size_t len, uint32_t now_ms);
void cyw43_diag_lwip_rx(void);
// Bounds a frame pointer against the driver's 2048-byte SPI receive buffer.
size_t cyw43_diag_bound_eth(void *ll, const uint8_t *frame, size_t reported);
void cyw43_diag_pbuf_fail(const uint8_t *frame, size_t len, uint32_t now_ms);
void cyw43_diag_netif_input_fail(void);
void cyw43_diag_sdpcm_invalid(void);
void cyw43_diag_spi_read_error(void);
void cyw43_diag_spi_status_invalid(void);
// Caller holds the CYW43/lwIP lock; no IO, allocation, printf or ioctl.
void cyw43_diag_snapshot(cyw43_diag_snapshot_t *out);
#endif
