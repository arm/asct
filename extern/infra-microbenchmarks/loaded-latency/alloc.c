
/*
 * SPDX-FileCopyrightText: Copyright 2019-2023 Arm Limited and/or its affiliates <open-source-office@arm.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <linux/mman.h>
#include <string.h>
#ifdef ASCT
#include <stdint.h>
#endif

#include "alloc.h"

void * do_alloc(size_t length, int use_hugepages, size_t nonhuge_alignment) {

    if (use_hugepages != HUGEPAGES_NONE) {
        int hugepage_size_flag = HUGEPAGES_DEFAULT;
        switch (use_hugepages) {
            case HUGEPAGES_64K:
                hugepage_size_flag = MAP_HUGE_64KB;
                break;
            case HUGEPAGES_2M:
                hugepage_size_flag = MAP_HUGE_2MB;
                break;
            case HUGEPAGES_32M:
                hugepage_size_flag = MAP_HUGE_32MB;
                break;
            case HUGEPAGES_512M:
                hugepage_size_flag = MAP_HUGE_512MB;
                break;
            case HUGEPAGES_1G:
                hugepage_size_flag = MAP_HUGE_1GB;
                break;
            case HUGEPAGES_16G:
                hugepage_size_flag = MAP_HUGE_16GB;
                break;
        }
        void * mmap_ret = mmap(NULL, length,
                       PROT_READ|PROT_WRITE,
                       MAP_PRIVATE|MAP_ANONYMOUS|MAP_HUGETLB|MAP_POPULATE|hugepage_size_flag,
                       -1, 0);

        if (mmap_ret == MAP_FAILED) {
            printf("mmap returned %p (MAP_FAILED) for latency thread setup. Exiting!\n"
                   "You probably need to allocate hugepages. Try:\n"
                   " sudo apt-get install libhugetlbfs-bin\n"
                   " sudo hugeadm --create-global-mounts\n"
                   " sudo hugeadm --pool-pages-max DEFAULT:+1000\n"
                   "(Only the last line is needed after a reboot.)\n"
                   "Or, no pages of the requested hugepage size are available.\n",
                   mmap_ret);
            exit(-1);
        }

        return mmap_ret;
    }

    void * p;

    int ret = posix_memalign((void **) &p, nonhuge_alignment, length);

    if (ret) {
        printf("posix_memalign returned %d, exiting\n", ret);
        exit(-1);
    }

    // prefault
    memset(p, 1, length);

    return p;
}

#ifdef ASCT
// Added routine to parition memory into 2 or 3 parts for multiple stream microbenchmark runs
size_t partition_n_aligned_memory(void *mem, size_t buflen, int num_parts, size_t part_align, void **parts) {
    if (mem == NULL) {
        printf("partition_n_aligned_memory: mem is NULL, exiting\n");
        exit(-1);
    }
    // mem must be aligned to part_align already 
    if((((uintptr_t)mem) & (part_align - 1)) != 0) 
    {
        printf("partition_n_aligned_memory: mem %p is not aligned to part_align %zu, exiting\n", mem, part_align);
        exit(-1);
    }
    if (buflen == 0) {
        printf("partition_n_aligned_memory: buflen is 0, exiting\n");
        exit(-1);
    }
    if (num_parts <= 0) {
        printf("partition_n_aligned_memory: num_parts %d is not positive, exiting\n", num_parts);
        exit(-1);
    }
    if (parts == NULL) {
        printf("partition_n_aligned_memory: parts is NULL, exiting\n");
        exit(-1);
    }

    // part_align must be a power of 2
    if((part_align & (part_align - 1)) != 0) {
        printf("partition_n_aligned_memory: part_align %zu is not a power of 2, exiting\n", part_align);
        exit(-1);
    }


    size_t part_size = buflen / num_parts;
    // Compute the aligned size of each part
    size_t part_size_aligned = part_size & ~(part_align - 1);

    // safety check
    if(((size_t)num_parts * part_size_aligned) > buflen) {
        printf("partition_n_aligned_memory: buflen %zu too small to partition into %d parts with aligned size %zu\n",
            buflen, num_parts, part_size_aligned);
        exit(-1);
    };  

    size_t offset = 0;
    for (int i = 0; i < num_parts; i++) {
        parts[i] = (char *)mem + offset;
        offset += part_size_aligned;
    }

    return part_size_aligned;
}
#endif