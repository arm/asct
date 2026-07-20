/*
 * Copyright (C) Arm Ltd. 2025. All rights reserved.
 *
 * Enable/disable hardware multithreading dynamically.
 *
 * Currently uses the global control:
 *   /sys/devices/system/cpu/smt/control
 *
 * This works by taking logical CPUs offline in the OS.
 *
 * Older kernels don't support this global control.
 * Currently we don't try to work around that.
 */

#ifndef __included_hwmt_h
#define __included_hwmt_h

/*
 * Return hardware multithreading status
 *
 * Corresponding to strings in /sys/devices/system/cpu/smt/control
 */
#define HWMT_ON               1
#define HWMT_OFF              0
#define HWMT_NOTIMPLEMENTED  -1
#define HWMT_ERROR           -2
int hwmt_status(void);


/*
 * Set a new hardware multithreading status.
 */
int hwmt_set(int);

#endif /* included */
