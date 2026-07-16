/*
 * Copyright (C) Arm Ltd. 2025. All rights reserved.
 *
 * CRC32 implementation
 *
 * Uses ACLE CRC32 intrinsics if available, C implementations if not.
 *
 * Also provides general functions e.g. buffer checksum.
 */


#ifndef __included_crc32_h
#define __included_crc32_h

#include <stdint.h>
#include <stddef.h>

/*
 * C implementations of CRC32, from crc32.c.
 * Naming and parameters follows the ACLE intrinsics.
 */

uint32_t c_crc32b(uint32_t, uint8_t);

uint32_t c_crc32h(uint32_t, uint16_t);

uint32_t c_crc32w(uint32_t, uint32_t);

uint32_t c_crc32d(uint32_t, uint64_t);


#ifdef __ARM_FEATURE_CRC32
#include <arm_acle.h>

#define crc32b(c, x) __crc32b(c, x)
#define crc32h(c, x) __crc32h(c, x)
#define crc32w(c, x) __crc32w(c, x)
#define crc32d(c, x) __crc32d(c, x)

#else

#define crc32b(c, x) c_crc32b(c, x)
#define crc32h(c, x) c_crc32h(c, x)
#define crc32w(c, x) c_crc32w(c, x)
#define crc32d(c, x) c_crc32d(c, x)

#endif


/*
 * Calculate the CRC32 checksum of an arbitrary data buffer.
 * The starting CRC is usually zero.
 * Both the starting and final CRC32 are (internally) inverted,
 * so as to match zlib.crc32, binascii.crc32 etc.
 */
uint32_t crc32_buffer(uint32_t, void const *, size_t);


#define CRC32_INIT 0   /* Conventional starting value for block CRC */


#endif /* included */
