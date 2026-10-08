#pragma once

// Bare-metal Pico W + lwIP raw TCP API; no RTOS or BSD socket layer.
#define NO_SYS 1
#define LWIP_SOCKET 0
#define LWIP_NETCONN 0
#define MEM_ALIGNMENT 4
#define MEM_SIZE 8192
#define MEMP_NUM_TCP_SEG 32
#define PBUF_POOL_SIZE 32
#define LWIP_ARP 1
#define LWIP_ETHERNET 1
#define LWIP_ICMP 1
#define LWIP_IPV4 1
#define LWIP_TCP 1
#define LWIP_UDP 1
#define LWIP_DHCP 0
#define TCP_MSS 1460
#define TCP_WND (16 * TCP_MSS)
#define TCP_SND_BUF (8 * TCP_MSS)
#define TCP_SND_QUEUELEN 32
#define LWIP_NETIF_STATUS_CALLBACK 1
#define LWIP_NETIF_LINK_CALLBACK 1
#define LWIP_NETIF_TX_SINGLE_PBUF 1
#define DHCP_DOES_ARP_CHECK 0
#define LWIP_DHCP_DOES_ACD_CHECK 0
