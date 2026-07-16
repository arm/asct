/*
 * Copyright (C) Arm Ltd. 2025. All rights reserved.
 *
 * Construct random circular pointer-chains in memory. 
 */

#ifndef __included_chain_h
#define __included_chain_h

#include <stddef.h>
#include <stdint.h>

/*
 * Chain characteristics. This is used to specify general
 * properties of a pointer chain, as input to the random
 * construction.
 *
 * Apart from n_links, zeroes are suitable defaults for
 * the rest.
 */
typedef struct {
    /* The number of links in the chain. Generally equals
       the number of cache lines touched by the chain. */
    size_t n_links;

    /* Short-range dispersion factor.
       Links are randomly placed within a group of N contiguous lines.
       N.b. a default of 0 in this field indicates 1. */
    uint16_t dispersion;

    /* Long-range dispersion factor.
       The base footprint is treated as N replicas, and links are
       randomly allocated between replicas.
       This may help defeat page-prefetchers, while not leading to
       increased cache pressure. */
    uint16_t spread;

    /* Offset of pointer field within line.
       -1 indicates random offset. */
    int16_t link_offset_in_line;

    /* Alignment of link within line, for when pointer_offset=-1.
       Defaults to naturally aligned, i.e. 4 or 8 for 32-bit and 64-bit
       pointers respectively. */
    uint16_t alignment;

    /* Fixed offset of each link pointer value. The actual address
       of the next link is *[previous pointer] + value_offset.
       This is normally zero but might be made non-zero for
       experimenting with prefetch-defeat strategies. */
    int32_t value_offset;

    /* Chain is sequential, rather than random */
    unsigned int is_stream:1;

    /* Chain is random, but within sub-blocks, to avoid TLB pressure.
       Sub-block-size currently hardcoded internally. */
    unsigned int is_blocked:1;
} chain_t;


/*
 * Initialize a chain descriptor.
 */
void chain_init(chain_t *);


/*
 * The chain pointer (possibly offset) - i.e. the value
 * maintained as we step through the chain.
 */
typedef void const *chainptr_t;


/*
 * Get the length (number of links) of a pointer chain, with an upper limit.
 * Return 0 if the limit is exceeded.
 */
unsigned int chain_length(void const *, int offset, unsigned int limit);


/*
 * Get the next link in a chain, applying any offsets etc.
 */
chainptr_t chain_next(chainptr_t, chain_t const *);


/*
 * Get the memory size needed for a chain, taking into account
 * the requested number of links, dispersion factors etc.
 */
size_t chain_size(chain_t const *);


/*
 * Construct a chain in a provided area of memory.
 */
chainptr_t chain_construct(void *, size_t, chain_t const *, int);


#endif /* included */
