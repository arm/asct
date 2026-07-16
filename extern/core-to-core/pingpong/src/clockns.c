/*
 * Copyright (C) Arm Ltd. 2025. All rights reserved.
 */

#include "clockns.h"


static uint64_t
timespec_ns(struct timespec const *ts)
{
    return (ts->tv_sec * 1000000000ULL) + ts->tv_nsec;
}


uint64_t
clock_gettime_ns(int id)
{
    struct timespec ts;
    clock_gettime(id, &ts);
    return timespec_ns(&ts);
}


double
clock_gettime_double(int id)
{
    return clock_gettime_ns(id) / 1.0e9;
}


/*
 * Measure the overhead of a clock_gettime() call.
 * Implemented in VDSO, this is typically small, e.g. ~100ns.
 *
 * TBD: results from this function vary more than expected.
 * Possible causes:
 *  - actual variation in time of clock_gettime()
 *    e.g. kernel frequently changing time parameters
 *  - low resolution (granularity) in the t0/t1 measurements
 */
double
clock_overhead(int id)
{
    int i;
    int const ITERS = 1000;
    double t0 = clock_gettime_double(id);
    for (i = 0; i < ITERS; ++i) {
        clock_gettime_double(id);
    }
    double t1 = clock_gettime_double(id);
    return (t1 - t0) / ITERS;
}
