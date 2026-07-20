/*
 * Copyright (C) Arm Ltd. 2025. All rights reserved.
 *
 * Private header for load generation
 */

#ifndef __included_loadgenp_h
#define __included_loadgenp_h

#ifndef ASCT
#include "loadgen.h"
#endif /* ASCT */
#include <stdio.h>
#include <stddef.h>

extern int workload_verbose;

extern void *load_construct_code(Workload *);

extern void load_free_code(Workload *);

extern void *load_construct_data(Character const *, Block *);

extern void fprint_mem(FILE *, void const *, size_t);

extern void fprint_code(FILE *, void const *, size_t);

#define DEBUG_FD stderr

#endif /* included */
