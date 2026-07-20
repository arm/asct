/*
 * Copyright (C) Arm Ltd. 2025. All rights reserved.
 */

#include "workset.h"

#ifndef ASCT
#include "loadgenp.h"
#endif /* ASCT */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>


#define FOOTPRINT_ALREADY_TOUCHED 0
#define FOOTPRINT_FIRST_TOUCH 1
#define FOOTPRINT_SECOND_TOUCH 2
static int footprint_update(Footprint *fp, void const *p, unsigned int GRANULE)
{
    void const *granule_address = (void const *)((unsigned long)p & ~(unsigned long)(GRANULE-1));
    unsigned long granule_index = (unsigned long)granule_address / GRANULE;
    unsigned int const bytes_per_chunk = (GRANULE * FOOTPRINT_CHUNK_BITS);
    void const *chunk_address = (void const *)((unsigned long)p & ~(bytes_per_chunk-1));
    unsigned long chunk_index = (unsigned long)chunk_address / bytes_per_chunk;
    unsigned int const bucket = chunk_index % FOOTPRINT_N_BUCKETS;
    FootprintChunk *fc;
    for (fc = fp->granules_touched[bucket]; fc; fc = fc->next_in_bucket) {
        if (fc->chunk_address == chunk_address) {
            break;
        }
    }
    if (!fc) {
        fc = (FootprintChunk *)malloc(sizeof(FootprintChunk));
        fc->chunk_address = chunk_address;
        fc->n_access = 0;
        fc->bitmap_touch1 = 0;
        fc->bitmap_touchm = 0;
        fc->next_in_bucket = fp->granules_touched[bucket];
        fp->granules_touched[bucket] = fc;
    }
    ++fc->n_access;
    {
        unsigned int const offset = granule_index & (FOOTPRINT_CHUNK_BITS-1);
        unsigned long const mask = 1ULL << offset;    /* a 1-hot mask into the bitmap */
        if ((fc->bitmap_touch1 & mask) == 0) {
            ++fp->n_granules_touched;
            fc->bitmap_touch1 |= mask;
            return FOOTPRINT_FIRST_TOUCH;
        } else if ((fc->bitmap_touchm & mask) == 0) {
            fc->bitmap_touchm |= mask;
            return FOOTPRINT_SECOND_TOUCH;
        }
    }
    return FOOTPRINT_ALREADY_TOUCHED;
}


/*
Incrementally update working set characteristics, given another access.
Currently we don't distinguish reads and writes.
*/
void ws_update(WorkingSetCharacteristics *ws, void const *p, size_t access_size)
{
    ws->n_access++;
    void const *pe = (char const *)p + access_size;
    unsigned int const LINE = 64;

    assert(p != 0);
    assert(access_size > 0);
    assert(access_size == (access_size & -access_size));   /* check it's a power of 2 */
    if (ws->n_access == 1) {
        /* This is the first access */
        ws->min_address = p;
        ws->max_access_address = p;
        ws->hwm = pe;
    } else {
        /* Check if this access is contiguous with the previous access. */
        unsigned long pline = (unsigned long)(ws->most_recent_access) & ~(unsigned long)(LINE-1);
        unsigned long line = (unsigned long)p & ~(unsigned long)(LINE-1);
        if (line == pline) {
            ws->n_same_line++;
        }
        if (line == pline || line == pline+LINE) {
            ws->n_contig_access++;
        }
        if ((char const *)p < (char const *)ws->min_address) {
            ws->min_address = p;
        }
        if ((char const *)p > (char const *)ws->max_access_address) {
            ws->max_access_address = p;
        }
        if ((char const *)pe > (char const *)ws->hwm) {
            ws->hwm = pe;
        }
    }
    if (((unsigned long)p & (access_size-1)) != 0) {
        ws->n_unaligned += 1;
    }
    ws->most_recent_access = p;
    if (footprint_update(&ws->cache_line_footprint, p, LINE) == FOOTPRINT_SECOND_TOUCH) {
        // fprintf(DEBUG_FD, "repeat access to cache line %p\n", p);
    }
    footprint_update(&ws->page_footprint, p, 4096);
}


void ws_init(WorkingSetCharacteristics *ws)
{
    memset(ws, 0, sizeof *ws);
    ws->n_access = 0;
    ws->n_unaligned = 0;
    ws->min_address = 0;
    ws->max_access_address = 0;
    ws->hwm = 0;
    ws->most_recent_access = 0;
    ws->n_same_line = 0;
    ws->n_contig_access = 0;
}


static void footprint_free(Footprint *fp)
{
    unsigned int b;
    for (b = 0; b < FOOTPRINT_N_BUCKETS; ++b) {
        while (fp->granules_touched[b]) {
            FootprintChunk *fc = fp->granules_touched[b];
            fp->granules_touched[b] = fc->next_in_bucket;
            free(fc);
        }
    }
}


void ws_free(WorkingSetCharacteristics *ws)
{
    footprint_free(&ws->cache_line_footprint);
    footprint_free(&ws->page_footprint);
}


/*
 * Queries on the working set characteristics.
 */
size_t ws_range(WorkingSetCharacteristics const *ws)
{
    return (char const *)ws->hwm - (char const *)ws->min_address;
}


void ws_fprint(FILE *fd, WorkingSetCharacteristics const *ws)
{
    fprintf(fd, "Working set (%u accesses):\n", ws->n_access);
    fprintf(fd, "  From:      %p\n", ws->min_address);
    fprintf(fd, "  To:        %p\n", ws->hwm);
    fprintf(fd, "  Range:     %#lx\n", (unsigned long)ws_range(ws));
    fprintf(fd, "  Same:      %u\n", ws->n_same_line);
    fprintf(fd, "  Contig:    %u\n", ws->n_contig_access);
    fprintf(fd, "  Lines:     %u\n", ws->cache_line_footprint.n_granules_touched);
    fprintf(fd, "  4K pages:  %u\n", ws->page_footprint.n_granules_touched);
    fprintf(fd, "  Unaligned: %u\n", ws->n_unaligned);
}


/* end of workset.c */
