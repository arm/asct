/*
 * Copyright (C) Arm Ltd. 2025. All rights reserved.
 */

#include "hwpf.h"

#include <errno.h>
#include <unistd.h>

#if defined(__x86_64__)

#include <stdint.h>
#include <stdio.h>
#include <fcntl.h>

#define MSR_HWPF         0x1A4
#define MSR_HWPF_DISABLE   0xf
#define MSR_HWPF_ENABLE    0x0

static int open_msr(int cpu, int mode)
{
    char fn[32];
    sprintf(fn, "/dev/cpu/%u/msr", cpu);
    return open(fn, mode);
}


static uint64_t rdmsr(int cpu, unsigned long off)
{
    int rc;
    uint64_t val;
    int fd = open_msr(cpu, O_RDONLY);
    if (fd < 0) {
        return (uint64_t)(-1);
    }
    rc = pread(fd, &val, 8, off);
    close(fd);
    return (rc != 8) ? (uint64_t)(-1) : val;
}


static int wrmsr(int cpu, unsigned long off, uint64_t val, uint64_t *oval)
{
    int rc;
    int fd = open_msr(cpu, O_RDWR);
    if (fd < 0) {
        return -1;
    }
    if (oval != NULL) {
        rc = pread(fd, oval, 8, off);
        if (rc <= 0) {
            close(fd);
            return rc;
        }
    }
    rc = pwrite(fd, &val, 8, off);
    close(fd);
    return (rc < 0) ? rc : 0;
}

#endif



int hwpf_check(int cpu)
{
#ifdef __x86_64__
    return rdmsr(cpu, MSR_HWPF);
#else
    errno = ENOTSUP;
    return -1;
#endif
}


int hwpf_set(int cpu, int state)
{
    if (cpu == -1) {
        int rc = 0;
        int i;
        int n_cpu = sysconf(_SC_NPROCESSORS_CONF);
        for (i = 0; i < n_cpu; ++i) {
            rc = hwpf_set(i, state);
            /* Tolerate ENOENT, as the CPU may be offline */
            if (rc < 0 && errno != ENOENT) {
                break;
            }
        }
        return rc;
    }
#ifdef __x86_64__
    return wrmsr(cpu, MSR_HWPF, ((state == HWPF_DISABLE) ? MSR_HWPF_DISABLE : MSR_HWPF_ENABLE), NULL);
#else
    /* Don't know how to change hardware prefetcher status on this target */
    errno = ENOTSUP;
    return -1;
#endif
}


