/*
 * Copyright (C) Arm Ltd. 2025. All rights reserved.
 */

#include <assert.h>

#include "vatopa.h"

#include "round.h"

#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <linux/kernel-page-flags.h>


/*
 * Translate virtual address to physical address.
 * (If in a guest, this will be IPA.)
 *
 * We open /proc/self/pagemaps (once), and then for each translation
 * we seek and read the corresponing entry.
 * n.b. the file must be unbuffered, otherwise we risk reading
 * stale entries.
 */
#define PFN_MASK 0x007fffffffffffff   /* 55 bits for PFN */

#define PE_PRESENT(pe)     (((pe) & 0x8000000000000000) != 0)
#define PE_PFN(pe)         ((pe) & PFN_MASK)
#define PE_MMAP_EXCLUSIVE  (1ULL << 56)
#define PE_FILE            (1ULL << 61)

/*
 * Get the Linux page entry
 */
static phys_addr_t
vatopa_get_page_pe(unsigned long page_number, int pid, uint64_t *pep)
{
    int rc;
    uint64_t pe = 0xBAD;
    static FILE *pmfd = NULL;
    static int pmfd_pid = 0;
    if (!pmfd || (pid != pmfd_pid)) {
        char fn[6+30+9];        /* "/proc/<pid>/pagemap" */
        if (pmfd) {
            fclose(pmfd);
            pmfd = NULL;
        }
        if (pid == -1) {
            pid = getpid();
        }
        sprintf(fn, "/proc/%u/pagemap", pid);
        pmfd = fopen(fn, "rb");
        if (!pmfd) {
            /* Unexpected - file exists even if non-root */
            if (errno == ENOENT) {
                return VATOPA_INVALID_PID;
            }
            if (errno == EACCES) {
                return VATOPA_NO_ACCESS;
            }
            perror("pagemap");
            return VATOPA_NOT_AVAILABLE;
        }
        setvbuf(pmfd, NULL, _IONBF, 0);
    }
    rc = fseek(pmfd, 8*page_number, SEEK_SET);
    if (rc) {
        perror("fseek");
        return VATOPA_NOT_AVAILABLE;
    }
    rc = fread(&pe, sizeof pe, 1, pmfd);
    if (rc != 1) {
        perror("fread");
        return VATOPA_NOT_AVAILABLE;
    }
    if (0) {
        uintptr_t va = page_number * sysconf(_SC_PAGESIZE);
        fprintf(stderr, "vatopa (pid=%d): %p -> %016llx\n",
            pid, (void *)va, (unsigned long long)pe);
    }
    *pep = pe;
    if (PE_PRESENT(pe)) {
        /* Valid (present) entry - but PFN may read as zero if we're unprivileged. */
        if (PE_PFN(pe) == 0) {
            /* If we haven't got sufficient privilege, the pagemap
               entry will show something like 8100000000000000. */
            return VATOPA_NOT_AVAILABLE;
        }
        return 0;
    } else if (PE_PFN(pe) == 0) {
        /* Address not (yet) mapped to physical page - includes case
           where OS has allocated the VA range to us but not yet backed
           it with a physical page. We might see some flags set
           e.g. _PM_SOFT_DIRTY. */
        return VATOPA_INVALID_VA;
    } else {
        uintptr_t va = page_number * sysconf(_SC_PAGESIZE);
        fprintf(stderr, "bad pagemap entry for %p (pid=%d): 0x%016lx\n",
            (void const *)va, pid, (unsigned long)pe);
        return VATOPA_INVALID_PE;
    }
}


#define PFN_FLAGS_BAD 0xffffffffffffffff

static uint64_t
pfn_flags(uint64_t pfn)
{
    uint64_t flags = PFN_FLAGS_BAD;
    int rc;
    static FILE *kpfd = NULL;
    if (!kpfd) {
        kpfd = fopen("/proc/kpageflags", "rb");
        if (!kpfd) {
            perror("open");
            return PFN_FLAGS_BAD;
        }
    }
    rc = fseek(kpfd, 8*pfn, SEEK_SET);
    if (rc) {
        perror("fseek");
        return PFN_FLAGS_BAD;
    }
    rc = fread(&flags, sizeof flags, 1, kpfd);
    if (rc != 1) {
        perror("fread");
        return PFN_FLAGS_BAD;
    }
    return flags;
}


phys_addr_t vatopa_pid(uintptr_t p, int pid)
{
    unsigned long const page_size = sysconf(_SC_PAGESIZE);
    uint64_t pe;
    phys_addr_t pa = vatopa_get_page_pe((p / page_size), pid, &pe);
    if (VATOPA_IS_ERROR(pa)) {
        return pa;     /* Couldn't get the page entry, or it was invalid */
    }
    assert(PE_PRESENT(pe));
    return (PE_PFN(pe) * page_size) + (p % page_size);
}


phys_addr_t vatopa(void const volatile *p)
{
    return vatopa_pid((uintptr_t)p, -1);
}


#define BIT(x, n) (((x) >> (n)) & 1)

int
vatopa_get_map_pid(uintptr_t addr, size_t size, vatopa_stat_t *stats, vatopa_map_t *maps, unsigned int n_maps, int pid)
{
    /* Round beginning and end up to page boundaries */
    unsigned long const page_size = sysconf(_SC_PAGESIZE);
    uintptr_t const addr_start = round_size_down(addr, page_size);
    uintptr_t const addr_end = round_size_up(addr+size, page_size);
    unsigned int n = 0;
    if (!maps) {
        n_maps = 0;
    }
    phys_addr_t last_pa = VATOPA_INVALID_VA;
    for (addr = addr_start; addr < addr_end; addr += page_size) {
        uint64_t pe;
        uint16_t flags = 0;
        uint64_t kpf = 0;
        uint64_t pfn = 0;
        phys_addr_t err = vatopa_get_page_pe(addr / page_size, pid, &pe);
        if (err == VATOPA_INVALID_VA) {
            flags = VA_MAP_UNMAPPED;
        } else if (VATOPA_IS_ERROR(err)) {
            return (int)err;
        } else {
            /* PE has PFN and other details */
            pfn = PE_PFN(pe);
            kpf = pfn_flags(pfn);
            if (!(pe & PE_MMAP_EXCLUSIVE)) {
                flags |= VA_MAP_NONEXCLUSIVE;   /* e.g. zero page */
            }
            if (pe & PE_FILE) {
                flags |= VA_MAP_FILE;
            }
            if (kpf != PFN_FLAGS_BAD) {
                if (BIT(kpf, KPF_HUGE) | BIT(kpf, KPF_THP)) {
                    flags |= VA_MAP_HUGE;
                }
            }
        }
        if (stats) {
            int i;
            for (i = 0; i < VA_ATTR_MAX; ++i) {
                if (flags & (1<<i)) {
                    ++stats->stat[i];
                }
            }
            ++stats->stat[VA_ATTR_VALID];
            if (!VATOPA_IS_ERROR(err)) {
                phys_addr_t pa = pfn * page_size;
                if (last_pa != VATOPA_INVALID_VA && pa != (last_pa + page_size)) {
                    fprintf(stderr, "low %#lx last %#lx now %#lx\n", stats->pa_low, last_pa+page_size, pa);
                    ++stats->n_discontiguous;
                }
                last_pa = pa;
                if (stats->pa_low == 0 || pa < stats->pa_low) {
                    stats->pa_low = pa;
                }
                if (stats->pa_high == 0 || (pa+page_size) > stats->pa_high) {
                    stats->pa_high = (pa+page_size);
                }
            } else {
                if (last_pa != VATOPA_INVALID_VA) {
                    last_pa = VATOPA_INVALID_VA;
                    ++stats->n_discontiguous;
                }
            }
        }
        if (n < n_maps) {
            /* Add details to the next map entry */
            maps[n].va = addr;
            maps[n].size = page_size;
            maps[n].pebits = (pe >> 48);
            if (err == 0) {
                maps[n].pa = pfn * page_size;
#ifdef VA_MAP_HAS_KPF
                maps[n].kpf = kpf;
#endif
            } else {
                maps[n].pa = err;
            }
            maps[n].flags = flags;
        }
        ++n;
    }
    return n;
}


int
vatopa_get_map(void const volatile *p, size_t size, vatopa_stat_t *stats, vatopa_map_t *maps, unsigned int n_maps)
{
    return vatopa_get_map_pid((uintptr_t)p, size, stats, maps, n_maps, -1);
}


void
vatopa_stat_init(vatopa_stat_t *stats)
{
    memset(stats, 0, sizeof(vatopa_stat_t));
}
