/*
 * Copyright (C) Arm Ltd. 2025. All rights reserved.
 *
 * CPU dynamic frequency management via sysfs
 *
 * Generally requires sudo.
 *
 * This interface is simplistic, but hopefully adequate to lock down
 * CPU frequencies when microbenchmarking. 
 */

#ifndef __included_cpufreq_h
#define __included_cpufreq_h

#include <stddef.h>

#define CPUFREQ_MIN 0
#define CPUFREQ_MAX 1

/*
 * Set frequency (in kHz) and wait until it takes effect.
 *
 * Return -1 on permissions issues, or failure to change.
 *
 * Frequency can be CPUFREQ_MIN or CPUFREQ_MAX.
 *
 * Many frequency changes in quick succession are likely to
 * increase the wait time and risk of timeouts.
 */
int cpufreq_set_frequency(unsigned int cpu, unsigned int freq);

/*
 * After setting the frequency, we wait until it takes effect.
 * The timeout can be controlled.
 *
 * TBD: The frequency might never stabilize at the exact
 * requested frequency, e.g. it might be snapped to one of a
 * number of discrete set points. Some implementations expose
 * these set-points in scaling_available_frequencies, others
 * do not.
 */
extern unsigned int CPUFREQ_TIMEOUT_US;

/*
 * Wait for frequency to stabilize at a previously set point.
 */
int cpufreq_wait_frequency(unsigned int cpu, unsigned int freq);


/*
 * Get the current frequency (in kHz) as reported by cpufreq.
 */
unsigned int cpufreq_current(unsigned int cpu);


/*
 * Set the frequency governor for a CPU, returning -1 on error.
 */
int cpufreq_set_governor(unsigned int cpu, char const *gov);


/*
 * Get the frequency governor for a CPU.
 */
int cpufreq_get_governor(unsigned int cpu, char *gov, size_t size);


/*
 * Restore governors to their pre-modification settings.
 */
void cpufreq_restore(void);


#endif /* included */
