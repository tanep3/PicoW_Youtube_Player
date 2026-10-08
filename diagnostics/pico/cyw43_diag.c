#include "cyw43_diag.h"
#include <string.h>

_Static_assert(sizeof(cyw43_diag_event) == 20, "PWS4 event layout changed");
_Static_assert(sizeof(cyw43_diag_snapshot_t) == 240, "PWS4 snapshot layout changed");

static cyw43_diag_snapshot_t counters;
static cyw43_diag_event ring[CYW43_DIAG_RING_SLOTS];
static uint16_t tracked_dst_port;
static uint32_t expected_seq;
static bool tracking_seq;

static uint16_t big16(const uint8_t *p) { return (uint16_t)((uint16_t)p[0] << 8 | p[1]); }
static uint32_t big32(const uint8_t *p) {
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
}

bool cyw43_diag_parse_tcp(const uint8_t *frame, size_t len, cyw43_diag_tcp *out) {
    if (!frame || !out || len < 14 + 20 + 20 || big16(frame + 12) != 0x0800) return false;
    const uint8_t *ip = frame + 14;
    unsigned ihl = (ip[0] & 15u) * 4u;
    if ((ip[0] >> 4) != 4 || ihl < 20 || len < 14u + ihl + 20u || ip[9] != 6) return false;
    unsigned ip_total = big16(ip + 2);
    if (ip_total < ihl + 20u || ip_total > len - 14u) return false;
    if ((big16(ip + 6) & 0x1fffu) != 0) return false; // non-first IPv4 fragment
    const uint8_t *tcp = ip + ihl;
    unsigned tcp_len = (tcp[12] >> 4) * 4u;
    if (tcp_len < 20 || ihl + tcp_len > ip_total) return false;
    out->src_port = big16(tcp);
    out->dst_port = big16(tcp + 2);
    out->seq = big32(tcp + 4);
    out->ack = big32(tcp + 8);
    out->flags = tcp[13];
    out->payload_len = (uint16_t)(ip_total - ihl - tcp_len);
    out->payload = tcp + tcp_len;
    return true;
}

uint8_t cyw43_diag_classify_tx(const uint8_t *frame, size_t len) {
    cyw43_diag_tcp tcp;
    if (!cyw43_diag_parse_tcp(frame, len, &tcp)) return CYW43_DIAG_TX_OTHER;
    if (tcp.payload_len == 0 && (tcp.flags & 0x10) && !(tcp.flags & 0x07))
        return CYW43_DIAG_TX_ACK;
    if (tcp.payload_len >= 4 &&
        (!memcmp(tcp.payload, "PWS3", 4) || !memcmp(tcp.payload, "PWS4", 4)))
        return CYW43_DIAG_TX_STATUS;
    return CYW43_DIAG_TX_OTHER;
}

uint32_t cyw43_diag_fingerprint(const uint8_t *frame, size_t len) {
    // Only the first 64 Ethernet bytes, never the mutable SDPCM/BDC header.
    size_t n = len < 64 ? len : 64;
    uint32_t hash = 2166136261u;
    for (size_t i = 0; i < n; ++i) hash = (hash ^ frame[i]) * 16777619u;
    return hash;
}

static void record(uint8_t type, uint8_t tx_class, uint32_t ms, const cyw43_diag_tcp *tcp) {
    uint32_t serial = ++counters.event_serial;
    cyw43_diag_event *event = &ring[(serial - 1u) % CYW43_DIAG_RING_SLOTS];
    *event = (cyw43_diag_event){.serial = serial, .ms = ms, .type = type,
                                 .tx_class = tx_class};
    if (tcp) {
        event->seq = tcp->seq;
        event->src_port = tcp->src_port;
        event->dst_port = tcp->dst_port;
        event->payload_len = tcp->payload_len;
    }
}

void cyw43_diag_wait_enter(uint8_t kind) {
    ++counters.waits_total;
    if (kind == CYW43_DIAG_TX_ACK) ++counters.waits_ack;
    else if (kind == CYW43_DIAG_TX_STATUS) ++counters.waits_status;
    else ++counters.waits_other;
}
void cyw43_diag_wait_finish(uint32_t us, bool timed_out) {
    if (us > counters.wait_max_us) counters.wait_max_us = us;
    if (timed_out) ++counters.waits_timeout;
}
void cyw43_diag_credit_drop(const uint8_t *frame, size_t len, uint8_t tx_class, uint32_t now_ms) {
    ++counters.discard_all;
    cyw43_diag_tcp tcp;
    if (cyw43_diag_parse_tcp(frame, len, &tcp) && tcp.src_port == 16151 && tcp.payload_len) {
        ++counters.discard_tcp_data;
        if (!counters.first_drop_ms) {
            counters.first_drop_ms = now_ms;
            counters.first_drop_seq = tcp.seq;
        }
        record(CYW43_DIAG_CREDIT_DROP, tx_class, now_ms, &tcp);
    } else {
        record(CYW43_DIAG_CREDIT_DROP, tx_class, now_ms, NULL);
    }
}
void cyw43_diag_tx_clobber(const cyw43_diag_tcp *tx, uint8_t tx_class, uint32_t now_ms) {
    ++counters.tx_buffer_changed;
    record(CYW43_DIAG_TX_CLOBBER, tx_class, now_ms, tx);
}
void cyw43_diag_normal_rx(const uint8_t *frame, size_t len, uint32_t now_ms) {
    ++counters.normal_data_delivered;
    cyw43_diag_tcp tcp;
    if (!cyw43_diag_parse_tcp(frame, len, &tcp) || tcp.src_port != 16151 || !tcp.payload_len) return;
    if (!tracking_seq || tcp.dst_port != tracked_dst_port) {
        tracked_dst_port = tcp.dst_port;
        expected_seq = tcp.seq + tcp.payload_len;
        tracking_seq = true;
    } else if ((int32_t)(tcp.seq - expected_seq) > 0) {
        ++counters.tcp_gap;
        record(CYW43_DIAG_TCP_GAP, 0, now_ms, &tcp);
        expected_seq = tcp.seq + tcp.payload_len;
    } else if ((int32_t)((tcp.seq + tcp.payload_len) - expected_seq) > 0) {
        expected_seq = tcp.seq + tcp.payload_len;
    }
}
void cyw43_diag_lwip_rx(void) { ++counters.lwip_seen; }
void cyw43_diag_pbuf_fail(const uint8_t *frame, size_t len, uint32_t now_ms) {
    ++counters.pbuf_fail;
    cyw43_diag_tcp tcp;
    record(CYW43_DIAG_PBUF_FAIL, 0, now_ms,
           cyw43_diag_parse_tcp(frame, len, &tcp) ? &tcp : NULL);
}
void cyw43_diag_netif_input_fail(void) { ++counters.netif_input_fail; }
void cyw43_diag_sdpcm_invalid(void) { ++counters.sdpcm_invalid; }
void cyw43_diag_spi_read_error(void) { ++counters.spi_read_error; }
void cyw43_diag_spi_status_invalid(void) { ++counters.spi_status_invalid; }
void cyw43_diag_snapshot(cyw43_diag_snapshot_t *out) {
    memcpy(out, &counters, offsetof(cyw43_diag_snapshot_t, events));
    for (unsigned i = 0; i < CYW43_DIAG_WIRE_EVENTS; ++i) {
        uint32_t serial = counters.event_serial > CYW43_DIAG_WIRE_EVENTS
            ? counters.event_serial - CYW43_DIAG_WIRE_EVENTS + 1u + i : i + 1u;
        out->events[i] = serial <= counters.event_serial
            ? ring[(serial - 1u) % CYW43_DIAG_RING_SLOTS] : (cyw43_diag_event){0};
    }
}
