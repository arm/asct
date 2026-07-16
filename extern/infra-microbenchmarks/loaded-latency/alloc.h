
/*
 * SPDX-FileCopyrightText: Copyright 2019-2023 Arm Limited and/or its affiliates <open-source-office@arm.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

#ifndef ALLOC_H
#define ALLOC_H

enum {
    HUGEPAGES_NONE,
    HUGEPAGES_DEFAULT,
    HUGEPAGES_64K,
    HUGEPAGES_2M,
    HUGEPAGES_32M,
    HUGEPAGES_512M,
    HUGEPAGES_1G,
    HUGEPAGES_16G,
    HUGEPAGES_MAX_ENUM
};
#ifdef ASCT
#if defined(__x86_64__) || (defined(__aarch64__) && defined(HAS_SVE))
#define NT_STORE_AVAILABLE 1
#else
#define NT_STORE_AVAILABLE 0
#endif
typedef enum {
    READ_ONLY = 0,
    WRITE_ONLY,
    READ_WRITE_3_1,
    READ_WRITE_2_1,
    READ_WRITE_1_1,
#if NT_STORE_AVAILABLE
    READ_WRITE_2_1_NT_STORE,
#endif
    BW_MODE_MAX_ENUM
} bw_mode_t;
#endif


void * do_alloc(size_t length, int use_hugepages, size_t nonhuge_alignment);
#ifdef ASCT
size_t partition_n_aligned_memory(void * mem, size_t length, int num_parts,
    size_t alignment, void ** parts);
#endif

#endif
