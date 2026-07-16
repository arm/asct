/*
 * Measure inter-CPU latency.
 *
 * General approach, for any pair of CPUs A and B, is to have
 * CPU A read data out of CPU B's cache, such that each load doesn't start
 * until the previous one completes. And iterate this enough times to
 * get a reliable statistic.
 *
 * To start with, the data must be in B but not A. There are two ways
 * to achieve this:
 *
 *   - get the data Unique into B, either modified or not - the simplest
 *     way is to modify it, so that it's Unique Dirty. By definition it
 *     will not be in A.
 *
 *   - explicitly clean and invalidate from A, while also reading into B.
 *
 * In the code below, we take the first approach, getting the data UD into B.
 *
 * Then, the data must be read into A in such a way that the loads don't
 * overlap. For large working sets, this can be achieved by pointer-chaining.
 * But to be sure of reading out of B's cache, the working set may be small.
 * For smaller working sets (e.g. less than 1000 lines) a pointer chain risks
 * being learnt by A's hardware prefetcher, such that when one line is read
 * it knows the next line. Making the load address data formally dependent
 * on the previous line contents, is not sufficient to defeat hardware prefetch.
 * We need the next line to be different in each major iteration.
 *
 * How do we achieve that?
 *
 * - set up several distinct working sets, each with a different pointer chain.
 *   On each iteration B loads a fresh working set and A reads the chain.
 *   This multiplies the set of addresses seen by A's prefetcher, hopefully
 *   exceeding its capacity.
 *
 * - have A create its own fresh permutation of the lines in the working set,
 *   and load lines in that order, but retaining the data dependence on
 *   the data from the previous load. This creates a different "next"
 *   relationship than the one A's prefetcher previously saw.
 *
 * was: Demonstrate cache line ping-pong by setting up N threads sharing a variable.
 */

#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif

#include <assert.h>

#include "block.h"
#include "gettid.h"
#include "vatopa.h"
#include "cpufreq.h"
#include "clockns.h"
#include "round.h"
#include "chain.h"
#include "hwpf.h"
#include "hwmt.h"
#ifndef ASCT
#include "loadgen.h"
#endif
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
#include <unistd.h>
#include <pthread.h>
#ifdef ASCT
#ifdef USE_PROBE
#include "dietperf.h"
#endif
#endif

static int o_verbose = 0;

// extern int workload_verbose;
int workload_verbose = 0;

typedef enum {
    BENCH_MEMBLOCK,
    BENCH_SEMAPHORE,
} bench_type_t;

static bench_type_t o_bench_type = BENCH_MEMBLOCK;

static int o_pointer_offset = 0;

static int o_chain_spread = 4;    /* Enough to defeat page-prefetcher? */

static Block o_mem_props;

static int o_chain_is_blocked = 1;  /* Use chain sub-blocks to reduce TLB misses */

static int N_ITERS = 5;           /* Number of times to measure for each CPU */

static int o_repetitions = 1;     /* Overall repetitions */

static size_t o_block_size = 256*1024;  /* Enough to fit in CPU L2 */

static int o_minimum = 1;         /* Use minimum rather than mean */

static int o_nopf = 0;            /* Disable hardware prefetcher */

static int o_nomt = 0;            /* Disable hardware multithreading */

static int o_n_sema_iters = 5000;

static char o_csv = '\0';

static int o_csv_include_offline = 1;

static int o_symmetric = 1;

static int o_cpu_stride = 1;

#define CPUFREQ_NOP 2
static unsigned int o_freq = CPUFREQ_NOP;

static int o_n_cpus_specified = 0;

static int o_cpus[10];

static int o_no_free = 0;

#ifdef USE_PTHREADS_SEMAPHORE

#include <semaphore.h>

typedef sem_t sema_t;

#define spin_init sem_init
#define spin_wait sem_wait
#define spin_post sem_post

#ifdef ASCT
/* In the pthreads semaphore version, we simply block on the semaphore
 * with sem_wait and ignore the separate 'done' flag.
 * This implementation preserves source compatibility with the spin-based implementation,
 * which can poll both.
 */
#define spin_wait_with_done(s, d) (void)(sem_wait(s))
#endif

#else /* !USE_PTHREADS_SEMAPHORE */

typedef int volatile sema_t;


#if defined(__arm64__) || defined(__AARCH64EL__) || defined(__ARM_ARCH_ISA_A64)
#define DSB __asm__ __volatile__("dsb sy")
#define LOAD_BARRIER __asm__ __volatile__("dmb ld")
#define STORE_BARRIER __asm__ __volatile__("dmb st")
#else
#define DSB (void)0
#define LOAD_BARRIER (void)0
#define STORE_BARRIER (void)0
#endif


static void __attribute__((noinline))
spin_init(sema_t *s, int pshared, unsigned int value)
{
    assert(!pshared);
    *s = value;
    STORE_BARRIER;
}


static void __attribute__((noinline))
spin_wait(sema_t *s)
{
    while (!*s) LOAD_BARRIER;
    *s = 0;
    LOAD_BARRIER;
}

#ifdef ASCT
static void __attribute__((noinline))
spin_wait_with_done(sema_t *s, int _Atomic *done)
{
    while (!*s && !*done) LOAD_BARRIER;
    *s = 0;
    LOAD_BARRIER;
}
#endif

static void __attribute__((noinline))
spin_post(sema_t *s)
{
    LOAD_BARRIER;
    assert(*s != 1);
    *s = 1;
    STORE_BARRIER;
}

#endif /* USE_PTHREADS_SEMAPHORE */


/* These aren't in contention at the same time, so false sharing isn't an issue */
static sema_t spin_atob, spin_btoa;


static int volatile spin_shared;


/*
 * Read a block of data into the current CPU's cache,
 * for modification, although the contents are not changed.
 *
 * TBD: we currently read the entire block, not just size_req.
 *
 * TBD: the dummy write will cause the line to be in Modified state (UD in Arm CHI).
 * A true RFO would instead leave the line in Unique (Exclusive) state (UC in Arm CHI).
 * On Arm we could achieve that with PRFM.
 */
void block_rfo(Block *m)
{
    int i;
    for (i = 0; i < m->size_req; i += 64) {
        uint32_t volatile *p = (uint32_t *)((unsigned char *)m->base + i);
        *p = *p;
    }
}


/* Overhead for clock_gettime(), typically ~100ns. */
static float t_clock_gettime;

#ifndef ASCT
static void const *
follow_chain(void const *p, unsigned int *count)
{
    unsigned int n = 0;
    void const *op = p;
    do {
        void const *const *load_addr = (void const * const *)(p);
        load_addr = (void const *const *)((unsigned char *)load_addr + o_pointer_offset);
        p = *load_addr;
        ++n;    /* we expect the pipeline to execute this concurrently with the load */
    } while (p != op);
    if (count) {
        *count = n;
    }
    return p;
}
#endif

static void const *
follow_chain_write(void *p, unsigned int *count)
{
    unsigned int n = 0;
    void *op = p;
    do {
        void **load_addr = (void **)(p);
        load_addr = (void **)((unsigned char *)load_addr + o_pointer_offset);
        load_addr[1] = 0;      /* write to the line, to cause eviction from the other cache */
        p = *load_addr;
        ++n;    /* we expect the pipeline to execute this concurrently with the load */
    } while (p != op);
    if (count) {
        *count = n;
    }
    return p;
}


typedef double value_t;


typedef struct {
    unsigned int n;
    value_t total;
    value_t val_min, val_max;
} stats_t;


static void
stats_init(stats_t *st)
{
    memset(st, 0, sizeof *st);
}


static void
stats_update(stats_t *st, value_t val)
{
    st->n += 1;
    st->total += val;
    if (st->n == 1) {
        st->val_min = val;
        st->val_max = val;
    } else {
        if (val < st->val_min) {
            st->val_min = val;
        }
        if (val > st->val_max) {
            st->val_max = val;
        }
    }
}


static value_t
stats_mean(stats_t const *st)
{
    return st->total / st->n;
}


static value_t
stats_value(stats_t const *st)
{
    return o_minimum ? st->val_min : stats_mean(st);
}


typedef struct {
    /* Pre-creation */
    char const *name;
    void *user;
    void *(*fn)(void *);   /* Used to pass in actual closure */
    void *data;            /* ditto */
    int cpu;
    /* Post-creation */
    pthread_t thread_id;
    int tid;          /* OS thread id, filled in by thread main */
    /* Post-termination */
    void *ret;
    stats_t st;            /* Accumulated time */
    sema_t spin_mtot;
    sema_t spin_ttom;
    int _Atomic done;
} thread_state_t;


static void *
thread_main_common(void *pv)
{
    void *r;
    thread_state_t *ts = (thread_state_t *)pv;
    ts->tid = gettid();
    if (o_verbose >= 1) {
        fprintf(stderr, "[%d] %s starting...\n", ts->tid, ts->name);
    }
    r = (ts->fn)(ts->data);
    if (o_verbose >= 2) {
        fprintf(stderr, "[%d] %s finished.\n", ts->tid, ts->name);
    }
    return r;
}


static int
thread_start(thread_state_t *ts, void *(*fn)(void *), void *data)
{
    int rc;
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    if (ts->cpu != -1) {
        cpu_set_t affinity;
        CPU_ZERO(&affinity);
        CPU_SET(ts->cpu, &affinity);
        pthread_attr_setaffinity_np(&attr, sizeof affinity, &affinity);
    }
    ts->fn = fn;
    ts->data = data;
    if (!ts->name) {
        ts->name = "<anon>";
    }
    rc = pthread_create(&ts->thread_id, &attr, thread_main_common, ts);
    if (rc) {
        /* Might fail with ENOENT if we specified an invalid CPU */
        perror("create");
    }
    return rc;
}


static int
thread_join(thread_state_t *ts)
{
    int rc = pthread_join(ts->thread_id, &ts->ret);
    if (rc) {
        perror("join");
    }
    return rc;
}


/*
 * Attempt to pin a thread to a CPU.
 * This will fail with EINVAL if the CPU is offline.
 */
static int
thread_pin(thread_state_t *ts, int cpu)
{
    int rc;
    cpu_set_t cpus;
    CPU_ZERO(&cpus);
    CPU_SET(cpu, &cpus);
    rc = sched_setaffinity(ts->tid, sizeof cpus, &cpus);
    if (rc && o_verbose) {
        perror("sched_setaffinity");
    }
    return rc;
}


#define STATE_INIT 0
#define STATE_READY 1
#define STATE_PING 2
#define STATE_PONG 3
#define STATE_FINISH 4


static void *
thread_A_sema(void *pv)
{
    thread_state_t *ts = (thread_state_t *)pv;
    spin_wait(&spin_btoa);
    spin_post(&spin_atob);
    while (!ts->done) {
        int i;
#ifdef ASCT
        spin_wait_with_done(&ts->spin_mtot, &ts->done);
#else
        spin_wait(&ts->spin_mtot);
#endif
        if (ts->done) {
            break;
        }
        sched_yield();
        stats_init(&ts->st);
        for (i = 0; i < N_ITERS+1; ++i) {
            int j;
            double t0, t1;
#ifdef ASCT
            spin_wait_with_done(&spin_btoa, &ts->done);
            if(ts->done) {
                break;
            }
#else
            spin_wait(&spin_btoa);
#endif
            spin_post(&spin_atob);
            t0 = clock_gettime_double(CLOCK_MONOTONIC);
            while (spin_shared != STATE_READY) {}
            for (j = 0; j < o_n_sema_iters; ++j) {
                spin_shared = STATE_PING;
                while (spin_shared != STATE_PONG) {}
            }
            spin_shared = STATE_FINISH;
            t1 = clock_gettime_double(CLOCK_MONOTONIC);
            if (i > 0) {
                stats_update(&ts->st, (t1 - t0 - t_clock_gettime));
            }
            //spin_post(&spin_atob);
        }
        spin_post(&ts->spin_ttom);
    }
    return NULL;
}


static void *
thread_B_sema(void *pv)
{
    thread_state_t *ts = (thread_state_t *)pv;
    spin_post(&spin_btoa);
    spin_wait(&spin_atob);
    while (!ts->done) {
        int i;
#ifdef ASCT
        spin_wait_with_done(&ts->spin_mtot, &ts->done);
#else
        spin_wait(&ts->spin_mtot);
#endif
        if (ts->done) {
            break;
        }
        sched_yield();
        stats_init(&ts->st);
        for (i = 0; i < N_ITERS+1; ++i) {
            double t0, t1;
            spin_post(&spin_btoa);
#ifdef ASCT
            spin_wait_with_done(&spin_atob, &ts->done);
            if(ts->done) {
                break;
            }
#else
            spin_wait(&spin_atob);
#endif
            t0 = clock_gettime_double(CLOCK_MONOTONIC);
            spin_shared = STATE_READY;
            while (spin_shared == STATE_READY) {}
            while (spin_shared != STATE_FINISH) {
                if (spin_shared == STATE_PING) {
                    spin_shared = STATE_PONG;
                }
                while (spin_shared == STATE_PONG) {}
            }
            t1 = clock_gettime_double(CLOCK_MONOTONIC);
            if (i > 0) {
                stats_update(&ts->st, (t1 - t0 - t_clock_gettime));
            }
        }
        spin_post(&ts->spin_ttom);
    }
    return NULL;
}


static void *
thread_A_latency(void *pv)
{
    thread_state_t *ts = (thread_state_t *)pv;
    void *p = ts->user;
    int i;
    unsigned int count;
    spin_wait(&spin_btoa);
    spin_post(&spin_atob);
#ifdef ASCT
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
#endif
    while (!ts->done) {
#ifdef ASCT
        spin_wait_with_done(&ts->spin_mtot, &ts->done);
#else
        spin_wait(&ts->spin_mtot);
#endif
        if (ts->done) {
            break;
        }
        sched_yield();
        stats_init(&ts->st);
        for (i = 0; i < N_ITERS+1; ++i) {
            double t0, t1;
#ifdef ASCT
            spin_wait_with_done(&spin_btoa, &ts->done);
            if(ts->done) {
                break;
            }
#else
            spin_wait(&spin_btoa);
#endif
            t0 = clock_gettime_double(CLOCK_MONOTONIC);
            p = (void *)follow_chain_write(p, &count);
            t1 = clock_gettime_double(CLOCK_MONOTONIC);
            if (i > 0) {
                /* exclude first iteration - warmup */
                //fprintf(stderr, "A: %.2fns\n", (t1-t0)*1e9);
                stats_update(&ts->st, (t1 - t0 - t_clock_gettime));
            }
            spin_post(&spin_atob);
        }
        spin_post(&ts->spin_ttom);
    }
#ifdef ASCT
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
#endif

    return NULL;
}


static void *
thread_B_latency(void *pv)
{
    thread_state_t *ts = (thread_state_t *)pv;
    void *p = ts->user;
    int i;
    spin_post(&spin_btoa);
    spin_wait(&spin_atob);
    while (!ts->done) {

#ifdef ASCT
        spin_wait_with_done(&ts->spin_mtot, &ts->done);
#else
        spin_wait(&ts->spin_mtot);
#endif
        if (ts->done) {
            break;
        }
        sched_yield();
        stats_init(&ts->st);
        for (i = 0; i < N_ITERS+1; ++i) {
            double t0, t1;
            spin_post(&spin_btoa);
#ifdef ASCT
            spin_wait_with_done(&spin_atob, &ts->done);
            if(ts->done) {
                break;
            }
#else
            spin_wait(&spin_atob);
#endif
            t0 = clock_gettime_double(CLOCK_MONOTONIC);
            p = (void *)follow_chain_write(p, NULL);
            t1 = clock_gettime_double(CLOCK_MONOTONIC);
            if (i > 0) {
                //fprintf(stderr, "B: %.2fns\n", (t1-t0)*1e9);
                stats_update(&ts->st, (t1 - t0 - t_clock_gettime));
            }
        }
        spin_post(&ts->spin_ttom);
    }
    return NULL;
}


static int
measure(void)
{
    Block mem = o_mem_props;
    chain_t ch;
    thread_state_t ts[2];
    int const N_CPU = sysconf(_SC_NPROCESSORS_CONF);
    int first_a, last_a;
    int a, b;
    int i;
    void *chain;

    chain_init(&ch);
    spin_init(&spin_atob, 0, 0);
    spin_init(&spin_btoa, 0, 0);

    memset(&ts, 0, sizeof ts);
    ts[0].name = "pingpong-A";
    ts[1].name = "pingpong-B";
    ts[0].cpu = -1;
    ts[1].cpu = -1;
    /* If user has specified CPUs, start the worker threads pinned */
    for (i = 0; i < o_n_cpus_specified; ++i) {
        ts[i].cpu = o_cpus[i];
    }


    if (o_bench_type == BENCH_MEMBLOCK) {

        /* Allocate the working-set memory */
        ch.n_links = round_count_down(o_block_size, 64);
        ch.spread = o_chain_spread;
        ch.value_offset = o_pointer_offset;
        ch.is_blocked = o_chain_is_blocked;       /* reduce TLB misses */

        mem.size_req = o_block_size * ch.spread;
        workload_verbose = (o_verbose >= 1) ? (o_verbose - 1) : 0;
        if (!block_alloc(&mem)) {
            fprintf(stderr, "Can't allocate memory\n");
            exit(EXIT_FAILURE);
        }

        chain = (void *)chain_construct(mem.base, mem.size_req, &ch, workload_verbose);
        if (o_verbose >= 2) {
            fprintf(stderr, "Constructed chain:\n");
            block_fprint(&mem, stderr, 20);
        }
        if (o_verbose >= 1) {
#define N_VATOPA_MAPS 10
            vatopa_stat_t stats;
            vatopa_map_t maps[N_VATOPA_MAPS];
            vatopa_stat_init(&stats);
            unsigned int n_to_collect = (o_verbose >= 2) ? N_VATOPA_MAPS : 0;
            int n_needed = vatopa_get_map(mem.base, mem.size_req, &stats, maps, n_to_collect);
            if (n_needed > 0) {
                int i;
                fprintf(stderr, "Physical addresses 0x%lx..0x%lx:\n", stats.pa_low, stats.pa_high);
                fprintf(stderr, "  Pages:     %10u\n", stats.stat[VA_ATTR_VALID]);
                fprintf(stderr, "  Huge:      %10u\n", stats.stat[VA_ATTR_HUGE]);
                fprintf(stderr, "  Unmapped:  %10u\n", stats.stat[VA_ATTR_UNMAPPED]);
                fprintf(stderr, "  Jumps:     %10u\n", stats.n_discontiguous);
                for (i = 0; i < n_needed; ++i) {
                    if (i >= n_to_collect) {
                        /* There are more VA-to-PA entries but we didn't collect them */
                        if (i > 0) {
                            fprintf(stderr, "  ...\n");
                        }
                        break;
                    }
                    fprintf(stderr, "  %04x  %p %#lx -> ",
                        maps[i].pebits, (void const *)maps[i].va, maps[i].size);
                    if (maps[i].flags & VA_MAP_UNMAPPED) {
                        fprintf(stderr, "unmapped");
                    } else {
                        fprintf(stderr, "0x%016lx", maps[i].pa);
#ifdef VA_MAP_HAS_KPF
                        fprintf(stderr, " kpf:0x%016lx", maps[i].kpf);
#endif
                        if (maps[i].flags & VA_MAP_NONEXCLUSIVE) {
                            fprintf(stderr, " shared");
                        }
                        if (maps[i].flags & VA_MAP_HUGE) {
                            fprintf(stderr, " huge");
                        }
                    }
                    fprintf(stderr, "\n");
                }
            } else {
                fprintf(stderr, "Could not get physical addresses\n");
            }
        }

        ts[0].user = chain;
        ts[1].user = chain;
    }

    for (i = 0; i < 2; ++i) {
        int rc;
        if (o_bench_type == BENCH_MEMBLOCK) {
            rc = thread_start(&ts[i], i == 0 ? thread_A_latency : thread_B_latency, &ts[i]);
        } else if (o_bench_type == BENCH_SEMAPHORE) {
            rc = thread_start(&ts[i], i == 0 ? thread_A_sema : thread_B_sema, &ts[i]);
        } else {
            assert(0);
        }
        if (rc) {
            fprintf(stderr, "Could not start worker thread\n");
            exit(EXIT_FAILURE);
        }
    }

    sched_yield();

    /* Find the range of CPUs. TBD: handle offline CPUs.
       If there's only (one) online CPU, then the loops below should work,
       but not measure anything, and output will be blank. */
    if (sysconf(_SC_NPROCESSORS_ONLN) < N_CPU) {
        fprintf(stderr, "** Some CPUs are offline and will be omitted\n");
    }

    if (o_n_cpus_specified >= 1) {
        first_a = o_cpus[0];
        last_a = o_cpus[0];
    } else {
        first_a = 0;
        last_a = N_CPU-1;
    }
    for (a = first_a; a <= last_a; a += o_cpu_stride) {
        int first_b, last_b;
        int is_a_online = (thread_pin(&ts[0], a) == 0);
        ts[0].cpu = a;
        if (!o_csv) {
            printf("%3u  ", a);
        }
        if (o_n_cpus_specified == 2) {
            first_b = o_cpus[1];
            last_b = o_cpus[1];
        } else {
            if (o_csv && o_symmetric) {
                first_b = a + o_cpu_stride;   /* can do triangular and print two at a time */
            } else {
                first_b = 0;
            }
            last_b = N_CPU-1;
        }
        for (b = first_b; b <= last_b; b += o_cpu_stride) {
            unsigned int n_transfers =
                (o_bench_type == BENCH_MEMBLOCK)  ? ch.n_links :
                (o_bench_type == BENCH_SEMAPHORE) ? o_n_sema_iters :
                0;
            if (a == b) {
                if (!o_csv) {
                    printf("      ");
                }
                continue;
            }
            if (!is_a_online || thread_pin(&ts[1], b) < 0) {
                if (!o_csv) {
                    printf("     *");
                } else if (o_csv_include_offline) {
                    printf("%u%c%u%c-1\n", b, o_csv, a, o_csv);
                    printf("%u%c%u%c-1\n", a, o_csv, b, o_csv);
                }
                continue;
            }
            ts[1].cpu = b;
            sched_yield();             /* in case we're running on one of them */
            for (i = 0; i < 2; ++i) {
                spin_post(&ts[i].spin_mtot);
            }
            if (o_verbose) {
                fprintf(stderr, "[%u] waiting on (%u, %u)\n", gettid(), a, b);
            }
            for (i = 0; i < 2; ++i) {
                spin_wait(&ts[i].spin_ttom);
            }
            if (o_verbose) {
                for (i = 0; i < 2; ++i) {
                    fprintf(stderr, " %3u -> %3u: mean %6.2fus  min %6.2fus  max %6.2fus\n",
                        ts[1-i].cpu, ts[i].cpu,
                        stats_mean(&ts[i].st)*1e6, ts[i].st.val_min*1e6, ts[i].st.val_max*1e6);
                }
            }
            if (o_csv) {
                /* For CSV, we can show both A reading from B, and B reading from A */
                for (i = 0; i < (o_symmetric ? 2 : 1); ++i) {
                    double t_iter = stats_value(&ts[i].st);
                    double t_load = t_iter / n_transfers;
                    if (i == 0) {
                        printf("%u%c%u%c", b, o_csv, a, o_csv);
                    } else {
                        printf("%u%c%u%c", a, o_csv, b, o_csv);
                    }
                    printf("%.2f\n", t_load * 1e9);
                }
            } else {
                for (i = 0; i < 1; ++i) {
                    double t_iter = stats_value(&ts[i].st);
                    double t_load = t_iter / n_transfers;
                    printf(" %5.1f", t_load * 1e9);
                }
            }
        }
        if (!o_csv) {
            printf("\n");
        }
    }
    for (i = 0; i < 2; ++i) {
        ts[i].done = 1;
        spin_post(&ts[i].spin_mtot);
    }

    if (o_verbose) {
        fprintf(stderr, "[%u] waiting on thread termination\n", gettid());
    }
    for (i = 0; i < 2; ++i) {
        thread_join(&ts[i]);
    }
    if (!o_no_free) {
        block_free(&mem);
    }
    return 0;
}


static int setup_and_measure(void)
{
    int rc = -1;
    int i;
    double const t0 = clock_gettime_double(CLOCK_MONOTONIC);
#ifdef ASCT
    int const has_cpufreq = 0;
#else
    int const has_cpufreq = (cpufreq_current(0) != 0);
#endif
    int const do_cpufreq = (has_cpufreq && o_freq != CPUFREQ_NOP);

    /* Calibration: get the clock overhead */
    t_clock_gettime = clock_overhead(CLOCK_MONOTONIC);

    if (o_verbose) {
        fprintf(stderr, "clock_gettime cost: %.2fns\n", t_clock_gettime * 1e9);
    }

    if (o_freq != CPUFREQ_NOP && !has_cpufreq && o_verbose) {
        fprintf(stderr, "cpufreq not available, cannot override frequency\n");
    }
    if (do_cpufreq) {
        if (o_verbose) {
            //fprintf(stderr, "freq: %u %u\n",
                //cpufreq_current(cpus[0]), cpufreq_current(cpus[1]));
        }
        for (i = 0; i < o_n_cpus_specified; ++i) {
            int rc = cpufreq_set_frequency(o_cpus[i], o_freq);
            if (rc != 0) {
                fprintf(stderr, "CPU#%u: failed to set frequency\n", o_cpus[i]);
            }
        }
    }
    if (o_nopf) {
        int rc;
        if (o_verbose) {
            fprintf(stderr, "disabling hardware prefetcher\n");
        }
        rc = hwpf_set(-1, HWPF_DISABLE);
        if (rc && errno != ENOENT) {
            perror("disable");
            fprintf(stderr, "Can't disable hardware prefetcher\n");
            goto cleanup;
        }
    }
    if (o_nomt) {
        int rc;
        if (o_verbose) {
            fprintf(stderr, "disabling hardware multithreading\n");
        }
        rc = hwmt_set(HWMT_OFF);
        if (rc != HWMT_OFF && rc != HWMT_NOTIMPLEMENTED) {
            fprintf(stderr, "Can't disable hardware multithreading\n");
            goto cleanup;
        }
    } else {
        if (hwmt_status() == HWMT_ON) {
            fprintf(stderr, "Warning: this system is using hardware multithreading\n");
        }
    }

    for (i = 0; i < o_repetitions; ++i) {
        rc = measure();
        if (rc != 0) {
            break;
        }
    }

cleanup:
    if (do_cpufreq) {
        //cpufreq_restore();
        for (i = 0; i < o_n_cpus_specified; ++i) {
    //        cpufreq_set_governor(ts[0].cpu, "ondemand");
        }
    }
    if (o_nopf) {
        if (o_verbose) {
            fprintf(stderr, "enable hardware prefetcher\n");
        }
        hwpf_set(-1, HWPF_ENABLE);
    }
    if (o_nomt) {
        hwmt_set(HWMT_ON);
    }

    if (o_verbose) {
        double const t_done = clock_gettime_double(CLOCK_MONOTONIC);
        fprintf(stderr, "Run time = %.2fs\n",
            (t_done - t0));
    }
    return rc;
}


static int help(void)
{
    fprintf(stderr, "-f<freq> -r<reps> -I<iters> -m<nodemask> -s<size> -v cpu1 cpu2\n");
    fprintf(stderr, "  specify one CPU to do that CPU and all others\n");
    fprintf(stderr, "  specify two CPUs to do just that pair\n");
    fprintf(stderr, "  --mean           use mean measurement\n");
    fprintf(stderr, "  --minimum        use minimum measurement, not mean\n");
    fprintf(stderr, "  --no-symmetric   measure A->B and B->A separately\n");
    fprintf(stderr, "  --nomt           disable hardware multithreading\n");
    fprintf(stderr, "  --nopf           disable hardware prefetcher (x86 only)\n");
    return EXIT_FAILURE;
}


int main(int argc, char **argv)
{
    while (*++argv) {
        char const *arg = *argv;
        if (arg[0] == '-') {
            ++arg;
            switch (arg[0]) {
            case 'f':
                o_freq = atoi(arg+1);
                break;
            case 'F':
                o_mem_props.fill_type = BLOCK_FILL_DEFAULT;
                break;
            case 'H':
                o_mem_props.is_hugepage = 1;
                o_mem_props.is_force_hugepage = 1;
                break;
            case 'h':
                return help();
            case 'I':
                N_ITERS = atoi(arg+1);
                break;
            case 'm':
                o_mem_props.is_numa = 1;
                o_mem_props.nodemask = atoi(arg+1);
                break;
            case 'n':
                o_mem_props.user_name = arg+1;
                break;
            case 'p':
                /* Value offset for pointer. Attempt to defeat prefetchers. */
                o_pointer_offset = atoi(arg+1);
                break;
            case 'R':
                o_chain_spread = atoi(arg+1);
                break;
            case 'r':
                o_repetitions = atoi(arg+1);
                break;
            case 'S':
                o_cpu_stride = atoi(arg+1);
                break;
            case 's':
                /* What we really want is "%zi" which should scan a value of type size_t and
                   handle base prefixes like "0x". But GCC interprets this as scanning a
                   "signed size_t" and warns. */
                {
                    long bs;
                    if (!sscanf(arg+1, "%li", &bs)) {
                        return help();
                    }
                    o_block_size = bs;
                    o_n_sema_iters = o_block_size;
                }
                break;
            case 'u':
                o_chain_is_blocked = 0;
                break;
            case 'v':
                o_verbose++;
                break;
            case 'x':
                if (arg[1] == 't') {
                    o_csv = '\t';
                } else if (arg[1] == '\0') {
                    o_csv = ' ';
                } else {
                    o_csv = arg[1];
                }
                break;
            case '-':
                /* Keyword argument */
                ++arg;
                if (!strcmp(arg, "help")) {
                    return help();
                } else if (!strcmp(arg, "no-free")) {
                    o_no_free = 1;
                } else if (!strcmp(arg, "nomt")) {
                    o_nomt = 1;
                } else if (!strcmp(arg, "nopf")) {
                    o_nopf = 1;
                } else if (!strcmp(arg, "mean")) {
                    o_minimum = 0;
                } else if (!strcmp(arg, "minimum")) {
                    o_minimum = 1;
                } else if (!strcmp(arg, "semaphore")) {
                    o_bench_type = BENCH_SEMAPHORE;
                } else if (!strcmp(arg, "symmetric")) {
                    o_symmetric = 1;
                } else if (!strcmp(arg, "no-symmetric")) {
                    o_symmetric = 0;
                } else {
                    fprintf(stderr, "bad argument: '--%s'\n", arg);
                    return help();
                }
                break;
            default:
                fprintf(stderr, "bad argument: '%s'\n", arg);
                return help();
            }
        } else {
            if (o_n_cpus_specified >= 2) {
                fprintf(stderr, "specify at most 2 CPUs: '%s'\n", arg);
                return help();
            }
            o_cpus[o_n_cpus_specified++] = atoi(arg);
        }
    }

    return (setup_and_measure() == 0) ? EXIT_SUCCESS : EXIT_FAILURE;
}

