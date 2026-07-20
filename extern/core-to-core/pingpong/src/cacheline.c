/*
 * Copyright (C) Arm Ltd. 2025. All rights reserved.
 */

#include "cacheline.h"

#include <stdio.h>
#include <unistd.h>


unsigned int cache_line_length(void)
{
    static unsigned int line_size = 0;
    if (!line_size) {
        long line = sysconf(_SC_LEVEL1_DCACHE_LINESIZE);
        if (line < 0) {
            perror("sysconf(_SC_LEVEL1_DCACHE_LINESIZE)");
            line = 64;    /* Fall back to sensible guess at line size */
        } else if (line == 0) {
            fprintf(stderr, "sysconf(_SC_LEVEL1_DCACHE_LINESIZE) reports line size zero: assume 64\n");
            line = 64;
        }
        line_size = (unsigned int)line;
    }
    return line_size;
}


