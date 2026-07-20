
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
#include <math.h>

#include <sys/time.h>
#include <sys/types.h>

#include <sys/mman.h>
#include <linux/mman.h>

#ifdef __aarch64__
#include "cntvct.h"
#endif

#ifdef __x86_64__
#include "rdtsc.h"
#endif

#include "alloc.h"
#include "memlatency.h"
#ifdef ASCT
#include <stdatomic.h>
#ifdef USE_PROBE
#include "dietperf.h"
#endif
#endif

/* lat_initialize can be called from main.c for shared memory */

void ** lat_initialize(size_t cacheline_bytes,
    size_t cacheline_count, int randomize, int clear_cache, size_t cacheline_stride, int use_hugepages) {

    size_t i;

    typedef struct {
        void * next;
        size_t order;
        size_t index;
        char buf[cacheline_bytes - sizeof(void *) - sizeof(size_t) - sizeof(size_t)];
    } node_t;

    // check that sizeof(node_t) == cacheline_bytes // XXX: might not be on 32-bit
    if (sizeof(node_t) != cacheline_bytes) {
        printf("in lat_setup, sizeof(node_t) = %zu, does not equal cacheline_bytes = %zu\n",
            sizeof(node_t), cacheline_bytes);
        exit(-1);
    }

    if (cacheline_bytes % sizeof(void*)) {
        printf("cacheline_bytes = %zu, is not an exact multiple of sizeof(void*) = %zu\n", cacheline_bytes, sizeof(void*));
        exit(-1);
    }

    node_t * p = do_alloc(cacheline_bytes * cacheline_count, use_hugepages, cacheline_bytes);

    // order is the sequence of node_t elements to traverse.  Initialize for sequential order.

    for (i = 0; i < cacheline_count; i++) {
        p[i].order = i;
    }

    // if randomize is used, randomly swap the order values

    if (randomize) {
        for (int rounds = 0; rounds < 10; rounds++) {
            for (i = 0; i < cacheline_count; i+= cacheline_stride) {
                size_t offset_a, offset_b, x;

                do {
                    offset_a = (lrand48() % (cacheline_count/cacheline_stride)) * cacheline_stride;
                    offset_b = (lrand48() % (cacheline_count/cacheline_stride)) * cacheline_stride;
                } while (offset_a == offset_b);

                x = p[offset_a].order;
                p[offset_a].order = p[offset_b].order;
                p[offset_b].order = x;
            }
        }
    }

    // create the pointer loop using the ordering table

    for (i = 0; i < cacheline_count - cacheline_stride; i += cacheline_stride) {
        p[p[i].order].next = &(p[p[i + cacheline_stride].order].next);
        p[p[i].order].index = i;
    }

    p[p[i].order].next = &(p[p[0].order].next);
    p[p[i].order].index = i;

#if 0
    // print out latency loop pointers for debug
    printf("by pointer:\n");
    node_t * pp = (node_t *) ppvoid;
    for (i = 0; i < cacheline_count; i++) {
        printf("%zu\tpp=%p pp->next=%p delta=%ld bytes\n", i, pp, pp->next, (long) pp->next - (long) pp );
        pp = pp->next;
    }

    printf("by entry:\n");
    pp = (node_t *) ppvoid;
    for (i = 0; i < cacheline_count; i++) {
        printf("pp[%zu]\t= %p, .next=%p\n", i, &(pp[i]), pp[i].next);
    }
#endif

    if (clear_cache) {
        __builtin___clear_cache(p, p+cacheline_count);
    }

    return (void **) p;
}


static void ** run(void ** p, size_t iterations) __attribute__((noinline));
static void ** run(void ** p, size_t iterations) {

#ifdef DO_DUMMY1
    size_t dummy1;
#define DUMMY1 asm volatile ("ldr %0, [%1, #8]" : "=r" (dummy1) : "r" (p));
#else
#define DUMMY1
#endif

#ifdef DO_DUMMY2
    size_t dummy2;
#define DUMMY2 asm volatile ("ldr %0, [%1, #16]" : "=r" (dummy2) : "r" (p));
#else
#define DUMMY2
#endif

    for (size_t i = 0; i < iterations; i++) {

        p = (void **) (*p); DUMMY1;  DUMMY2;
        p = (void **) (*p); DUMMY1;  DUMMY2;
        p = (void **) (*p); DUMMY1;  DUMMY2;
        p = (void **) (*p); DUMMY1;  DUMMY2;
        p = (void **) (*p); DUMMY1;  DUMMY2;

        p = (void **) (*p); DUMMY1;  DUMMY2;
        p = (void **) (*p); DUMMY1;  DUMMY2;
        p = (void **) (*p); DUMMY1;  DUMMY2;
        p = (void **) (*p); DUMMY1;  DUMMY2;
        p = (void **) (*p); DUMMY1;  DUMMY2;
    }

    return p;
}

#ifdef ASCT
// Performs end - start and returns the value as nanosecond
double timespec_diff_nanosec(const struct timespec *end, const struct timespec *start) {
    time_t sec_diff = end->tv_sec - start->tv_sec;
    long nsec_diff = end->tv_nsec - start->tv_nsec;
    return (double)sec_diff * 1e9 + (double)nsec_diff;
}
#endif

void latency_thread (struct lat_thread_info * lat_tinfo) {
    size_t cacheline_bytes                    = lat_tinfo->lat_cacheline_bytes;
    size_t cacheline_count                    = lat_tinfo->cacheline_count;
    size_t iterations                         = lat_tinfo->iterations;
#ifndef ASCT // Only used by original implementation printing message
    double cycle_time_ns                      = lat_tinfo->cycle_time_ns;
#endif
    int thread_num                            = lat_tinfo->thread_num;
    int cpu                                   = lat_tinfo->cpu;
    unsigned long hwcounter_start             = lat_tinfo->hwcounter_start;
#ifdef ASCT
    uint64_t repetitions            = lat_tinfo->repetitions;
#endif
    unsigned long hwcounter_stop              = lat_tinfo->hwcounter_stop;
    int randomize                             = lat_tinfo->randomize;
    int use_hugepages                         = lat_tinfo->use_hugepages;
    void ** mem                               = lat_tinfo->mem;
    size_t lat_offset                         = lat_tinfo->lat_offset;
    int lat_clear_cache                       = lat_tinfo->lat_clear_cache;
    int warmup                                = lat_tinfo->warmup;
    size_t cacheline_stride                   = lat_tinfo->cacheline_stride;

    double avg_latency = 0.0;
#ifdef ASCT
    double avg_latency_cyc = 0.0;
#endif
#ifndef ASCT // ASCT normally will not have the trailing iteration issue
    double min_latency = INFINITY;
    unsigned long latency_samples = 0;
#endif
    unsigned long start_tick, stop_tick;

#ifdef ASCT
    struct timespec t0, t1;
#else
    struct timeval t0, t1, tdiff;
#endif

    // if mem is not NULL, then it has been preinitalized.

    if (mem == NULL) {
        mem = lat_initialize(cacheline_bytes, cacheline_count, randomize, lat_clear_cache, cacheline_stride, use_hugepages);
    }

    void ** p = mem;

    // warm-up read

    if (warmup) {
        p = run(p, cacheline_count); // this will do 10 full-reads because there are 10 deploads per iteration in run()
        printf("CPU%d LATTHREAD%d: warmed up\n", cpu, thread_num);
    }
    p = run(p, lat_offset / 10);    // advance p to start offset. / 10 because there are 10 deploads per iteration in run()

    printf("CPU%d LATTHREAD%d: cacheline_count = %zu, iterations = %zu, mem = %p, randomize = %d, use_hugepages = %d, hwcounter_start = 0x%zx, lat_offset = %zu, tid = %d\n",
           cpu, thread_num, cacheline_count, iterations, mem, randomize,
           use_hugepages, hwcounter_start, lat_offset, gettid());

    // wait until hwcounter reaches the expected value
    while ((start_tick = read_hwcounter()) < hwcounter_start) {
        ;
    }

    lat_tinfo->actual_hwcounter_start = start_tick;

    // XXX: this printf has overhead
    printf("CPU%d LATTHREAD%d: started at " HWCOUNTER " = 0x%zx\n", cpu, thread_num, start_tick);

    size_t last_hwcounter = start_tick;

    stop_tick = read_hwcounter();

#ifndef ASCT
    if (stop_tick < hwcounter_stop) {
        do {
            gettimeofday(&t0, NULL);

            p = run(p, iterations);

            gettimeofday(&t1, NULL);

            timersub(&t1, &t0, &tdiff);

            double x = tdiff.tv_sec;    // x is elapsed time for loop. Here it is in seconds.
            x += tdiff.tv_usec / 1e6;

            double x_per_iter = x;
            x_per_iter *= 1e9;
            x_per_iter /= iterations * 10;  // latency for this iteration

            size_t this_hwcounter = read_hwcounter();

#if 0
            typedef struct {
                void * next;
                size_t order;
                size_t index;
            } partial_node_t;

            size_t current_index = ((partial_node_t *) p)->index;

            printf("CPU%d LATTHREAD%d: %.6f ns, %.6f cycles, cntvct=0x%08lx cntvct_diff=%lu p=%p index=%zu latency_samples=%zu\n",
                    cpu, thread_num, x_per_iter, x_per_iter/cycle_time_ns, this_hwcounter,
                    this_hwcounter - last_hwcounter, p, current_index, latency_samples);
#else
            printf("CPU%d LATTHREAD%d: %.6f ns, %.6f cycles\n", cpu, thread_num, x_per_iter, x_per_iter/cycle_time_ns);
#endif

            last_hwcounter = this_hwcounter;

            if (x_per_iter < min_latency) {
                min_latency = x_per_iter;
            }

            avg_latency += x_per_iter;
            latency_samples++;
        } while (last_hwcounter < hwcounter_stop);
        stop_tick = last_hwcounter;
    } else {
        unsigned long tick_deficit = stop_tick - hwcounter_stop;
        double tick_deficit_seconds = tick_deficit / (double) read_cntfreq();

        printf("CPU%d LATTHREAD%d: the hwclock has passed the expected "
        "stop time without any measurements.  Use --delay-seconds to "
        "increase delay time for threads to do their setup.  A "
        "suggested value to add to the current value is %f\n",
        cpu, thread_num, tick_deficit_seconds);
    }
#else // ASCT
    p = run(p, iterations); // warmup run
    unsigned long run_duration_tick = hwcounter_stop - hwcounter_start;
    repetitions = 0;
    size_t this_now = read_hwcounter();
    size_t end_tick = this_now + run_duration_tick;
    while (1) {
        repetitions++;
        p = run(p, iterations);
        if (read_hwcounter() >= end_tick) {
            break;
        }
    }
    // recorded number of repetitions for target time, now run the barrier to wait for all threads
    uint64_t _repetitions;
    do {
        _repetitions = atomic_load(lat_tinfo->_repetitions);
    } while(repetitions > _repetitions
            && !atomic_compare_exchange_weak(lat_tinfo->_repetitions, &_repetitions, repetitions));

    int rc = pthread_barrier_wait(lat_tinfo->barrier);
    if (rc != 0) {
        if (rc == PTHREAD_BARRIER_SERIAL_THREAD) {
            // reset the following start flag to busy waiting loop below to restart
            atomic_store_explicit(lat_tinfo->arrival_count, 0, memory_order_release);
        } else {
            // Error condition
            printf("Error: pthread_barrier_wait failed with code %d\n", rc);
            exit(-1);
        }
    }

    pthread_barrier_wait(lat_tinfo->barrier);
    // all threads update the bwthinfo->_repetitions if their repetitions is larger, so we can load the max
    repetitions = atomic_load(lat_tinfo->_repetitions);
    // use the count to track how many threads passed the barrier and ready to start
    atomic_fetch_add_explicit(lat_tinfo->arrival_count, 1, memory_order_acq_rel);
    while (atomic_load_explicit(lat_tinfo->arrival_count, memory_order_acquire) < lat_tinfo->total_num_threads) {
        // busy wait until all threads are ready
    }

    if (repetitions <= 0) {
        printf("CPU%d LATTHREAD%d: ERROR: repetitions not positive\n", cpu, thread_num);
        exit(-1);
    }
    // ASCT will go ahead to run the loop for fixed repetitions
    size_t do_count_times_iterations = repetitions * iterations;
    size_t my_start_tick = read_hwcounter();

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
    clock_gettime(CLOCK_MONOTONIC, &t0);
    p = run(p, do_count_times_iterations);
    clock_gettime(CLOCK_MONOTONIC, &t1);
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

    size_t my_stop_tick = read_hwcounter();
    size_t my_tick_diff = my_stop_tick - my_start_tick;
    double mem_op_count = (double)do_count_times_iterations * 10;
    avg_latency = timespec_diff_nanosec(&t1, &t0) / mem_op_count;
    avg_latency_cyc = avg_latency * (double) read_cntfreq() / 1e9; // in cycles
    stop_tick = last_hwcounter;
    printf("avg_latency = %.6f, do_count = %lu, iterations = %zu, my_tick_diff = %zu\n", avg_latency, repetitions, iterations, my_tick_diff);
#endif // ASCT

    asm volatile ("" : : "r" (p));  // force p to be "used"

    lat_tinfo->actual_hwcounter_stop = stop_tick;

#ifndef ASCT // ASCT normally will not have the trailing iteration issue
    // drop lowest latency if there is more than 1 sample
    // because it may be an unencumbered trailing iteration

    if (latency_samples > 1) {
        avg_latency -= min_latency;
        latency_samples--;
    }

    avg_latency /= latency_samples;
#endif

    lat_tinfo->avg_latency = avg_latency;
#ifdef ASCT
    lat_tinfo->avg_latency_cyc = avg_latency_cyc;
#endif
}
