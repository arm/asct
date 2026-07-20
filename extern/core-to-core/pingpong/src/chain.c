/*
 * Copyright (C) Arm Ltd. 2025. All rights reserved.
 */

#include <assert.h>

#include "chain.h"

#include "cacheline.h"
#include "workset.h"
#include "round.h"
#include "shuffle.h"
#include "crc32.h"

#include <stdio.h>
#include <string.h>
#include <stdlib.h>


static chainptr_t const *chain_pointer_addr(chainptr_t p, chain_t const *c)
{
    return (chainptr_t const *)((unsigned char *)p + c->value_offset);
}


chainptr_t chain_next(chainptr_t chainp, chain_t const *c)
{
    return *chain_pointer_addr(chainp, c);
}


static unsigned int chain_dispersion(chain_t const *c)
{
    return (c->dispersion >= 1) ? c->dispersion : 1;
}


static unsigned int chain_spread(chain_t const *c)
{
    return (c->spread >= 1) ? c->spread : 1;
}


/*
Test the length of a chain of data.  The chain must be completely circular
i.e. we must get back to the beginning.  Given bad data, this function might crash.
The caller should pass in an upper bound greater than the expected length,
to avoid an infinite loop.
If the upper bound is exceeded, we return 0 (not a valid chain length).
*/
unsigned int chain_length(void const *chainp, int offset, unsigned int limit)
{
    unsigned int n = 0;
    void const *p = chainp;
    do {
        ++n;
        if (n == limit) {
            /* Upper limit reached with loop not closed - return 0 to indicate error. */
            return 0;
        }
        void const *const *load_addr = (void const * const*)((unsigned char *)p + offset);
        p = *((void const **)load_addr);
    } while (p != chainp);
    return n;
}


/*
 * Hash an integer, to achieve a pseudorandom distribution.
 *
 * Since we're generally reducing the hash by a small power of 2, we particularly
 * want the LSBs of the output to be pseudorandom, and not correlated with any
 * bits of the input.
 *
 * Plain crc32w(0, n) is not good for this, but we can improve by losing the LSBs.
 */
static uint32_t hash_uint32(uint32_t n)
{
    uint32_t r = crc32w(0, n);
    return (r ^ (r >> 8));
}


/*
 * Given an index i into our overall working set, return the placement of the
 * data chain pointer within the cache line or line group (chunk).
 * This needs to be a deterministic function of i, so if we want to randomize
 * the placement we've got to use a pseudo-random function of i.
 * We mustn't overspill the end of the line group, as we risk bumping into
 * the next line group, or into unrelated data.
 * Exceptionally, the first item is always at offset 0, so that the client
 * knows where to start.
 */
static unsigned int line_data_placement(chain_t const *c, unsigned int i)
{
    unsigned int ix;
    unsigned int const LINE = cache_line_length();
    unsigned int const dispersion = chain_dispersion(c);
    unsigned int const chunk_bytes = LINE * dispersion;
    if (c->link_offset_in_line < 0) {
        /* Random link placement within line */
        unsigned int alignment = c->alignment ? c->alignment : sizeof(void *);
        /* Pointers will be aligned on 'alignment', e.g. 8 bytes. So if the chunk size is a
           64-byte line, and alignment is 8, valid offsets will be 0,8,16,24,32,40,48,52. */
        /* TBD: if data_alignment < sizeof(void *), and data_dispersion > 1,
           currently we might split the pointer across two cache lines.
           We could try to avoid this. */
        unsigned int range = (chunk_bytes - sizeof(void *)) / alignment;
        /* Pointer can be placed anywhere on [0,range]*alignment */
        ix = (hash_uint32(i) % (range+1)) * alignment;
        ix = (i == 0) ? 0 : ix;
    } else {
        /* Fixed link placement within line */
        ix = c->link_offset_in_line;
        if (dispersion > 1 && i > 0) {
            ix += (hash_uint32(i) % dispersion) * LINE;
        }
    }
    assert((ix + sizeof(void *)) <= chunk_bytes);
    return ix;
}


/*
 * This handles spread>1. For spread==1 it will always return zero.
 * Given an index i into our overall working set, return which replica it's in.
 */
static unsigned int line_replica(chain_t const *c, unsigned int i)
{
    int const s = chain_spread(c);
    unsigned int r = (s == 1 || i == 0) ? 0 : (hash_uint32(i ^ 0x1234) % s);
    return r;
}


/*
 * Traverse a circular chain, and update working set statistics.
 * Caller is responsible for initializing and freeing the statistics.
 */
static void chain_working_set(chainptr_t p, chain_t const *c, WorkingSetCharacteristics *ws)
{
    chainptr_t const start_p = p;
    assert(p != 0);
    do {
        chainptr_t const *load_addr = chain_pointer_addr(p, c);
        ws_update(ws, load_addr, sizeof(void *));
        p = *load_addr;
        if (!p) {
            fprintf(stderr, "Unexpected chain termination: %p...%p -> NULL\n", start_p, (void *)load_addr);
            ws_fprint(stderr, ws);
            exit(EXIT_FAILURE);
        }
        if (ws->n_access > c->n_links) {
            fprintf(stderr, "working set corrupt: %lu > %lu\n",
                    (unsigned long)ws->n_access, (unsigned long)c->n_links);
            assert(0);
        }
    } while (p != start_p);
}


size_t chain_size(chain_t const *c)
{
    return c->n_links * chain_dispersion(c) * chain_spread(c) * cache_line_length();
}


#define DEBUG_FD stderr

chainptr_t chain_construct(void *mem_base, size_t mem_size, chain_t const *c, int debug)
{
    int32_t const data_pointer_offset = c->value_offset;
    unsigned int const n_lines = c->n_links;
    unsigned int const LINE = cache_line_length();
    unsigned int const dispersion = chain_dispersion(c);
    unsigned int const chunk_bytes = LINE * dispersion;
    size_t const replica_size = n_lines * chunk_bytes;
    size_t const size_rounded_to_lines = n_lines * chunk_bytes * chain_spread(c);
    unsigned int i;
    unsigned int const expected_chain_length = n_lines;
    /* Any placement of links within lines relies on the area being
       at least line-aligned. */
    if (mem_size < chain_size(c)) {
        fprintf(stderr, "Memory size 0x%zx too small, need 0x%zx (%u %u-byte lines",
            mem_size, chain_size(c), n_lines, LINE);
        if (dispersion > 1) {
            fprintf(stderr, ", dispersion=%u", dispersion);
        }
        if (chain_spread(c) > 1) {
            fprintf(stderr, ", spread=%u", chain_spread(c));
        }
        fprintf(stderr, ")\n");
        return NULL;
    }
    assert(is_rounded(mem_base, LINE));
    void *const adjusted_data = (void *)((unsigned char *)mem_base - data_pointer_offset);
    if (debug) {
        fprintf(DEBUG_FD, "Constructing chain, %u lines of %u bytes\n", n_lines, LINE);
        if (dispersion > 1) {
            fprintf(DEBUG_FD, "  Dispersion: %u\n", dispersion);
        }
        if (chain_spread(c) > 1) {
            fprintf(DEBUG_FD, "  Spread: %u\n", chain_spread(c));
        }
        fprintf(stderr, "  Replica size: %#lx\n", replica_size);
        if (data_pointer_offset) {
            fprintf(DEBUG_FD, "  Data pointer offset: %d\n", data_pointer_offset);
        }
    }
    if (!c->is_stream) {
        unsigned int const SUBBLOCK_LINES = 2048;  /* 32 4K pages, each of 64 64-byte lines */
        unsigned int const block_lines = !c->is_blocked ? n_lines : SUBBLOCK_LINES;
        unsigned int off = 0;
        int n_lines_left = n_lines;
        while (n_lines_left > 0) {
            unsigned int *order;
            unsigned int const nl = ((unsigned int)n_lines_left > block_lines) ? block_lines : (unsigned int)n_lines_left;
            n_lines_left -= nl;
            /* Construct a random cycle for this sub-block. */
            if (debug >= 2) {
                fprintf(DEBUG_FD, "Constructing %u-line sub-block (out of %u)\n", nl, n_lines);
            }
            order = alloc_random_maximal_cycle(nl);
            if (debug >= 3) {
                unsigned int i;
                for (i = 0; i < nl; ++i) {
                    fprintf(DEBUG_FD, " %d", order[i]);
                }
                fprintf(DEBUG_FD, "\n");
            }
            /* Use the random cycle to build a chain of pointers in the data area. */
            /* Each link in the chain can, in principle, be allocated anywhere in the line,
               or if we're using dispersion, in the group of lines. We can also try to
               use unaligned and cross-line data placement. */
            for (i = 0; i < nl; ++i) {
                int nexti = order[i];
                /* Each sub-block will have one link that points to 0. This needs to point
                   to the next sub-block, or the first sub-block if this is the last one. */
                if (nexti != 0) {
                    nexti += off;    /* another line (not the first one) within this sub-block */
                } else if (n_lines_left > 0) {
                    nexti = off + block_lines;    /* first line in the next sub-block */
                } else {
                    nexti = 0;       /* back to the first line in the first sub-block */
                }
                void **link_addr = (void **)((unsigned char *)mem_base + (i+off)*chunk_bytes + line_replica(c, i)*replica_size + line_data_placement(c, i));
                void *link_val = ((unsigned char *)adjusted_data + nexti*chunk_bytes + line_replica(c, order[i])*replica_size + line_data_placement(c, order[i]));
                *link_addr = link_val;
            }
            off += nl;
            free(order);
        }
    } else {
        /* Construct a sequential cycle. Still a chain of pointers,
           but ascending in address order. */
        for (i = 0; i < n_lines; ++i) {
            *(void **)((unsigned char *)mem_base + i*chunk_bytes) = ((unsigned char *)adjusted_data + ((i+1)%n_lines)*chunk_bytes);
        }
    }
    if (debug >= 2) {
        fprintf(DEBUG_FD, "Data working set (adjusted_data=%p):\n", adjusted_data);
        unsigned int lines_to_show = n_lines;
        if (lines_to_show > 10) {
            lines_to_show = 10;
        }
        for (i = 0; i < lines_to_show; ++i) {
            unsigned int j;
            unsigned int ix = c->is_stream ? 0 : line_data_placement(c, i);
            void ** const start_p = (void **)((unsigned char *)adjusted_data + i*chunk_bytes + line_replica(c, i)*replica_size + ix);
            void ** p = start_p;
            fprintf(DEBUG_FD, "  from %2u: ", i);
            for (j = 0; j < 10; ++j) {
                if (data_pointer_offset == 0) {
                    fprintf(DEBUG_FD, "*%p -> ", (void *)p);
                } else {
                    fprintf(DEBUG_FD, "*(%p+%d) -> ", (void *)p, data_pointer_offset);
                }
                if (j > 0 && p == start_p) {
                    break;
                }
                p = (void **)*(void **)((unsigned char *)p + data_pointer_offset);
            }
            fprintf(DEBUG_FD, "...\n");
        }
    }
    if (debug >= 1) {
        /* Do a post-construction check on the data, to check it has the right parameters */
        WorkingSetCharacteristics ws;
        if (debug >= 1) {
            fprintf(DEBUG_FD, "Collecting data working set characteristics...\n");
        }
        ws_init(&ws);
        chain_working_set(adjusted_data, c, &ws);
        if (debug >= 1) {
            ws_fprint(DEBUG_FD, &ws);
            fprintf(stderr, "Size rounded to lines: 0x%zx\n", size_rounded_to_lines);
        }
        size_t rounded_range = round_size_up(ws_range(&ws), chunk_bytes);
        if (chain_spread(c) == 1) {
            assert(rounded_range == size_rounded_to_lines);
        } else {
            /* last link might not be in last replica, above test doesn't work exactly */
            assert(rounded_range <= size_rounded_to_lines);
        }
        /* Check that the pattern is suitably random. In a random shuffle we expect
           on average 1 contiguous pair. But we might see more with sub-blocking. */
        if (n_lines >= 20 && ws.n_contig_access > 0) {
            assert((ws.n_contig_access-1)*100 < n_lines+10);
        }
        ws_free(&ws);
    }
    if (1) {
        unsigned int cl = chain_length(adjusted_data, data_pointer_offset, expected_chain_length*3);
        if (cl != expected_chain_length) {
            fprintf(DEBUG_FD, "Data chain length %u, expected %u\n", cl, expected_chain_length);
            exit(EXIT_FAILURE);
        }
        if (debug >= 1) {
            fprintf(DEBUG_FD, "Data chain length verified as %lu (%lu-byte footprint in %u-byte lines)\n",
                (unsigned long)cl, ((unsigned long)cl * LINE), LINE);
        }
    }
    if (debug >= 1) {
        fprintf(DEBUG_FD, "Constructed data working set.\n");
    }
    /* Return the initial offsetted pointer that the client should use when
       iterating through the working set. Each load will add the fixed offset to
       the current pointer. The actual memory area is remembered in the
       memory descriptor structure and will be used on free. */
    return adjusted_data;
}


/*
 * Initialize a chain properties block.
 * Zero-initialization is equivalent, but chain_init is cleaner
 * in setting a few values to 1 where this is implied by a zero default.
 */
void chain_init(chain_t *c)
{
    memset(c, 0, sizeof(chain_t));
    c->dispersion = 1;
    c->spread = 1;
}

