/*
 * Copyright (C) Arm Ltd. 2025. All rights reserved.
 */

#ifndef __included_shuffle_h
#define __included_shuffle_h

/*
 * Construct a random maximal cycle of 0..N-1.
 */
unsigned int *random_maximal_cycle(unsigned int *, unsigned int);

/*
 * Returns a dynamically allocated array - caller to free.
 */
unsigned int *alloc_random_maximal_cycle(unsigned int);

#endif
