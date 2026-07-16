/*
 * Copyright (C) Arm Ltd. 2025. All rights reserved.
 */

#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif

#include <assert.h>

#include "cpufreq.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>


#define CPUFREQ_MAX_GOV 20

typedef struct cpufreq_restore_s {
    struct cpufreq_restore_s *next;
    unsigned int cpu;
    char gov[CPUFREQ_MAX_GOV];
} cpufreq_restore_t;


static cpufreq_restore_t *needs_restore;
static int atexit_set = 0;


void
cpufreq_restore(void)
{
    while (needs_restore) {
        cpufreq_restore_t *nr = needs_restore;
        needs_restore = nr->next;
        cpufreq_set_governor(nr->cpu, nr->gov);
        free(nr);
    }
}


static FILE *
cpu_frequency_open(unsigned int cpu, char const *par, char const *mode)
{
    char fn[100];
    sprintf(fn, "/sys/devices/system/cpu/cpu%u/cpufreq/%s", cpu, par);
    FILE *fd = fopen(fn, mode);
    return fd;
}


static unsigned int
cpu_frequency_parameter(unsigned int cpu, char const *par)
{
    int rc;
    unsigned int freq = 0;
    FILE *fd = cpu_frequency_open(cpu, par, "r");
    if (fd) {
        rc = fscanf(fd, "%u", &freq);
        assert(rc == 1);
        fclose(fd);
    }
    return freq;
}


unsigned int cpufreq_current(unsigned int cpu)
{
    unsigned int n = cpu_frequency_parameter(cpu, "cpuinfo_cur_freq");
    if (!n) {
        n = cpu_frequency_parameter(cpu, "scaling_cur_freq");
    }
    return n;
}


int
cpufreq_set_governor(unsigned int cpu, char const *gov)
{
    FILE *fd = cpu_frequency_open(cpu, "scaling_governor", "w");
    if (fd) {
        fprintf(fd, "%s", gov);
        fclose(fd);
        return 0;
    } else {
        perror("scaling_governor");
        return -1;
    }
}


int
cpufreq_get_governor(unsigned int cpu, char *gov, size_t size)
{
    FILE *fd = cpu_frequency_open(cpu, "scaling_governor", "r");
    if (fd) {
        int n = fread(gov, 1, size, fd);
        fclose(fd);
        if (n == (long)size) {
            return -2;
        }
        return 0;
    } else {
        *gov = '\0';
        return -1;
    }
}


static int
cpufreq_push_governor(unsigned int cpu, char const *gov)
{
    char ogov[CPUFREQ_MAX_GOV+1];
    int rc;
    rc = cpufreq_get_governor(cpu, ogov, sizeof ogov);
    if (rc) {
        return rc;
    }
    if (!strcmp(gov, ogov)) {
        /* Already set to the requested governor */
        return 0;
    }
    rc = cpufreq_set_governor(cpu, gov);
    if (!rc) {
        /* New governor was set - remember to restore the old one */
        cpufreq_restore_t *nr = (cpufreq_restore_t *)malloc(sizeof *nr);
        nr->cpu = cpu;
        strcpy(nr->gov, ogov);
        nr->next = needs_restore;
        needs_restore = nr;
        if (!atexit_set) {
            atexit(cpufreq_restore);
        }
    }
    return rc;
}


unsigned int CPUFREQ_TIMEOUT_US = 1000;


int
cpufreq_wait_frequency(unsigned int cpu, unsigned int freq)
{
    unsigned int t_us = 10;
    unsigned int t_total_us = 0;
    for (;;) {
        if (cpufreq_current(cpu) == freq) {
            return 0;
        }
        if (t_total_us >= CPUFREQ_TIMEOUT_US) {
            return -1;
        }
        usleep(t_us);
        t_total_us += t_us;
        t_us *= 2;
    }
}


int cpufreq_set_frequency(unsigned int cpu, unsigned int freq)
{
    if (!cpufreq_push_governor(cpu, "userspace")) {
        FILE *fd;
        if (freq == CPUFREQ_MIN || freq == CPUFREQ_MAX) {
            freq = cpu_frequency_parameter(cpu, freq == CPUFREQ_MIN ? "scaling_min_freq" : "scaling_max_freq");
        }
        fd = cpu_frequency_open(cpu, "scaling_setspeed", "w");
        if (fd) {
            fprintf(fd, "%u", freq);
            fclose(fd);
            int rc = cpufreq_wait_frequency(cpu, freq);
            if (rc != 0) {
                fprintf(stderr, "cpufreq: CPU#%u didn't change to %u, now %u\n",
                    cpu, freq, cpufreq_current(cpu));
            }
            return rc;
        }
    } else {
        perror("can't set userspace cpufreq governor");
    }
    return -1;
}
