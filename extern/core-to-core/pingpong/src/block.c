/*
Copyright (C) ARM Ltd. 2016-2022

Memory block allocator for workload generator
*/

#include "block.h"

#ifndef _GNU_SOURCE
#define _GNU_SOURCE 1
#endif

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/mman.h>
#include <unistd.h>
#include <sys/syscall.h>
#include <sys/prctl.h>
#include <linux/prctl.h>
#include <linux/mempolicy.h>

#ifndef ASCT
#include "loadgenp.h"
#endif /* ASCT */
#include "idfill.h"
#include "cacheline.h"
#include "round.h"
#include "crc32.h"


/* PR_SET_VMA was introduced in 5.17: but our headers might be out of date */
#ifndef PR_SET_VMA
#define PR_SET_VMA           0x53564d41
#define PR_SET_VMA_ANON_NAME 0
#endif

extern int workload_verbose;


static unsigned long round_size_to_pages(unsigned long size)
{
    return round_size_up(size, sysconf(_SC_PAGESIZE));
}


/*
 * Find out the system's huge page size, so that we can safely use MAP_HUGETLB.
 * MAP_HUGETLB allocations must be rounded up to this size.
 *
 * Return 0 if we can't find the size.
 *
 * We can cache the result, on the assumption it won't change during the
 * program lifetime. The result is valid even if nr_hugepages==0.
 *
 * This is over-simplistic when we have multiple huge page sizes.
 * For more info on huge pages install libhugetlbfs-dev and use the 'hugeadm' tool,
 * or look under /sys/kernel/mm/hugepages .
 */
static unsigned long huge_page_size(void)
{
    static unsigned long size = 1;   /* Never valid; initiates discovery */
    if (size == 1) {
        FILE *fd = fopen("/proc/meminfo", "r");
        char buf[100];
        while (fgets(buf, sizeof buf, fd)) {
            if (!memcmp(buf, "Hugepagesize:", 13)) {
                long sizek = 0;
                if (sscanf(buf+13, "%ld", &sizek) == 1) {
                    size = sizek * 1024;
                    if (size != 0) {
                        assert((size & -size) == size);   /* power of 2 */
                        assert((long)size > sysconf(_SC_PAGESIZE));  /* TBD: always? */
                    }
                    break;
                }
            }
        }
        fclose(fd);
        if (size == 1) {
            fprintf(stderr, "Couldn't get huge page size\n");
            size = 0;
        }
    }
    return size;
}


static int is_naturally_aligned(uint64_t page, void *addr, uint64_t size)
{
    return ((uintptr_t)addr % page) == 0 && (size % page) == 0;
}


static int is_naturally_aligned_huge(void *addr, uint64_t size)
{
    return is_naturally_aligned(huge_page_size(), addr, size);
}


/*
 * See how many huge pages have been reserved.
 * We could cache this - but the caller might be experimenting with setting it differently.
 * Hopefully we only call this when trying to explain a failed allocation.
 *
 * Return -1 if we can't determine the number of huge pages.
 */
static int nr_hugepages(void)
{
    int n = -1;
    FILE *fd = fopen("/proc/sys/vm/nr_hugepages", "r");
    if (fd) {
        if (fscanf(fd, "%d", &n) != 1) {
            n = -1;
        }
        fclose(fd);
    }
    return n;
}


#if 0
static long
set_mempolicy(int mode, unsigned long const *nodemask, unsigned long maxnode)
{
    return (long)syscall(SYS_set_mempolicy, mode, nodemask, maxnode);
}
#endif


static long
mbind(void *addr, unsigned long len, int mode,
      unsigned long const *nodemask, unsigned long maxnode,
      unsigned int flags)
{
    return (long)syscall(SYS_mbind, addr, len, mode, nodemask, maxnode, flags);
}


static unsigned long total_mmap_size = 0;
static unsigned int total_mmap_count = 0;


/*
 * Initialize (construct) a block object.
 */
Block *block_init(Block *m)
{
    memset(m, 0, sizeof *m);   /* Zero the block object, not the block */
    return m;
}


/*
 * Heap-allocate and construct a new memory-block descriptor object (Block).
 * This doesn't allocate the actual memory; that is done later with
 * block_alloc().
 */
Block *block_new(void)
{
    Block *m = (Block *)malloc(sizeof(Block));
    return block_init(m);
}


/*
 * Allocate some memory, e.g. for data or code working set.
 * The memory is page-aligned, so that we can later change its protection.
 * Before calling, the caller must fill in details of the request.
 * On return, the Block structure is filled in with the base
 * address and anything else we think relevant.
 * The base address is also returned directly, or NULL on failure.
 * TBD: What should we do for size zero?
 */
void *block_alloc(Block *m)
{
    void *p;
    unsigned long rsize;

    /* MAP_POPULATE is documented as pre-populating the page tables. */
    int flags = MAP_PRIVATE|MAP_ANONYMOUS;
    assert(!m->base);
    assert(m->size_req > 0);
    if (workload_verbose) {
        fprintf(stderr, "block: alloc 0x%lx huge=%d/%d",
            m->size_req, m->is_hugepage, m->is_force_hugepage);
        if (m->is_numa) {
            fprintf(stderr, " nodemask=0x%lx", m->nodemask);
        }
        if (m->fill_type != BLOCK_FILL_NONE) {
            fprintf(stderr, " fill=0x%x", m->fill_type);
        }
        if (m->user_name) {
            fprintf(stderr, " name=\"%s\"", m->user_name);
        }
        fprintf(stderr, "\n");
    }
    rsize = round_size_to_pages(m->size_req);
    /* MAP_HUGETLB is only available if the size is a multiple of the
       huge page size. When the user requests HUGETLB for a smaller allocation,
       do they want us to round up the size, or ignore HUGETLB? */
    if ((m->is_hugepage && rsize >= huge_page_size()) ||
        m->is_force_hugepage) {
        /* Is it even worth doing this if /proc/sys/vm/nr_hugepages is 0? */
        flags |= MAP_HUGETLB;
        rsize = round_size_up(rsize, huge_page_size());
        if (workload_verbose) {
            fprintf(stderr, "block: hugepage requested: rounding size from %#lx to %#lx\n",
                m->size_req, rsize);
        }
    }
    /* We can't force mmap() to allocate with small pages.
       But we can allocate without population, then madvise(MADV_NOHUGEPAGE),
       then populate. */
    if (!m->is_no_hugepage) {
        flags |= MAP_POPULATE;
    }
    if (0) {
        /* To force a larger-than-default huge page we need to put the log2 of the
           specific huge page size (must be one of the supported ones) into the flags. */
        unsigned int hpl = 16;   /* 64K pages; 21 for 2M; 25 for 32M */
        flags |= (hpl << 26);
    }
    m->prot = 0;
    m->size = rsize;
    m->base = NULL;
    if (1) {
        /* _GNU_SOURCE should have ensured we see MAP_ANONYMOUS */
        m->prot = PROT_READ;
        if (m->is_exec) {
            m->prot |= PROT_EXEC;
        }
        if (!m->is_readonly || m->fill_type) {
            if (m->is_readonly && workload_verbose) {
                fprintf(stderr, "block: allocating writeable to allow fill\n");
            }
            m->prot |= PROT_WRITE;
        }
        assert(!(flags & MAP_HUGETLB) || (rsize % huge_page_size()) == 0);
        if (workload_verbose) {
            fprintf(stderr, "block: mmap %lu/%#lx bytes, prot=0x%04x, flags=0x%04x\n",
                (unsigned long)rsize, (unsigned long)rsize,
                (unsigned int)m->prot, (unsigned int)flags);
        }
        p = mmap(NULL, rsize, m->prot, flags, -1, 0);
        if (p != MAP_FAILED && workload_verbose) {
            fprintf(stderr, "block: %p size %#zx allocated\n", p, rsize);
        }
        if (p == MAP_FAILED && (flags & MAP_HUGETLB) != 0 && errno == ENOMEM) {
            /* See if the request could never be satisified because the predefined
               pool of huge pages is too small - it may of course have failed because
               some pages from the pool are already in use. */
            int hp_defd = nr_hugepages();
            size_t hp_size = huge_page_size();
            int hp_reqd = rsize / hp_size;
            if (workload_verbose) {
                fprintf(stderr, "block: %d %#zx-byte huge pages needed, /proc/sys/vm/nr_hugepages is %d\n",
                    hp_reqd, hp_size, hp_defd);
            }
            if (hp_defd < hp_reqd) {
                if (m->is_force_hugepage) {
                    /* Caller wants huge pages always, and we should fail if impossible */
                    return NULL;
                }
            }
            /* Try again, allocating a non-HUGETLB area and then using madvise() to force huge pages.
               To maximise chances of returning a huge-page area to the user, we allocate an excess of
               one huge-page size, and then trim it to huge-page boundaries. */
            uint64_t excess = huge_page_size();
            flags = flags & ~MAP_HUGETLB;
            /* We don't want the pages to be allocated until we've done madvise() */
            flags = flags & ~MAP_POPULATE;
            if (workload_verbose) {
                fprintf(stderr, "block: mmap(MAP_HUGETLB) failed, retry size=%#zx, flags=%#04x then madvise(MADV_HUGEPAGE)\n",
                    rsize+excess, flags);
            }
            p = mmap(NULL, rsize+excess, m->prot, flags, -1, 0);
            if (p != MAP_FAILED) {
                /* Trim any excess at the start */
                void *p_up = round_addr_up(p, hp_size);
                size_t start_trim = (unsigned char *)p_up - (unsigned char *)p;
                if (start_trim > 0) {
                    if (workload_verbose) {
                        fprintf(stderr, "block: mmap at %p, rounding to %p, unmapping %#zx bytes\n", p, p_up, start_trim);
                    }
                    int rc = munmap(p, start_trim);    /* not expected to fail */
                    if (rc) {
                        perror("munmap (round up)");
                    }
                    p = p_up;
                    excess -= start_trim;
                    if (excess > 0) {
                        void *p_end = (unsigned char *)p + rsize;
                        rc = munmap(p_end, excess);        /* not expected to fail */
                        if (rc) {
                            perror("munmap (trim end)");
                        }
                    }
                }
            }
        }
        if (p == MAP_FAILED) {
            perror("mmap");
            fprintf(stderr, "Failed to allocate %lu/%#lx bytes (flags 0x%x, page size %lu): total out %u, %lu bytes\n",
                (unsigned long)rsize, (unsigned long)rsize,
                (unsigned int)flags,
                (unsigned long)sysconf(_SC_PAGESIZE),
                total_mmap_count,
                (unsigned long)total_mmap_size);
            return NULL;
        }
        total_mmap_count += 1;
        total_mmap_size += rsize;
        m->is_mmap = 1;
        /* We don't need to use MADV_HUGEPAGE, as we will have mmap'ed with MAP_HUGETLB */
        if ((m->is_hugepage || m->is_force_hugepage) && !(flags & MAP_HUGETLB)) {
#ifdef MADV_HUGEPAGE
            /* "Enable THP for pages in the range specified by addr and length.
               The kernel will regularly scan the areas marked as huge page
               candidates to replace them with huge pages. The kernel will also
               allocate huge pages directly when the region is natually aligned
               to the huge page size." */
            if (0) {
                fprintf(stderr, "block: %p %#zx naturally aligned huge?: %d\n", p, rsize, is_naturally_aligned_huge(p, rsize));
            }
            if (workload_verbose) {
                fprintf(stderr, "block: madvise(%p, %#zx, MADV_HUGEPAGE)\n", p, rsize);
            }
            int rc = madvise(p, rsize, MADV_HUGEPAGE);
            if (rc < 0) {
                perror("madvise");
                m->is_hugepage = 0;
            }
#else
            fprintf(stderr, "MADV_HUGEPAGE not available when this module was built\n");
            m->is_hugepage = 0;
#endif
        }
        if (m->is_no_hugepage) {
#ifdef MADV_NOHUGEPAGE
            int rc = madvise(p, rsize, MADV_NOHUGEPAGE);
            if (rc < 0) {
                perror("madvise");
                m->is_no_hugepage = 0;
            }
#else
            fprintf(stderr, "MADV_NOHUGEPAGE not available when this module was built\n");
            m->is_no_hugepage = 0;
#endif
        }
    }
    m->base = p;
    if (workload_verbose) {
        fprintf(stderr, "block: alloc %p size %lu/%#lx (%s)\n",
            m->base, m->size, m->size, (m->user_name ? m->user_name : "anon"));
    }
    if (m->user_name) {
        if (block_set_name(m, m->user_name)) {
            /* Failed to set name - sometimes happens if huge pages are allocated */
            m->user_name = NULL;
        }
    }
    /* TBD: Do we need is_numa? Or is it enough to test nodemask != 0? */
    if (m->is_numa) {
        int rc = block_bind_nodemask(m, m->nodemask);
        if (rc) {
            block_free(m);
            return NULL;
        }
    }
    if (m->fill_type) {
        if (workload_verbose) {
            fprintf(stderr, "block: %p: filling with type 0x%x\n", m->base, m->fill_type);
        }
        block_fill(m, m->fill_type);
        if (m->is_readonly) {
            /* Block was only temporarily writeable for the fill */
            if (workload_verbose) {
                fprintf(stderr, "block: %p: write-protecting after fill\n", m->base);
            }
            block_protect(m, m->prot - PROT_WRITE);
        }
    }
    assert(p != NULL);
    return p;
}


static void block_fill_random(void *pv, size_t size, uint32_t seed)
{
    uint32_t *p = (uint32_t *)pv;
    while (size > 0) {
        seed = crc32w(seed, 0);
        *p++ = seed;
        size -= 4;
    }
}


int block_fill(Block *m, uint16_t fill_type)
{
    m->fill_type = fill_type;
    if (fill_type == BLOCK_FILL_NONE) {
        /* do nothing */
    } else if (fill_type & BLOCK_FILL_BYTE(0)) {
        uint8_t byte = fill_type & 0xff;
        memset(m->base, byte, m->size);
    } else if (fill_type == BLOCK_FILL_DEFAULT) {
        memset(m->base, 0xCC, m->size);
    } else if (fill_type == BLOCK_FILL_IDFILL_NO_PA ||
               fill_type == BLOCK_FILL_IDFILL_PA) {
        return block_idfill(m, m->user_name ? m->user_name : "anon",
                            fill_type == BLOCK_FILL_IDFILL_PA);
    } else if (fill_type == BLOCK_FILL_RANDOM) {
        block_fill_random(m->base, m->size, (uint32_t)(uintptr_t)m->base);
    } else {
        return 1;
    }
    return 0;
}


int block_protect(Block *m, int prot)
{
    if (prot != m->prot) {
        int rc = mprotect(m->base, m->size, prot);
        if (rc) {
            perror("mprotect");
        } else {
            m->prot = prot;
        }
        return rc;
    } else {
        return 0;
    }
}


int block_advise(Block *m, int advice)
{
    int rc = madvise(m->base, m->size, advice);
    if (rc) {
        perror("madvise");
    }
    return rc;
}


int block_bind_nodemask(Block *m, unsigned long nodemask)
{
    int rc = mbind(m->base, m->size, MPOL_BIND|MPOL_F_STATIC_NODES, &nodemask, (sizeof nodemask)*8, MPOL_MF_MOVE|MPOL_MF_STRICT);
    if (rc) {
        /* e.g. nodemask specifies NUMA nodes that don't exist */
        perror("mbind");
        fprintf(stderr, "block: %p size %#lx failed to bind to nodemask %#lx\n",
            m->base, m->size, nodemask);
    }
    return rc;
}


int block_set_name(Block *m, char const *name)
{
    /* "The name can contain only printable ascii characters (including space),
        except '[', ']', '\', '$', and '`'." */
    int rc;
    if (workload_verbose) {
        fprintf(stderr, "block: %p size %#zx set name: %s\n", m->base, m->size, name ? name : "(null)");
    }
    rc = prctl(PR_SET_VMA, PR_SET_VMA_ANON_NAME, m->base, m->size, (unsigned long)name);
    if (rc < 0 && workload_verbose) {
        /* Hugepage mapped areas default to "/anon_hugepage (deleted)".
           It seems that prctl will return EBADF in this situation. */
        perror("prctl");
    }
    return rc;
}


/*
 * Fill a block with an easily recognizable signature,
 * incorporating virtual address and physical address.
 * Addresses are duplicated in case overwritten by
 * pointer-chain etc.
 */
int block_idfill(Block *m, char const *sig, int pa)
{
    return idfill_fill(m->base, m->size, sig, pa);
}


uint32_t block_crc32(Block const *m)
{
    return crc32_buffer(CRC32_INIT, m->base, m->size);
}


/*
 * Free the memory allocated for this block.
 * Don't free the block descriptor object itself.
 * In fact, the block descriptor can be reused.
 */
void block_free(Block *m)
{
    if (m->base) {
        if (workload_verbose) {
            fprintf(stderr, "block: free %p size %lu/%#lx\n", m->base, m->size, m->size);
        }
        if (m->is_mmap) {
            unsigned long rsize = round_size_to_pages(m->size);
            assert(total_mmap_size >= rsize);
            munmap(m->base, rsize);
            total_mmap_count -= 1;
            total_mmap_size -= rsize;
        } else {
            free(m->base);
        }
        m->base = NULL;
    }
}


void block_fprint(Block const *m, FILE *fd, int max_lines)
{
    unsigned int i;
    unsigned int const n_lines = round_count_down(m->size_req, cache_line_length());
    unsigned int n_printed = 0;
    fprintf(fd, "Block %p size %zu/%#zx requested %zu/%#zx:",
        (void *)m, m->size, m->size, m->size_req, m->size_req);
    if (!m->base) {
        fprintf(fd, "<unallocated>\n");
        return;
    }
    fprintf(fd, "\n");
    for (i = 0; i < n_lines; ++i) {
        int j;
        unsigned char const *p = (unsigned char const *)m->base + (i * 64);
        fprintf(fd, "  %p: ", p);
        for (j = 0; j < 64; ++j) {
            if (!(j % 8)) {
                fprintf(fd, " ");
            }
            fprintf(fd, "%02x", p[j ^ 7]);
        }
        fprintf(fd, "\n");
        ++n_printed;
        if (max_lines >= 0 && (int)n_printed >= max_lines && n_printed < n_lines) {
            fprintf(fd, "  ...\n");
            break;
        }
    }
}


/* end of block.c */
