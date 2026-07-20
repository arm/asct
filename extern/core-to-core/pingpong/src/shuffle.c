/*
 * Copyright (C) Arm Ltd. 2025. All rights reserved.
 */

#include <assert.h>

#include "shuffle.h"

#include <stdlib.h>



/*
 * Construct a random maximal cycle, returned as an array of integers,
 * caller to free.
 * We use Sattolo's algorithm. This is a variant on the Fisher-Yates shuffle
 * that guarantees that the permutation is a single cycle.
 *
 * The pointer chain can then be constructed as "i -> order[i]".
 *
 * (We could alternatively use a standard shuffle and construct the
 * pointer chain as "order[i] -> order[i+1]".)
 *
 * Uses C library rand().
 */
unsigned int *random_maximal_cycle(unsigned int *order, unsigned int n)
{
    unsigned int i;
    assert(n > 0);
    for (i = 0; i < n; ++i) {
        order[i] = i;
    }
    for (i = n-1; i >= 1; --i) {
        unsigned int j = rand() % (i);
        unsigned int temp;
        assert(j < n);
        temp = order[j];
        order[j] = order[i];
        order[i] = temp;
    }
    /* order now contains a random maximal cycle. */
    return order;
}


unsigned int *alloc_random_maximal_cycle(unsigned int n)
{
    unsigned int *order = (unsigned int *)malloc(sizeof(int) * n);   /* This could be problematic if w.s. very large */
    assert(order != NULL);
    return random_maximal_cycle(order, n);
}
