/*
 * Copyright (C) Arm Ltd. 2025. All rights reserved.
 *
 * Address translation
 *
 * Translates virtual to physical address (or IPA if in guest).
 * Uses /proc/self/pagemap.
 *
 * Will generally require sudo privilege.
 *
 * Note: in a non-metal VM, "physical address" is intermediate physical address (IPA)
 * i.e. the output of stage-1 translation. Finding the actual physical address would
 * require a paravirtualization API.
 */

#ifndef __included_vatopa_h
#define __included_vatopa_h

#include <stdint.h>
#include <stddef.h>


typedef uint64_t phys_addr_t;


/*
 * Get the physical address for a virtual address in the current process.
 */
phys_addr_t vatopa(void const volatile *);


/*
 * Get the physical address for a virtual address in a process.
 */
phys_addr_t vatopa_pid(uintptr_t, int);   /* use pid -1 for self */


/*
 * Error codes (encoded in phys_addr_t) indicating bad VA or failure to look up VA.
 */
#define VATOPA_NOT_AVAILABLE         0xffffffffffffffff   /* not privileged, PAs read as zeroes */
#define VATOPA_INVALID_VA            0xfffffffffffffffe   /* VA is not mapped into address space */
#define VATOPA_INVALID_PID           0xfffffffffffffffd
#define VATOPA_NO_ACCESS             0xfffffffffffffffc   /* e.g. access other pid */
#define VATOPA_INVALID_PE            0xfffffffffffffffb   /* unexpected contents in page entry */
#define VATOPA_IS_ERROR(pa) ((pa) >= 0xfffffffffffffff0)


typedef enum {
    VA_ATTR_VALID,           /* VA is valid (virtual address) */
    VA_ATTR_UNMAPPED,        /* VA is not mapped to anything - will page-fault */
    VA_ATTR_NONEXCLUSIVE,    /* VA is mapped non-exclusively - includes zero-page */
    VA_ATTR_HUGE,            /* VA is (in a) huge page (marked as huge by kernel) */
    VA_ATTR_FILE,            /* VA is mapped to a file */
    VA_ATTR_MAX
} vatopa_attr_t;


#define VA_MAP_HAS_KPF
typedef struct {
    uintptr_t va;    /* Virtual address */
    phys_addr_t pa;  /* Physical address (or IPA) */
    size_t size;     /* Range of mapping */
    uint16_t flags;  /* Mapping flags */
    uint16_t pebits; /* Page entry top 16 bits (raw) */
#ifdef VA_MAP_HAS_KPF
    uint64_t kpf;    /* Kernel page flags (kpageflags) */
#endif
} vatopa_map_t;

#define VA_MAP_UNMAPPED      (1U << VA_ATTR_UNMAPPED)      /* VA is not mapped at all */
#define VA_MAP_NONEXCLUSIVE  (1U << VA_ATTR_NONEXCLUSIVE)
#define VA_MAP_FILE          (1U << VA_ATTR_FILE)
#define VA_MAP_HUGE          (1U << VA_ATTR_HUGE)


/*
 * Statistics about a range of addresses
 *
 * Most stats are in terms of base pages (SC_PAGESIZE)
 */

typedef struct {
    uint32_t stat[VA_ATTR_MAX];   /* Counts of pages with the various attributes */
    uint32_t n_discontiguous;     /* Pages which jump in PA from previous page */
    phys_addr_t pa_low;           /* Lowest physical address encountered */
    phys_addr_t pa_high;          /* Highest physical address encountered (end of block) */
} vatopa_stat_t;

void vatopa_stat_init(vatopa_stat_t *);


/*
 * Get physical addresses for a range of virtual addresses.
 * Return the number of addr_map_t entries used (or needed).
 */
int vatopa_get_map(void const volatile *, size_t, vatopa_stat_t *, vatopa_map_t *, unsigned int);

int vatopa_get_map_pid(uintptr_t, size_t, vatopa_stat_t *, vatopa_map_t *, unsigned int, int);


#endif /* included */
