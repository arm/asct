
/*
 * SPDX-FileCopyrightText: Copyright 2019-2023 Arm Limited and/or its affiliates <open-source-office@arm.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

#define _GNU_SOURCE
#include <pthread.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <errno.h>
#include <ctype.h>

#include <sys/time.h>
#include <sys/types.h>

#ifdef USE_HUGEPAGES
#include <sys/mman.h>
#endif

#ifdef __aarch64__
#include "cntvct.h"
#endif

#ifdef __x86_64__
#include "rdtsc.h"
#endif

#include "alloc.h"
#include "bandwidth.h"
#ifdef ASCT
#if NT_STORE_AVAILABLE && defined(__aarch64__)
#include <arm_sve.h>
#endif
#include <stdatomic.h>
#ifdef USE_PROBE
#include "dietperf.h"
#endif
#endif


/* my_read() provides a variable read bandwidth.
   Increasing inner_nops lowers the read bandwidth. */
static void my_read(void * p, size_t bytes, size_t inner_nops, size_t bw_cacheline_bytes)
    __attribute__((noinline));
static void my_read(void * p, size_t bytes, size_t inner_nops, size_t bw_cacheline_bytes) {
    size_t i, j, dummy;

    // this just reads one 64-bit dword from each cache lnie
    for (i = 0; i < bytes; i += bw_cacheline_bytes) {
#ifdef __aarch64__
        asm volatile ("ldr %0, [%1, %2]" : "=r" (dummy): "r" (p), "r" (i));
#endif
#ifdef __x86_64__
        asm volatile ("movq   (%1,%2,1), %0" : "=r" (dummy) : "r" (p), "r" (i));
#endif
        for (j = 0; j < inner_nops; j++) {
            asm volatile ("");
        }
    }
}
#ifdef ASCT // ASCT version, no need to add noop loop
__attribute__((noinline))
static void my_read_no_nops(void * p, size_t bytes, size_t bw_cacheline_bytes) {
    size_t i, dummy;

    // this just reads one 64-bit dword from each cache lnie
    for (i = 0; i < bytes; i += bw_cacheline_bytes) {
#ifdef __aarch64__
        asm volatile ("ldr %0, [%1, %2]" : "=r" (dummy): "r" (p), "r" (i));
#endif
#ifdef __x86_64__
        asm volatile ("movq   (%1,%2,1), %0" : "=r" (dummy) : "r" (p), "r" (i));
#endif
    }
}
__attribute__((noinline))
static void my_read_no_nops_rep_64b(void * p, size_t bytes, uint64_t repetitions) {
    // check for smaller loops first as they are more sensitive to extra control instructions
    const size_t bw_cacheline_bytes = 64;
    if (bytes < 2*bw_cacheline_bytes) {
        // fully unroll the loop for small data sizes
        for (size_t r = 0; r < repetitions; r++) {
            size_t dummy;
            #ifdef __aarch64__
                    asm volatile ("ldr %0, [%1, #0]"     : "=r"(dummy) : "r"(p));
            #endif
            #ifdef __x86_64__
                    asm volatile ("movq   (%1), %0" : "=r" (dummy) : "r" (p));
            #endif
        }
        return;
    }

    if (bytes < 3*bw_cacheline_bytes) {
        // fully unroll the loop for small data sizes
        for (size_t r = 0; r < repetitions; r++) {
            size_t dummy;
            #ifdef __aarch64__
                    asm volatile ("ldr %0, [%1, #0]"    : "=r"(dummy) : "r"(p));
                    asm volatile ("ldr %0, [%1, 64]"    : "=r"(dummy) : "r"(p));
            #endif
            #ifdef __x86_64__
                    asm volatile ("movq   (%1), %0" : "=r" (dummy)   : "r" (p));
                    asm volatile ("movq   64(%1), %0" : "=r" (dummy) : "r" (p));
            #endif
        }
        return;
    }

    if (bytes < 4*bw_cacheline_bytes) {
        // fully unroll the loop for small data sizes
        for (size_t r = 0; r < repetitions; r++) {
            size_t dummy;
            #ifdef __aarch64__
                    asm volatile ("ldr %0, [%1, #0]"     : "=r"(dummy) : "r"(p));
                    asm volatile ("ldr %0, [%1, 64]"    : "=r"(dummy)  : "r"(p));
                    asm volatile ("ldr %0, [%1, 2*64]"    : "=r"(dummy)  : "r"(p));
            #endif
            #ifdef __x86_64__
                    asm volatile ("movq   (%1), %0" : "=r" (dummy)   : "r" (p));
                    asm volatile ("movq   64(%1), %0" : "=r" (dummy) : "r" (p));
                    asm volatile ("movq   2*64(%1), %0" : "=r" (dummy) : "r" (p));
            #endif
        }
        return;
    }

    if (bytes < 5*bw_cacheline_bytes) {
        // fully unroll the loop for small data sizes
        for (size_t r = 0; r < repetitions; r++) {
            size_t dummy;
            #ifdef __aarch64__
                    asm volatile ("ldr %0, [%1, #0]"     : "=r"(dummy) : "r"(p));
                    asm volatile ("ldr %0, [%1, 64]"    : "=r"(dummy)  : "r"(p));
                    asm volatile ("ldr %0, [%1, 2*64]"    : "=r"(dummy)  : "r"(p));
                    asm volatile ("ldr %0, [%1, 3*64]"    : "=r"(dummy)  : "r"(p));
            #endif
            #ifdef __x86_64__
                    asm volatile ("movq   (%1), %0" : "=r" (dummy)   : "r" (p));
                    asm volatile ("movq   64(%1), %0" : "=r" (dummy) : "r" (p));
                    asm volatile ("movq   2*64(%1), %0" : "=r" (dummy) : "r" (p));
                    asm volatile ("movq   3*64(%1), %0" : "=r" (dummy) : "r" (p));
            #endif
        }
        return;
    }

    if (bytes < 6*bw_cacheline_bytes) {
        // fully unroll the loop for small data sizes
        for (size_t r = 0; r < repetitions; r++) {
            size_t dummy;
            #ifdef __aarch64__
                    asm volatile ("ldr %0, [%1, #0]"     : "=r"(dummy) : "r"(p));
                    asm volatile ("ldr %0, [%1, 64]"    : "=r"(dummy)  : "r"(p));
                    asm volatile ("ldr %0, [%1, 2*64]"    : "=r"(dummy)  : "r"(p));
                    asm volatile ("ldr %0, [%1, 3*64]"    : "=r"(dummy)  : "r"(p));
                    asm volatile ("ldr %0, [%1, 4*64]"    : "=r"(dummy)  : "r"(p));
            #endif
            #ifdef __x86_64__
                    asm volatile ("movq   (%1), %0" : "=r" (dummy)   : "r" (p));
                    asm volatile ("movq   64(%1), %0" : "=r" (dummy) : "r" (p));
                    asm volatile ("movq   2*64(%1), %0" : "=r" (dummy) : "r" (p));
                    asm volatile ("movq   3*64(%1), %0" : "=r" (dummy) : "r" (p));
                    asm volatile ("movq   4*64(%1), %0" : "=r" (dummy) : "r" (p));
            #endif
        }
        return;
    }

    if (bytes < 7*bw_cacheline_bytes) {
        // fully unroll the loop for small data sizes
        for (size_t r = 0; r < repetitions; r++) {
            size_t dummy;
            #ifdef __aarch64__
                    asm volatile ("ldr %0, [%1, #0]"     : "=r"(dummy) : "r"(p));
                    asm volatile ("ldr %0, [%1, 64]"    : "=r"(dummy)  : "r"(p));
                    asm volatile ("ldr %0, [%1, 2*64]"    : "=r"(dummy)  : "r"(p));
                    asm volatile ("ldr %0, [%1, 3*64]"    : "=r"(dummy)  : "r"(p));
                    asm volatile ("ldr %0, [%1, 4*64]"    : "=r"(dummy)  : "r"(p));
                    asm volatile ("ldr %0, [%1, 5*64]"    : "=r"(dummy)  : "r"(p));
            #endif
            #ifdef __x86_64__
                    asm volatile ("movq   (%1), %0" : "=r" (dummy)   : "r" (p));
                    asm volatile ("movq   64(%1), %0" : "=r" (dummy) : "r" (p));
                    asm volatile ("movq   2*64(%1), %0" : "=r" (dummy) : "r" (p));
                    asm volatile ("movq   3*64(%1), %0" : "=r" (dummy) : "r" (p));
                    asm volatile ("movq   4*64(%1), %0" : "=r" (dummy) : "r" (p));
                    asm volatile ("movq   5*64(%1), %0" : "=r" (dummy) : "r" (p));
            #endif
        }
        return;
    }

    if (bytes < 8*bw_cacheline_bytes) {
        // fully unroll the loop for small data sizes
        for (size_t r = 0; r < repetitions; r++) {
            size_t dummy;
            #ifdef __aarch64__
                    asm volatile ("ldr %0, [%1, #0]"     : "=r"(dummy) : "r"(p));
                    asm volatile ("ldr %0, [%1, 64]"    : "=r"(dummy)  : "r"(p));
                    asm volatile ("ldr %0, [%1, 2*64]"    : "=r"(dummy)  : "r"(p));
                    asm volatile ("ldr %0, [%1, 3*64]"    : "=r"(dummy)  : "r"(p));
                    asm volatile ("ldr %0, [%1, 4*64]"    : "=r"(dummy)  : "r"(p));
                    asm volatile ("ldr %0, [%1, 5*64]"    : "=r"(dummy)  : "r"(p));
                    asm volatile ("ldr %0, [%1, 6*64]"    : "=r"(dummy)  : "r"(p));

            #endif
            #ifdef __x86_64__
                    asm volatile ("movq   (%1), %0" : "=r" (dummy)   : "r" (p));
                    asm volatile ("movq   64(%1), %0" : "=r" (dummy) : "r" (p));
                    asm volatile ("movq   2*64(%1), %0" : "=r" (dummy) : "r" (p));
                    asm volatile ("movq   3*64(%1), %0" : "=r" (dummy) : "r" (p));
                    asm volatile ("movq   4*64(%1), %0" : "=r" (dummy) : "r" (p));
                    asm volatile ("movq   5*64(%1), %0" : "=r" (dummy) : "r" (p));
                    asm volatile ("movq   6*64(%1), %0" : "=r" (dummy) : "r" (p));
            #endif
        }
        return;
    }

    if (bytes < 9*bw_cacheline_bytes) {
        // fully unroll the loop for small data sizes
        for (size_t r = 0; r < repetitions; r++) {
            size_t dummy;
            #ifdef __aarch64__
                    asm volatile ("ldr %0, [%1, #0]"     : "=r"(dummy) : "r"(p));
                    asm volatile ("ldr %0, [%1, 64]"    : "=r"(dummy)  : "r"(p));
                    asm volatile ("ldr %0, [%1, 2*64]"    : "=r"(dummy)  : "r"(p));
                    asm volatile ("ldr %0, [%1, 3*64]"    : "=r"(dummy)  : "r"(p));
                    asm volatile ("ldr %0, [%1, 4*64]"    : "=r"(dummy)  : "r"(p));
                    asm volatile ("ldr %0, [%1, 5*64]"    : "=r"(dummy)  : "r"(p));
                    asm volatile ("ldr %0, [%1, 6*64]"    : "=r"(dummy)  : "r"(p));
                    asm volatile ("ldr %0, [%1, 7*64]"    : "=r"(dummy)  : "r"(p));
            #endif
            #ifdef __x86_64__
                    asm volatile ("movq   (%1), %0" : "=r" (dummy)   : "r" (p));
                    asm volatile ("movq   64(%1), %0" : "=r" (dummy) : "r" (p));
                    asm volatile ("movq   2*64(%1), %0" : "=r" (dummy) : "r" (p));
                    asm volatile ("movq   3*64(%1), %0" : "=r" (dummy) : "r" (p));
                    asm volatile ("movq   4*64(%1), %0" : "=r" (dummy) : "r" (p));
                    asm volatile ("movq   5*64(%1), %0" : "=r" (dummy) : "r" (p));
                    asm volatile ("movq   6*64(%1), %0" : "=r" (dummy) : "r" (p));
                    asm volatile ("movq   7*64(%1), %0" : "=r" (dummy) : "r" (p));
            #endif
        }
        return;
    }
    // fallthrough to the default loop handling big datasizes

    size_t main_stride = 8* bw_cacheline_bytes;
    char *main_end = (char *)p + (bytes / main_stride) * main_stride;
    char* p_end = (char *)p + bytes;
    for (size_t r = 0; r < repetitions; r++) {
        size_t dummy;
        for (char* i = p; i < main_end; i += main_stride) {
    #ifdef __aarch64__
            asm volatile ("ldr %0, [%1, #0]"     : "=r"(dummy) : "r"(i));
            asm volatile ("ldr %0, [%1, 64]"    : "=r"(dummy)  : "r"(i));
            asm volatile ("ldr %0, [%1, 2*64]"    : "=r"(dummy)  : "r"(i));
            asm volatile ("ldr %0, [%1, 3*64]"    : "=r"(dummy)  : "r"(i));
            asm volatile ("ldr %0, [%1, 4*64]"    : "=r"(dummy)  : "r"(i));
            asm volatile ("ldr %0, [%1, 5*64]"    : "=r"(dummy)  : "r"(i));
            asm volatile ("ldr %0, [%1, 6*64]"    : "=r"(dummy)  : "r"(i));
            asm volatile ("ldr %0, [%1, 7*64]"    : "=r"(dummy)  : "r"(i));
    #endif
    #ifdef __x86_64__
            asm volatile ("movq   (%1), %0" : "=r" (dummy)   : "r" (i));
            asm volatile ("movq   64(%1), %0" : "=r" (dummy) : "r" (i));
            asm volatile ("movq   2*64(%1), %0" : "=r" (dummy) : "r" (i));
            asm volatile ("movq   3*64(%1), %0" : "=r" (dummy) : "r" (i));
            asm volatile ("movq   4*64(%1), %0" : "=r" (dummy) : "r" (i));
            asm volatile ("movq   5*64(%1), %0" : "=r" (dummy) : "r" (i));
            asm volatile ("movq   6*64(%1), %0" : "=r" (dummy) : "r" (i));
            asm volatile ("movq   7*64(%1), %0" : "=r" (dummy) : "r" (i));
    #endif
        }
        // tail loop
        for (char* i=main_end ; i < p_end; i += bw_cacheline_bytes) {
    #ifdef __aarch64__
            asm volatile ("ldr %0, [%1, #0]"     : "=r"(dummy) : "r"(i));
    #endif
    #ifdef __x86_64__
            asm volatile ("movq   (%1), %0" : "=r" (dummy) : "r" (i));
    #endif
        }
    }
}
__attribute__((noinline))
static void my_read_no_nops_rep(void * p, size_t bytes, size_t bw_cacheline_bytes, uint64_t repetitions) {
    // check for smaller loops first as they are more sensitive to extra control instructions
    if (bytes < 2*bw_cacheline_bytes) {
        // fully unroll the loop for small data sizes
        for (size_t r = 0; r < repetitions; r++) {
            size_t dummy;
            #ifdef __aarch64__
                    asm volatile ("ldr %0, [%1, #0]"     : "=r"(dummy) : "r"(p));
            #endif
            #ifdef __x86_64__
                    asm volatile ("movq   (%1), %0" : "=r" (dummy) : "r" (p));
            #endif
        }
        return;
    }

    size_t offset1 = 1 * bw_cacheline_bytes;
    if (bytes < 3*bw_cacheline_bytes) {
        // fully unroll the loop for small data sizes
        for (size_t r = 0; r < repetitions; r++) {
            size_t dummy;
            #ifdef __aarch64__
                    asm volatile ("ldr %0, [%1, #0]"     : "=r"(dummy) : "r"(p));
                    asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(p), "r"(offset1));
            #endif
            #ifdef __x86_64__
                    asm volatile ("movq   (%1), %0" : "=r" (dummy) : "r" (p));
                    asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (p), "r"(offset1));
            #endif
        }
        return;
    }

    size_t offset2 = 2 * bw_cacheline_bytes;
    if (bytes < 4*bw_cacheline_bytes) {
        // fully unroll the loop for small data sizes
        for (size_t r = 0; r < repetitions; r++) {
            size_t dummy;
            #ifdef __aarch64__
                    asm volatile ("ldr %0, [%1, #0]"     : "=r"(dummy) : "r"(p));
                    asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(p), "r"(offset1));
                    asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(p), "r"(offset2));
            #endif
            #ifdef __x86_64__
                    asm volatile ("movq   (%1), %0" : "=r" (dummy) : "r" (p));
                    asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (p), "r"(offset1));
                    asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (p), "r"(offset2));
            #endif
        }
        return;
    }

    size_t offset3 = 3 * bw_cacheline_bytes;
    if (bytes < 5*bw_cacheline_bytes) {
        // fully unroll the loop for small data sizes
        for (size_t r = 0; r < repetitions; r++) {
            size_t dummy;
            #ifdef __aarch64__
                    asm volatile ("ldr %0, [%1, #0]"     : "=r"(dummy) : "r"(p));
                    asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(p), "r"(offset1));
                    asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(p), "r"(offset2));
                    asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(p), "r"(offset3));
            #endif
            #ifdef __x86_64__
                    asm volatile ("movq   (%1), %0" : "=r" (dummy) : "r" (p));
                    asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (p), "r"(offset1));
                    asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (p), "r"(offset2));
                    asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (p), "r"(offset3));
            #endif
        }
        return;
    }

    size_t offset4 = 4 * bw_cacheline_bytes;
    if (bytes < 6*bw_cacheline_bytes) {
        // fully unroll the loop for small data sizes
        for (size_t r = 0; r < repetitions; r++) {
            size_t dummy;
            #ifdef __aarch64__
                    asm volatile ("ldr %0, [%1, #0]"     : "=r"(dummy) : "r"(p));
                    asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(p), "r"(offset1));
                    asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(p), "r"(offset2));
                    asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(p), "r"(offset3));
                    asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(p), "r"(offset4));
            #endif
            #ifdef __x86_64__
                    asm volatile ("movq   (%1), %0" : "=r" (dummy) : "r" (p));
                    asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (p), "r"(offset1));
                    asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (p), "r"(offset2));
                    asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (p), "r"(offset3));
                    asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (p), "r"(offset4));
            #endif
        }
        return;
    }

    size_t offset5 = 5 * bw_cacheline_bytes;
    if (bytes < 7*bw_cacheline_bytes) {
        // fully unroll the loop for small data sizes
        for (size_t r = 0; r < repetitions; r++) {
            size_t dummy;
            #ifdef __aarch64__
                    asm volatile ("ldr %0, [%1, #0]"     : "=r"(dummy) : "r"(p));
                    asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(p), "r"(offset1));
                    asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(p), "r"(offset2));
                    asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(p), "r"(offset3));
                    asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(p), "r"(offset4));
                    asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(p), "r"(offset5));
            #endif
            #ifdef __x86_64__
                    asm volatile ("movq   (%1), %0" : "=r" (dummy) : "r" (p));
                    asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (p), "r"(offset1));
                    asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (p), "r"(offset2));
                    asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (p), "r"(offset3));
                    asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (p), "r"(offset4));
                    asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (p), "r"(offset5));
            #endif
        }
        return;
    }

    size_t offset6 = 6 * bw_cacheline_bytes;
    if (bytes < 8*bw_cacheline_bytes) {
        // fully unroll the loop for small data sizes
        for (size_t r = 0; r < repetitions; r++) {
            size_t dummy;
            #ifdef __aarch64__
                    asm volatile ("ldr %0, [%1, #0]"     : "=r"(dummy) : "r"(p));
                    asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(p), "r"(offset1));
                    asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(p), "r"(offset2));
                    asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(p), "r"(offset3));
                    asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(p), "r"(offset4));
                    asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(p), "r"(offset5));
                    asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(p), "r"(offset6));
            #endif
            #ifdef __x86_64__
                    asm volatile ("movq   (%1), %0" : "=r" (dummy) : "r" (p));
                    asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (p), "r"(offset1));
                    asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (p), "r"(offset2));
                    asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (p), "r"(offset3));
                    asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (p), "r"(offset4));
                    asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (p), "r"(offset5));
                    asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (p), "r"(offset6));
            #endif
        }
        return;
    }

    size_t offset7 = 7 * bw_cacheline_bytes;
    if (bytes < 9*bw_cacheline_bytes) {
        // fully unroll the loop for small data sizes
        for (size_t r = 0; r < repetitions; r++) {
            size_t dummy;
            #ifdef __aarch64__
                    asm volatile ("ldr %0, [%1, #0]"     : "=r"(dummy) : "r"(p));
                    asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(p), "r"(offset1));
                    asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(p), "r"(offset2));
                    asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(p), "r"(offset3));
                    asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(p), "r"(offset4));
                    asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(p), "r"(offset5));
                    asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(p), "r"(offset6));
                    asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(p), "r"(offset7));
            #endif
            #ifdef __x86_64__
                    asm volatile ("movq   (%1), %0" : "=r" (dummy) : "r" (p));
                    asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (p), "r"(offset1));
                    asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (p), "r"(offset2));
                    asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (p), "r"(offset3));
                    asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (p), "r"(offset4));
                    asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (p), "r"(offset5));
                    asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (p), "r"(offset6));
                    asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (p), "r"(offset7));
            #endif
        }
        return;
    }
    // fallthrough to the default loop handling big datasizes

    size_t main_stride = 8* bw_cacheline_bytes;
    char *main_end = (char *)p + (bytes / main_stride) * main_stride;
    char* p_end = (char *)p + bytes;
    for (size_t r = 0; r < repetitions; r++) {
        size_t dummy;
        for (char* i = p; i < main_end; i += main_stride) {
    #ifdef __aarch64__
            asm volatile ("ldr %0, [%1, #0]"     : "=r"(dummy) : "r"(i));
            asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(i), "r"(offset1));
            asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(i), "r"(offset2));
            asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(i), "r"(offset3));
            asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(i), "r"(offset4));
            asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(i), "r"(offset5));
            asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(i), "r"(offset6));
            asm volatile ("ldr %0, [%1, %2]"    : "=r"(dummy) : "r"(i), "r"(offset7));
    #endif
    #ifdef __x86_64__
            asm volatile ("movq   (%1), %0" : "=r" (dummy) : "r" (i));
            asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (i), "r"(offset1));
            asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (i), "r"(offset2));
            asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (i), "r"(offset3));
            asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (i), "r"(offset4));
            asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (i), "r"(offset5));
            asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (i), "r"(offset6));
            asm volatile ("movq   (%1,%2), %0" : "=r" (dummy) : "r" (i), "r"(offset7));
    #endif
        }
        // tail loop
        for (char* i=main_end ; i < p_end; i += bw_cacheline_bytes) {
    #ifdef __aarch64__
            asm volatile ("ldr %0, [%1, #0]"     : "=r"(dummy) : "r"(i));
    #endif
    #ifdef __x86_64__
            asm volatile ("movq   (%1), %0" : "=r" (dummy) : "r" (i));
    #endif
        }
    }
}
#endif // ASCT


/* my_write() provides a variable write bandwidth.
   Increasing inner_nops lowers the write bandwidth. */

#ifndef ASCT
static void my_write(void * p, size_t bytes, size_t inner_nops, size_t bw_cacheline_bytes)
    __attribute__((noinline));
static void my_write(void * p, size_t bytes, size_t inner_nops, size_t bw_cacheline_bytes) {

// uncomment the next line to use DC ZVA instructions to do writes
//#define USE_DCZVA

#if defined(__aarch64__) && defined(USE_DCZVA)
    // this just writes one 64-bit dword from each cache line, but is slower.
    for (char * i = p; i < ((char *)p)+bytes; i += bw_cacheline_bytes) {
        asm volatile ("dc zva, %0" : : "r" (i));
#elif defined(__aarch64__) && !defined(USE_DCZVA)
    size_t dummy=0;
    for (size_t i = 0; i < bytes; i += bw_cacheline_bytes) {
        asm volatile ("str %0, [%1, %2]" : : "r" (dummy), "r" (p), "r" (i));
#elif defined(__x86_64__)
    size_t dummy=0;
    for (size_t i = 0; i < bytes; i += bw_cacheline_bytes) {
        // warning untested
        asm volatile ("movq   %0, (%1,%2,1)" : : "r" (dummy), "r" (p), "r" (i));
#endif
        for (size_t j = 0; j < inner_nops; j++) {
            asm volatile ("");
        }
    }
}
#else // ASCT version, no need to add noop loop
__attribute__((noinline))
static void my_write_no_nops(void * p, size_t bytes, size_t bw_cacheline_bytes) {

// uncomment the next line to use DC ZVA instructions to do writes
//#define USE_DCZVA

#if defined(__aarch64__) && defined(USE_DCZVA)
    // this just writes one 64-bit dword from each cache line, but is slower.
    for (char * i = p; i < ((char *)p)+bytes; i += bw_cacheline_bytes) {
        asm volatile ("dc zva, %0" : : "r" (i));
#elif defined(__aarch64__) && !defined(USE_DCZVA)
    size_t dummy=0;
    for (size_t i = 0; i < bytes; i += bw_cacheline_bytes) {
        asm volatile ("str %0, [%1, %2]" : : "r" (dummy), "r" (p), "r" (i));
#elif defined(__x86_64__)
    size_t dummy=0;
    for (size_t i = 0; i < bytes; i += bw_cacheline_bytes) {
        // warning untested
        asm volatile ("movq   %0, (%1,%2,1)" : : "r" (dummy), "r" (p), "r" (i));
#endif
    }
}
__attribute__((noinline))
static void my_readwrite_3_1_no_nops(void* pr, void * pw, size_t bytes, size_t bw_cacheline_bytes) {

// uncomment the next line to use DC ZVA instructions to do writes
//#define USE_DCZVA
    size_t dummy_r=0;

#if defined(__aarch64__) && defined(USE_DCZVA)
    char* j = pr;
    // warning untested for ASCT
    // this just writes one 64-bit dword from each cache line, but is slower.
    for (char * i = pw; i < ((char *)pw)+bytes; i += bw_cacheline_bytes) {
        asm volatile ("ldr %0, [%1]" : "=r" (dummy_r): "r" (j));
        j += bw_cacheline_bytes;
        asm volatile ("ldr %0, [%1]" : "=r" (dummy_r): "r" (j));
        j += bw_cacheline_bytes;
        asm volatile ("dc zva, %0" : : "r" (i));
#elif defined(__aarch64__) && !defined(USE_DCZVA)
    int j = 0;
    size_t dummy=0;
    for (size_t i = 0; i < bytes; i += bw_cacheline_bytes) {
        asm volatile ("ldr %0, [%1, %2]" : "=r" (dummy_r): "r" (pr), "r" (j));
        j += bw_cacheline_bytes;
        asm volatile ("ldr %0, [%1, %2]" : "=r" (dummy_r): "r" (pr), "r" (j));
        j += bw_cacheline_bytes;
        asm volatile ("str %0, [%1, %2]" : : "r" (dummy), "r" (pw), "r" (i));
#elif defined(__x86_64__)
    size_t j = 0;
    size_t dummy=0;
    for (size_t i = 0; i < bytes; i += bw_cacheline_bytes) {
        // warning untested
        asm volatile ("movq   (%1,%2,1), %0" : "=r" (dummy_r) : "r" (pr), "r" (j));
        j += bw_cacheline_bytes;
        asm volatile ("movq   (%1,%2,1), %0" : "=r" (dummy_r) : "r" (pr), "r" (j));
        j += bw_cacheline_bytes;
        asm volatile ("movq   %0, (%1,%2,1)" : : "r" (dummy), "r" (pw), "r" (i));
#endif
    }
}
__attribute__((noinline))
static void my_readwrite_2_1_no_nops(void* pr, void * pw, size_t bytes, size_t bw_cacheline_bytes) {

// uncomment the next line to use DC ZVA instructions to do writes
//#define USE_DCZVA
    size_t dummy_r=0;

#if defined(__aarch64__) && defined(USE_DCZVA)
    char* j = pr;
    // warning untested for ASCT
    // this just writes one 64-bit dword from each cache line, but is slower.
    for (char * i = pw; i < ((char *)pw)+bytes; i += bw_cacheline_bytes) {
        asm volatile ("ldr %0, [%1]" : "=r" (dummy_r): "r" (j));
        j += bw_cacheline_bytes;
        asm volatile ("dc zva, %0" : : "r" (i));
#elif defined(__aarch64__) && !defined(USE_DCZVA)
    size_t dummy=0;
    for (size_t i = 0; i < bytes; i += bw_cacheline_bytes) {
        asm volatile ("ldr %0, [%1, %2]" : "=r" (dummy_r): "r" (pr), "r" (i));
        asm volatile ("str %0, [%1, %2]" : : "r" (dummy), "r" (pw), "r" (i));
#elif defined(__x86_64__)
    size_t dummy=0;
    for (size_t i = 0; i < bytes; i += bw_cacheline_bytes) {
        // warning untested
        asm volatile ("movq   (%1,%2,1), %0" : "=r" (dummy_r) : "r" (pr), "r" (i));
        asm volatile ("movq   %0, (%1,%2,1)" : : "r" (dummy), "r" (pw), "r" (i));
#endif
    }
}
#if NT_STORE_AVAILABLE
__attribute__((noinline))
static void my_readwrite_2_1_nt_store_no_nops(void* pr, void* pr1, void * pw, size_t bytes, size_t bw_cacheline_bytes
#if defined(__aarch64__) && defined(HAS_SVE)
    ,size_t vl_bytes
#endif
) {
    size_t dummy_r=0;

#if defined(__aarch64__) 
    #if defined(HAS_SVE)
    // Set all lanes of z0.s to zero
    asm volatile ( "dup z0.s, #0" ::: "z0");
    asm volatile ( "ptrue p0.s" ::: "p0");
    for (size_t j = 0; j < bytes; j += bw_cacheline_bytes) {
        asm volatile ("ldr %0, [%1, %2]" : "=r" (dummy_r): "r" (pr), "r" (j));
        asm volatile ("ldr %0, [%1, %2]" : "=r" (dummy_r): "r" (pr1), "r" (j));

        for (size_t k = 0; k < bw_cacheline_bytes; k += vl_bytes) {
            asm volatile ("stnt1w z0.s, p0, [%0]" : : "r" (pw+j+k) : "z0", "p0", "memory");
        }
    }
    #else
        // SVE unavailable, error condition
        printf("Error: trying to run nt_store without SVE support\n");
        exit(-1);
    #endif

#elif defined(__x86_64__)
    size_t dummy=0;
    for (size_t i = 0; i < bytes; i += bw_cacheline_bytes) {
        asm volatile ("movq   (%1,%2,1), %0" : "=r" (dummy_r) : "r" (pr), "r" (i));
        asm volatile ("movq   (%1,%2,1), %0" : "=r" (dummy_r) : "r" (pr1), "r" (i));
        // Use a loop to write whole cache line to avoid partial writes 
        // causing cache line reads.
        for (size_t wi = i; wi < i+bw_cacheline_bytes; wi += sizeof(dummy)) {
            asm volatile ("movnti %0, (%1,%2,1)" : : "r" (dummy), "r" (pw), "r" (wi));
        }
    }
#endif
}
#endif /* NT_STORE_AVAILABLE */
#endif /* ifndef ASCT */

#ifdef ASCT
static void trial_run(int bw_write, void * mem, void * mem_r, void* mem_r1, void * mem_w,
    size_t buflen, size_t part_size, size_t bw_cacheline_bytes, size_t inner_nops
#if defined(__aarch64__) && defined(HAS_SVE)
    , size_t vl_bytes
#endif
) {
    switch (bw_write) {
        case READ_ONLY:
            if (inner_nops > 0) {
                my_read(mem, buflen, inner_nops, bw_cacheline_bytes);
            } else {
                my_read_no_nops(mem, buflen, bw_cacheline_bytes);
            }
        break;
        case WRITE_ONLY:
            my_write_no_nops(mem, buflen, bw_cacheline_bytes);
        break;
        case READ_WRITE_3_1:
            my_readwrite_3_1_no_nops(mem_r, mem_w, part_size, bw_cacheline_bytes);
        break;
        case READ_WRITE_2_1:
            my_readwrite_2_1_no_nops(mem_r, mem_w, part_size, bw_cacheline_bytes);
        break;
        case READ_WRITE_1_1:
            // The same as running WRITE_ONLY
            my_write_no_nops(mem, buflen, bw_cacheline_bytes);
        break;
#if NT_STORE_AVAILABLE
        case READ_WRITE_2_1_NT_STORE:
#if defined(__aarch64__) && defined(HAS_SVE)
            my_readwrite_2_1_nt_store_no_nops(mem_r, mem_r1, mem_w, part_size, bw_cacheline_bytes, vl_bytes);
#else
            my_readwrite_2_1_nt_store_no_nops(mem_r, mem_r1, mem_w, part_size, bw_cacheline_bytes);
#endif
        break;
#endif
        default:
            // Should not happen
            printf("Unexpected bw_write value %d in trial_run\n", bw_write);
            exit(-1);
    }
}
#endif


void bandwidth_thread (struct bw_thread_info * bw_tinfo) {
    size_t buflen           = bw_tinfo->bw_buflen;
    size_t inner_nops       = bw_tinfo->inner_nops;
    size_t outer_nops       = bw_tinfo->outer_nops;

    size_t iterations       = bw_tinfo->iterations;
    int thread_num          = bw_tinfo->thread_num;
    int cpu                 = bw_tinfo->cpu;                /* cpu on which this thread is to run */
    int bw_write            = bw_tinfo->bw_write;

    unsigned long hwcounter_start = bw_tinfo->hwcounter_start;
#ifdef ASCT
    uint64_t repetitions            = bw_tinfo->repetitions;
#endif
    unsigned long hwcounter_stop  = bw_tinfo->hwcounter_stop;

    size_t bw_cacheline_bytes     = bw_tinfo->bw_cacheline_bytes;

    int bw_use_hugepages    = bw_tinfo->bw_use_hugepages;

    unsigned long start_tick, stop_tick, tickdiff;
    double avg_bw = 0.0;
#ifdef ASCT
    double avg_bw_bpc = 0.0;
#endif
    double cntfreq = (double) read_cntfreq();
    unsigned long bw_samples = 0;

    printf("CPU%d BWTHREAD%d: buflen = %zu, iterations = %zu, inner_nops = %zu, outer_nops = %zu, hwcounter_start = 0x%zx, bw_cacheline_bytes = %zu, bw_use_hugepages = %d, tid = %d\n",
           cpu, thread_num, buflen, iterations, inner_nops, outer_nops, hwcounter_start, bw_cacheline_bytes, bw_use_hugepages, gettid());

    void * mem = do_alloc(buflen, bw_use_hugepages, sysconf(_SC_PAGESIZE));

    // synchronize thread start at the specified HW timer value
    while ((start_tick = read_hwcounter()) < hwcounter_start) {
        ;
    }

    bw_tinfo->actual_hwcounter_start = start_tick;

    printf("CPU%d BWTHREAD%d: started at " HWCOUNTER " = 0x%zx\n", cpu, thread_num, start_tick);

#ifndef ASCT
    while ((start_tick = stop_tick = read_hwcounter()) < hwcounter_stop) {

        for (size_t i = 0; i < iterations; i++) {
            if (bw_write) {
                my_write((void *) (((char *) mem)), buflen, inner_nops, bw_cacheline_bytes);
            } else {
                my_read((void *) (((char *) mem)), buflen, inner_nops, bw_cacheline_bytes);
            }
            for (size_t j = 0; j < outer_nops; j++) {
                asm volatile ("");
            }
        }

        stop_tick = read_hwcounter();
        tickdiff = stop_tick - start_tick;

        double bw = iterations * buflen / (tickdiff / cntfreq);

        avg_bw += bw;
        bw_samples++;

        bw /= 1e6;  // MB, not MiB

        printf("CPU%d BWTHREAD%d: %f MB/sec\n", cpu, thread_num, bw);

    }
#else // ASCT version is essentailly doing the same as original version but have a duration determined by repetitions
    // ASCT will go ahead to run the loop for fixed repetitions
    const int n = 3;
    void* parts[n];
    void* mem_r = NULL;
    void* mem_r1 = NULL;
    void* mem_w = NULL;
    size_t part_size = 0;
#if defined(__aarch64__) && defined(HAS_SVE)
    size_t vl_bytes = svcntb();
#endif

    switch (bw_write) {
        case READ_WRITE_2_1:
        // One read stream and one write stream striding the parition in the same manner
        part_size = partition_n_aligned_memory(mem, buflen, 2, sysconf(_SC_PAGESIZE), &parts[0]);
        mem_r = parts[0];
        mem_w = parts[1];
        parts[2] = NULL;
        break;

#if NT_STORE_AVAILABLE
        case READ_WRITE_2_1_NT_STORE:
    #if defined(__aarch64__) 
        #if defined(HAS_SVE)
        // First check whether the vector length is compatible with the cacheline size
        if (bw_cacheline_bytes % vl_bytes != 0) {
            printf("Error: cacheline size %zu is not multiple of SVE vector length %zu\n", bw_cacheline_bytes, 
                vl_bytes);
            exit(-1);
        }
        #else
        // SVE unavailable, error condition
        printf("Error: trying to run nt_store without SVE support\n");
        exit(-1);
        #endif
    #elif defined(__x86_64__)
        // For x86 version, data element size is size_t.
        if (bw_cacheline_bytes % sizeof(size_t) != 0) {
            printf("Error: cacheline size %zu is not multiple of element size %zu\n", bw_cacheline_bytes, 
                sizeof(size_t));
            exit(-1);
        }
    #endif
        // for READ_WRITE_2_1_NT_STORE, there are two read streams and one write stream,
        // so we need to partition the memory into 3 parts, two partitions for read and one partition for write
        // similar to READ_WRITE_3_1 (see below), so fall through to that case
#endif
        case READ_WRITE_3_1:
        // for READ_WRITE_3_1, there are one read stream and one write stream but the read stream will access double amount
        // of data than the write stream, 
        // so we need to partition the memory into 3 parts, two partitions for read and one partition for write
        // In summary:
        //  READ_WRTE_3_1: R R W
        //  READ_WRITE_2_1_NT_STORE: R1 R2 W
        part_size = partition_n_aligned_memory(mem, buflen, 3, sysconf(_SC_PAGESIZE), &parts[0]);
        mem_r = parts[0];
        mem_r1 = parts[1];  // mem_r1 not used by READ_WRITE_3_1
        mem_w = parts[2];
        break;
        default:
        // fall through for other cases
        ;
    }

    // Add trial run phase
#if defined(__aarch64__) && defined(HAS_SVE)
    trial_run(bw_write, mem, mem_r, mem_r1, mem_w, buflen, part_size, bw_cacheline_bytes, inner_nops, vl_bytes) ;
#else
    trial_run(bw_write, mem, mem_r, mem_r1, mem_w, buflen, part_size, bw_cacheline_bytes, inner_nops) ;
#endif
    unsigned long run_duration_tick = hwcounter_stop - hwcounter_start;
    repetitions = 0;
    size_t this_now = read_hwcounter();
    size_t end_tick = this_now + run_duration_tick;
    while (1) {
        repetitions++;
#if defined(__aarch64__) && defined(HAS_SVE)
        trial_run(bw_write, mem, mem_r, mem_r1, mem_w, buflen, part_size, bw_cacheline_bytes, inner_nops, vl_bytes);
#else
        trial_run(bw_write, mem, mem_r, mem_r1, mem_w, buflen, part_size, bw_cacheline_bytes, inner_nops);
#endif
        if (read_hwcounter() >= end_tick) {
            break;
        }
    }
    // recorded number of repetitions for target time, now will update the shared variable at least as large as
    // the current repetitions
    uint64_t _repetitions;
    do {
        _repetitions = atomic_load(bw_tinfo->_repetitions);
    } while(repetitions > _repetitions
            && !atomic_compare_exchange_weak(bw_tinfo->_repetitions, &_repetitions, repetitions));

    int rc = pthread_barrier_wait(bw_tinfo->barrier);
    if (rc != 0) {
        if (rc == PTHREAD_BARRIER_SERIAL_THREAD) {
            // reset the following start flag to busy waiting loop below to restart
            atomic_store_explicit(bw_tinfo->arrival_count, 0, memory_order_release);
        } else {
            // Error condition
            printf("Error: pthread_barrier_wait failed with code %d\n", rc);
            exit(-1);
        }
    }

    pthread_barrier_wait(bw_tinfo->barrier);
    // all threads update the bwthinfo->_repetitions if their repetitions is larger, so we can load the max
    repetitions = atomic_load(bw_tinfo->_repetitions);
    // use the count to track how many threads passed the barrier and ready to start
    atomic_fetch_add_explicit(bw_tinfo->arrival_count, 1, memory_order_acq_rel);
    while (atomic_load_explicit(bw_tinfo->arrival_count, memory_order_acquire) < bw_tinfo->total_num_threads) {
        // busy wait until all threads are ready
    }

    if (repetitions <= 0) {
        printf("CPU%d BWTHREAD%d: ERROR: repetitions not positive\n", cpu, thread_num);
        exit(-1);
    }
    
    start_tick = read_hwcounter();

#ifdef USE_PROBE
    int ret;
    struct dietperf_ctx ctx = {0};
    ret = dietperf_parse_evlist(&ctx);
    if (ret)
        exit(ret);
    ret = dietperf_init(&ctx);
    if (ret)
        exit(ret);
    ret = dietperf_set_outdir(&ctx, NULL);
    if (ret)
        exit(ret);
    ret = dietperf_start(&ctx);
    if (ret)
        exit(ret);
#endif

    size_t footprint_per_repetition = 0;
    switch (bw_write) {
        case READ_ONLY:
        if (inner_nops > 0) {
            for (size_t i = 0; i < repetitions; i++) {
                my_read(mem, buflen, inner_nops, bw_cacheline_bytes);
            }
        } else {
            // this is replaced by one function with smaller loop control overhead handling small datasizes better
            // while still keep the DRAM results the same.
            if (bw_cacheline_bytes == 64) {
                // use specialized version for 64b cacheliine (which is a common case).  It is observed to have
                // higher saturation for some system than the general one below (my_read_no_nops_rep()).
                my_read_no_nops_rep_64b(mem, buflen, repetitions);
            } else {
                my_read_no_nops_rep(mem, buflen, bw_cacheline_bytes, repetitions);
            }
        }
        printf("RO iter(tid=%d): %lu, %lu\n", gettid(), buflen, buflen*repetitions);
        footprint_per_repetition = buflen; // Read traffic spanning buflen
        break;
        case WRITE_ONLY:
        for (size_t i = 0; i < repetitions; i++) {
            my_write_no_nops(mem, buflen, bw_cacheline_bytes);
        }
        printf("WO iter: %lu\n", buflen);
        footprint_per_repetition = 2 * buflen; // Read and write traffic spanning buflen
        break;
        case READ_WRITE_3_1:
        for (size_t i = 0; i < repetitions; i++) {
            my_readwrite_3_1_no_nops(mem_r, mem_w, part_size, bw_cacheline_bytes);
        }
        printf("3:1 iter: %lu\n", part_size);
        footprint_per_repetition = 4 * part_size; // 3 Read and 1 write traffic spanning part_size
        break;
        case READ_WRITE_2_1:
        for (size_t i = 0; i < repetitions; i++) {
            my_readwrite_2_1_no_nops(mem_r, mem_w, part_size, bw_cacheline_bytes);
        }
        printf("2:1 iter: %lu\n", part_size);
        footprint_per_repetition = 3 * part_size; // 2 Read and 1 write traffic spanning part_size
        break;
        case READ_WRITE_1_1:
        for (size_t i = 0; i < repetitions; i++) {
            // The same as running WRITE_ONLY
            my_write_no_nops(mem, buflen, bw_cacheline_bytes);
        }
        printf("1:1 iter: %lu\n", buflen);
        footprint_per_repetition = 2 * buflen; // Read and 1 write traffic spanning part_size
        break;
#if NT_STORE_AVAILABLE
        case READ_WRITE_2_1_NT_STORE:
#if defined(__aarch64__) && defined(HAS_SVE)
        for (size_t i = 0; i < repetitions; i++) {
            my_readwrite_2_1_nt_store_no_nops(mem_r, mem_r1, mem_w, part_size, bw_cacheline_bytes, vl_bytes);
        }
#else
        for (size_t i = 0; i < repetitions; i++) {
            my_readwrite_2_1_nt_store_no_nops(mem_r, mem_r1, mem_w, part_size, bw_cacheline_bytes);
        }
#endif
        printf("2:1 non-temporal store iter: %lu\n", part_size);
        footprint_per_repetition =  3 * part_size; // 2 Read and 1 write traffic spanning part_size
        break;
#endif
        default:
            // Should not happen
            printf("Unexpected bw_write value %d in bandwidth_thread\n", bw_write);
            exit(-1);
    }
    // ASCT runs will not do outer nop loop
#ifdef USE_PROBE
    ret = dietperf_stop(&ctx);
    if (ret)
        exit(ret);
    ret = dietperf_write(&ctx);
    if (ret)
        exit(ret);
    ret = dietperf_destroy(&ctx);
    if (ret)
        exit(ret);
#endif
    stop_tick = read_hwcounter();
    tickdiff = stop_tick - start_tick;
    //double bw = repetitions * fp_buflen_times_cntfreq / tickdiff;
    double bw = repetitions * footprint_per_repetition * cntfreq / tickdiff;
    double bw_bpc = (double)(repetitions * footprint_per_repetition) / (double)tickdiff; // bytes per cycle
    printf("tid = %d, repetitions = %lu, tickdiff = %lu, time = %f\n", gettid(), repetitions, tickdiff,
        (double)tickdiff / cntfreq);
    avg_bw = bw;
    avg_bw_bpc = bw_bpc;
    bw_samples=1;
    bw /= 1e6;  // MB, not MiB
    // For ASCT, we don't try to adjust the inner_nops to reach the target bandwidth, so no more code here
    int did_proportional = 1;  // taking the value of the condition when first is true
    printf("CPU%-3d BWTHREAD%-3d: %5.f MB/sec, inner_nops = %-4lu -> %-4lu %s\n",
            cpu, thread_num, bw, 0UL, 0UL, did_proportional ? "did_proportional" : "");
#endif // ASCT

    bw_tinfo->actual_hwcounter_stop = stop_tick;

    avg_bw /= bw_samples;

    bw_tinfo->avg_bw = avg_bw;
#ifdef ASCT
    bw_tinfo->avg_bw_bpc = avg_bw_bpc;
#endif
}
