/*
 * Copyright (C) Arm Ltd. 2025. All rights reserved.
 *
 * Disable or enable hardware prefetching
 *
 * Will generally require privilege, and might not be possible at all.
 */

#ifndef __included_hwpf_h
#define __included_hwpf_h

/*
 * Return 1 if _disabled_, 0 if enabled, -1 if we can't check.
 */
int hwpf_check(int);

/*
 * Set hardware prefetcher state
 *
 * CPU number -1 for all CPUs
 */
#define HWPF_DISABLE  1
#define HWPF_ENABLE   0
int hwpf_set(int /*cpu*/, int);

#endif /* included */
