#ifndef PLAYER_JPEG_DECODE_H
#define PLAYER_JPEG_DECODE_H
#include <stddef.h>
#include <stdint.h>
#define JPEG_MAX_BYTES 8192
#define JPEG_WORK_BYTES 8192
// 0=success, -1=bad length/termination, -2=wrong dimensions,
// -3=decoder error or invalid tile. Destination is 160x80 RGB565 big-endian.
int jpeg_decode_frame(const uint8_t *jpeg, size_t length, uint8_t *rgb565);
#endif
