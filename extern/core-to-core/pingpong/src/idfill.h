/*
 * Copyright (C) Arm Ltd. 2025. All rights reserved.
 *
 * Memory identity fill
 *
 * Fills a block with self-identifying cache lines,
 * including virtual address, and physical address where available.
 */

#ifndef __included_idfill_h
#define __included_idfill_h

#include <stdint.h>
#include <stddef.h>

/*
 * Fill a block of memory.
 * Base address and size must be cache-line aligned.
 * Optionally, include the physical address - requires root privilege.
 *
 * Returns IDFILL_OK, or IDFILL_NO_PA if PA requested and n/a.
 */
int idfill_fill(void *, size_t, char const *, int);
#define IDFILL_OK        0
#define IDFILL_NO_PA     1   /* PA not available, lack of privilege */


typedef struct {
    uint64_t pa0;        /* First copy of physical address (or IPA) */
    uint64_t va0;        /* First copy of virtual address */
    uint32_t checksum;   /* CRC32 checksum of this structure */
    char sig[28];        /* "FILL" plus user-defined signature */
    uint64_t pa1;        /* =pa0 */
    uint64_t va1;        /* =va0 */
} idfill_t;


/*
 * Check if an idfilled block has the correct virtual address
 * and a valid checksum.
 */
int idfill_validate(idfill_t const *);
#define IDFILL_MISMATCH  2   /* address fields don't match */
#define IDFILL_CRC       3   /* failed checksum */
#define IDFILL_MOVED     4   /* contents valid but don't match address */


#endif /* included */
