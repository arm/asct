/*
 * Copyright (C) Arm Ltd. 2025. All rights reserved.
 *
 * High-frequency timestamps. 
 */

#ifndef __included_clockns_h
#define __included_clockns_h

#include <stdint.h>
#include <time.h>

/* Clock id should be e.g. CLOCK_MONOTONIC */

uint64_t clock_gettime_ns(int);

double clock_gettime_double(int);

double clock_overhead(int);

#endif /* included */
