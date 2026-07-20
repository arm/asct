/*
 * Copyright (C) Arm Ltd. 2025. All rights reserved.
 *
 * WorkingSet object.
 *
 * This object captures measured characteristics of a working set.
 * Can be fed a trace and will update the working set properties.
 *
 * Currently this is very simplistic.
 *
 * We don't attempt to characterize how this working set would
 * interact with various cache geometries. For example,
 * a working set which consisted of accesses at n, n+4K, n+8K
 * etc. might have a lot of conflicts due to aliasing.
 *
 * Nor do we characterize how many distinct
 * granules of size N are touched, where interesting values of
 * N would relate to various caching mechanisms such as
 *   - data cache line: 64-bytes or (occasionally) 128-bytes
 *   - TLB entry for 4K page
 *   - TLB entry for huge (512K) page
 * Nor do we characterize the "page walk working set" or the
 * amount of space that would be taken up by caching one or more
 * levels of page table.
 *
 * Other things being equal, for a dense working set we'd expect
 *   - number of 4K pages to be size / 4K
 *   - one TLB entry per page assuming no compression
 * So for an 8M working set with no huge pages we'd have
 *   - 2048 pages
 *   - 2048 last-level page table entries
 *   - 16K of last-level page tables
 */

#ifndef __included_workset_h
#define __included_workset_h

#include <stdio.h>
#include <stddef.h>


typedef struct FootprintChunk {
    struct FootprintChunk *next_in_bucket;
    void const *chunk_address;
#define FOOTPRINT_CHUNK_BITS (8 * sizeof(unsigned long))     /* number of granules per chunk */
    unsigned long bitmap_touch1;    /* touched at least once: touch1 and touchm form a saturating-to-2 counter */
    unsigned long bitmap_touchm;    /* touched more than once */
    unsigned int n_access;
} FootprintChunk;


typedef struct Footprint {
#define FOOTPRINT_N_BUCKETS 1024
    FootprintChunk *granules_touched[FOOTPRINT_N_BUCKETS];
    unsigned int n_granules_touched;
} Footprint;


typedef struct WorkingSet {
    void const *min_address;        /* lowest address accessed */
    void const *max_access_address; /* max (base) address of access */
    void const *hwm;                /* high water mark allowing for access size */
    unsigned int n_access;          /* number of accesses */
    unsigned int n_unaligned;       /* number of unaligned accesses */
    void const *most_recent_access; /* the most recent access - to detect simple streaming */
    unsigned int n_same_line;       /* number of accesses on same line */
    unsigned int n_contig_access;   /* number of accesses on same line or next line */
    Footprint cache_line_footprint;
    Footprint page_footprint;
} WorkingSetCharacteristics;

void ws_init(WorkingSetCharacteristics *);

/*
 * Update the working set characteristics, to record an access
 * at a given address.
 */
void ws_update(WorkingSetCharacteristics *, void const *p, size_t access_size);

/*
 * Free memory internally allocated - don't free the object itself
 */
void ws_free(WorkingSetCharacteristics *);

/*
 * Range of working set (in bytes)
 */
size_t ws_range(WorkingSetCharacteristics const *);

/*
 * Print working set characteristics.
 */
void ws_fprint(FILE *, WorkingSetCharacteristics const *);

#endif /* __included_workset_h */

/* end of workset.h */
