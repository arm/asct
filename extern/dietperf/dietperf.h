/***********************************************************************************
 * SPDX-FileCopyrightText: Copyright (C) 2025-2026 Arm Limited and/or its affiliates
 * SPDX-FileCopyrightText: <open-source-office@arm.com>
 * SPDX-License-Identifier: Apache-2.0
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
 * WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
 * License for the specific language governing permissions and limitations
 * under the License.
 **********************************************************************************/

/*
 *        _        _                    __
 *       | |_     | |                  / _|
 *     __| |_| ___| |_ _ __   ___ _ __| |_
 *    / _` | |/ _ \ __| '_ \ / _ \ '__|  _|
 *   | (_| | |  __/ |_| |_) |  __/ |  | |
 *    \__,_|_|\___|\__| .__/ \___|_|  |_|
 *                    | |
 *   dietperf         |_|
 *     a minimal header-only perf library
 *
 *  - see example.c for usage
 *  - library is NOT thread safe. calling public API functions from different
 *    threads for a single dietperf_ctx context is not supported
 *  - locking can be added with a mutex/lock around all internal
 *    __dietperf_ctx and external dietperf_ctx accesses
 *  - multiplexing aka supporting more counters than available hardware PMU
 *    slots is not implemented
 *      - to implement this, add PERF_FORMAT_TOTAL_TIME_RUNNING and compare to
 *        PERF_FORMAT_TOTAL_TIME_ENABLED
 *      - if these values differ, scale up values as appropriate
 *      - this will require removing PERF_FORMAT_GROUP or splitting counters
 *        into equal sized groups so they can be scheduled separately; since
 *        groups are scheduled as one block of counters, groups cannot contain
 *        more than the available pmu slots
 *
 *  TODO:
 *  - add a state to internal __ctx, e.g. running/stopped, currently you can
 *    call start twice in a row or stop before start, which doesn't make sense
 *  - use more decriptive custom error codes instead of the standard errno ones
 *
 */

/* START OF PUBLIC API */
#ifndef DIETPERF_H
#define DIETPERF_H

#include <errno.h>
#include <fcntl.h>
#include <linux/limits.h>
#include <linux/perf_event.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <unistd.h>

#define DIETPERF_MAX_PMUv3_EVENTS 7
// ^ 6x PMU counters + 1x CPU_CYCLE counters
// multiplexing of > 7 counters currently not enabled
#define DIETPERF_MAX_CMN_EVENTS 4
// for watchpoints, without wp_combine: 2x WP_UP + 2x WP_DOWN supported
//                     with wp_combine: 1x WP_UP + 1x WP_DOWN
#define DIETPERF_MAX_EVENTS 7 // max(MAX_PMUv3_EVENTS, MAX_CMN_EVENTS)
#define DIETPERF_MAX_DEVICES 2

struct __dietperf_ctx;

struct dietperf_cmn_event {
    uint64_t deviceid; // found in /sys/bus/event_source/devices/arm_cmn_N/type
    uint16_t type;
    uint16_t eventid;
    bool bynodeid;
    uint16_t nodeid;
    uint8_t occupid;

    uint8_t wp_dev_sel;
    uint8_t wp_chn_sel;
    uint8_t wp_grp;
    bool wp_exclusive;
    uint8_t wp_combine;
    uint64_t wp_val;
    uint64_t wp_mask;
};

struct dietperf_pmuv3 {
    uint16_t evlist[DIETPERF_MAX_PMUv3_EVENTS];
    uint8_t n_events;
    uint64_t values[DIETPERF_MAX_PMUv3_EVENTS];
    uint64_t time_enabled;
};

struct dietperf_cmn {
    struct dietperf_cmn_event evlist[DIETPERF_MAX_CMN_EVENTS];
    uint8_t n_events;
    uint64_t values[DIETPERF_MAX_CMN_EVENTS];
    uint64_t time_enabled;
};

struct dietperf_ctx {
    struct __dietperf_ctx *__ctx; // internal context/handle
    struct dietperf_pmuv3 pmu;
    struct dietperf_cmn cmn;
};

static inline int dietperf_parse_evlist(struct dietperf_ctx *ctx);
static inline int dietperf_init(struct dietperf_ctx *_ctx);
static inline int dietperf_destroy(struct dietperf_ctx *ctx);
static inline int dietperf_start(struct dietperf_ctx *ctx);
static inline int dietperf_stop(struct dietperf_ctx *ctx);
static inline int dietperf_reset(struct dietperf_ctx *ctx);
static inline int dietperf_set_outdir(struct dietperf_ctx *ctx,
                                      const char *outdir);
static inline int dietperf_write(struct dietperf_ctx *ctx);

#endif /* DIETPERF_H */
/* END OF PUBLIC API */

#ifndef __DIETPERF_IMPLEMENTATION_H
#define __DIETPERF_IMPLEMENTATION_H

#define dietperf_for_each_device(dev_ptr, __ctx)                               \
    for (struct __dietperf_device *dev_ptr = *(__ctx->devices);                \
         dev_ptr < *(__ctx->devices) + __ctx->n_devices; ++dev_ptr)

// Note: This format changes depending on perf_event_attr.read_format
// See `man perf_event_open`
struct __dietperf_read_format {
    uint64_t nr;
    uint64_t time_enabled; // PERF_FORMAT_TOTAL_TIME_ENABLED
    struct {
        uint64_t value;
        uint64_t id;               // PERF_FORMAT_ID
    } values[DIETPERF_MAX_EVENTS]; // PERF_FORMAT_GROUP
};

struct __dietperf_device {
    int fd[DIETPERF_MAX_EVENTS];      // fd[0] will be the group leader fd
    uint64_t id[DIETPERF_MAX_EVENTS]; // PERF_FORMAT_ID's
    struct perf_event_attr attr[DIETPERF_MAX_EVENTS];
    struct __dietperf_read_format results;
    uint8_t n_events;
    bool enabled;
};

struct __dietperf_output {
    bool enabled;
    int fd;
};

struct __dietperf_ctx {
    struct __dietperf_device pmu;
    struct __dietperf_device cmn;
    // once initialised, contains ptrs only to enabled devices
    struct __dietperf_device *devices[DIETPERF_MAX_DEVICES];
    uint8_t n_devices;
    struct __dietperf_output out;
};

static inline int __diet_perf_event_open(struct perf_event_attr *hw_event,
                                         pid_t pid, int cpu, int group_fd,
                                         uint64_t flags)
{
    return syscall(SYS_perf_event_open, hw_event, pid, cpu, group_fd, flags);
}

static inline void __diet_configure_event(struct perf_event_attr *pe,
                                          uint32_t type, uint64_t config,
                                          uint64_t config1, uint64_t config2)
{
    memset(pe, 0, sizeof(struct perf_event_attr));
    pe->type = type;
    pe->size = sizeof(struct perf_event_attr);
    pe->config = config;
    pe->read_format =
        PERF_FORMAT_GROUP | PERF_FORMAT_ID | PERF_FORMAT_TOTAL_TIME_ENABLED;
    pe->disabled = 1;
    pe->inherit = 0;
    pe->exclude_kernel =
        (pe->type == PERF_TYPE_RAW) ? 1 : 0; // only for RAW (PMU) events
    pe->exclude_hv =
        (pe->type == PERF_TYPE_RAW) ? 1 : 0; // only for RAW (PMU) events
    pe->config1 = config1;
    pe->config2 = config2;
}

static inline void __diet_pack_cmn_event(const struct dietperf_cmn_event *evt,
                                         struct perf_event_attr *pe)
{
    uint64_t cfg = 0;
    const uint64_t CMN_TYPE_MASK = 0xFFFFULL;
    const uint64_t CMN_EVENTID_MASK = 0x7FFULL;
    const uint64_t CMN_OCCUPID_MASK = 0xFULL;
    const uint64_t CMN_BYNODEID_BIT = (1ULL << 31);
    const uint64_t CMN_NODEID_MASK = 0xFFFFULL;
    const uint64_t CMN_TYPE_WATCHPOINT = 0x7770ULL;

    // core fields
    // bits [15:0] = cmn node type
    cfg |= ((uint64_t)evt->type & CMN_TYPE_MASK);
    // bits [26:16]  = eventid
    cfg |= ((uint64_t)evt->eventid & CMN_EVENTID_MASK) << 16;
    // bits [30:27] = occupid, but only for non-watchpoint events
    if ((cfg & CMN_TYPE_MASK) != CMN_TYPE_WATCHPOINT) {
        cfg |= ((uint64_t)evt->occupid & CMN_OCCUPID_MASK) << 27;
    }
    // bit 31 = bynodeid
    if (evt->bynodeid)
        cfg |= CMN_BYNODEID_BIT;
    // bits [47:32] = nodeid
    cfg |= ((uint64_t)evt->nodeid & CMN_NODEID_MASK) << 32;

    if ((cfg & CMN_TYPE_MASK) == CMN_TYPE_WATCHPOINT) {
        // bits [30:27]  = wp_combine (reuses the occupid bits)
        cfg |= ((uint64_t)evt->wp_combine & CMN_OCCUPID_MASK) << 27;
        // bits [50:48]  = wp_dev_sel
        cfg |= ((uint64_t)evt->wp_dev_sel & 0x7ULL) << 48;
        // bits [55:51]  = wp_chn_sel
        cfg |= ((uint64_t)evt->wp_chn_sel & 0x1FULL) << 51;
        // bits [57:56]  = wp_grp
        cfg |= ((uint64_t)evt->wp_grp & 0x3ULL) << 56;
        // bit  58       = wp_exclusive
        if (evt->wp_exclusive)
            cfg |= (1ULL << 58);
    }

    pe->config = cfg;
    pe->config1 = evt->wp_val;
    pe->config2 = evt->wp_mask;
}

/*
 * Populate ctx->cmn.evlist and ctx->cmn.n_events by parsing a comma separated
 * string in a similar format to `perf stat`:
 *
 *      arm_cmn_<n>/type=?,eventid=?,wp_dev_sel=?,wp_chn_sel=?,wp_grp=?,
 *      wp_val=?,wp_mask=?/
 *
 *      or
 *
 *      arm_cmn_<n>/eventid=?,type=?/
 *
 * where arm_cmn_<n> is the device/cmn mesh to be targeted and found at:
 *
 *      /sys/bus/event_source/devices/arm_cmn_<n>
 *
 * note: the kernel must be built with CONFIG_SYSFS and the sysfs mounted at
 *       /sys for this to work
 *
 * See `perf list --details` to see the encoding for various events.
 *
 */
static inline int __diet_parse_evlist_CMN(struct dietperf_ctx *ctx,
                                          char *evlist)
{
    int ret, fd, n_bytes;
    char *start, *opt_end, *opt_save;
    char *device_start, *device_end;
    const char *prefix = "/sys/bus/event_source/devices/";
    const char *suffix = "/type";
    char *type_start, *type_end;
    char path[64] = {0}; // 64 bytes should be more than enough
    char buf[64] = {0}; // we expect buf to be a few bytes, this is overkill
    uint64_t device_id;
    struct dietperf_cmn_event *evt;

    if (!evlist)
        return EINVAL;
    start = evlist;
    ctx->cmn.n_events = 0;

    do {
        errno = 0;
        if (*start == ',')
            start++;

        if (ctx->cmn.n_events + 1 > DIETPERF_MAX_CMN_EVENTS)
            return E2BIG;
        evt = &ctx->cmn.evlist[ctx->cmn.n_events];

        // first element is the cmn device name found at:
        //   /sys/bus/event_source/devices/arm_cmn_<n>/
        // this can be either arm_cmn_<n> or simply arm_cmn in some cases
        device_start = start;
        device_end = strchr(start, '/');
        if (!device_end)
            return EINVAL;
        *device_end = '\0';
        // the device id we need to pass in as a parameter to perf_event_open
        // syscall is found at:
        //   /sys/bus/event_source/devices/arm_cmn_<n>/type
        if ((strlen(prefix) + strlen(suffix) + strlen(device_start) + 1) >
            sizeof(path))
            return E2BIG;
        snprintf(path, sizeof(path), "%s%s%s", prefix, device_start, suffix);
        // open the type file in /sys and read the value as a char array
        fd = open(path, O_RDONLY | O_CLOEXEC);
        if (fd < 0)
            return errno;
        n_bytes = read(fd, &buf, sizeof(buf));
        if (n_bytes < 0) {
            close(fd);
            return errno;
        }
        // parse char array as an integer, it should be \n terminated
        type_start = buf;
        errno = 0; // strtoull does not reset errno on success
        device_id = strtoull(type_start, &type_end, 0);
        if (errno) {
            close(fd);
            return errno;
        }
        // failed to parse anything e.g. empty string, or leading invalid char
        if (type_start == type_end)
            return EINVAL;
        evt->deviceid = device_id;
        ret = close(fd);
        if (ret == -1)
            return errno;

        // we've got the target CMN device id, now parse the event parameters
        start = device_end + 1;
        // CMN option string must be terminated with a /
        opt_end = strchr(start, '/');
        if (!opt_end)
            return EINVAL;
        // isolate this CMN option by NULL terminating it
        *opt_end = '\0';

        opt_save = NULL;

        for (char *tok = strtok_r(start, ",", &opt_save); tok;
             tok = strtok_r(NULL, ",", &opt_save)) {
            char *eq = strchr(tok, '=');
            if (!eq)
                return EINVAL;

            *eq = '\0'; // lets key end at '=' symbol
            const char *key = tok;
            const char *val = eq + 1;

            errno = 0;
            uint64_t v = strtoull(val, NULL, 0);
            if (errno)
                return errno;

            if (strcmp(key, "type") == 0)
                evt->type = (uint16_t)v;
            else if (strcmp(key, "eventid") == 0)
                evt->eventid = (uint16_t)v;
            else if (strcmp(key, "bynodeid") == 0)
                evt->bynodeid = (v != 0);
            else if (strcmp(key, "nodeid") == 0)
                evt->nodeid = (uint16_t)v;
            else if (strcmp(key, "occupid") == 0)
                evt->occupid = (uint8_t)v;
            else if (strcmp(key, "wp_dev_sel") == 0)
                evt->wp_dev_sel = (uint8_t)v;
            else if (strcmp(key, "wp_chn_sel") == 0)
                evt->wp_chn_sel = (uint8_t)v;
            else if (strcmp(key, "wp_grp") == 0)
                evt->wp_grp = (uint8_t)v;
            else if (strcmp(key, "wp_exclusive") == 0)
                evt->wp_exclusive = (v != 0);
            else if (strcmp(key, "wp_combine") == 0)
                evt->wp_combine = (uint8_t)v;
            else if (strcmp(key, "wp_val") == 0)
                evt->wp_val = v;
            else if (strcmp(key, "wp_mask") == 0)
                evt->wp_mask = v;
        }

        *opt_end = '/';
        ctx->cmn.n_events++;
        // continue onto the next CMN option
        start = opt_end + 1;

    } while (*start != '\0');

    return 0;
}

/*
 * Populate ctx->pmu.evlist and ctx->pmu.n_events by parsing a CSV string of 16
 * bit hex raw perf event ids
 *
 * e.g. "0x1,0x3,0x8" ->
 *      ctx->pmu.evlist = [0x1, 0x3, 0x8];
 *      ctx->pmu.n_events = 3;
 */
static inline int __diet_parse_evlist_PMUv3(struct dietperf_ctx *ctx,
                                            char *evlist)
{
    char *start = evlist;
    char *end;
    ctx->pmu.n_events = 0;
    errno = 0;
    do {
        uint64_t n = strtoull(start, &end, 16);
        if (errno == ERANGE || n > 0xFFFF) // event codes are 16 bit max
            return ERANGE;
        // failed to parse anything e.g. empty string, or leading invalid char
        if (end == start)
            return EINVAL;
        if (errno == 0 && n == 0) // 0 is an invalid event code
            return EINVAL;

        ctx->pmu.n_events++;
        if (ctx->pmu.n_events > DIETPERF_MAX_PMUv3_EVENTS)
            return E2BIG;
        else
            ctx->pmu.evlist[ctx->pmu.n_events - 1] = (uint16_t)n;

        if (*end == ',')
            start = end + 1;   // next item
        else if (*end == '\0') // end of CSV string
            break;
        else // invalid character/delimiter
            return EINVAL;
    } while (*end != '\0');

    return 0;
}

static inline int __diet_create_perf_group(struct __dietperf_device *dev,
                                           int pid, int cpu)
{
    int ret = 0;

    // create event group leader by passing -1 as group_fd
    dev->fd[0] = __diet_perf_event_open(&dev->attr[0], pid, cpu, -1, 0);
    if (dev->fd[0] == -1) {
        return errno;
    }
    ret = ioctl(dev->fd[0], PERF_EVENT_IOC_ID, &dev->id[0]);
    if (ret == -1) {
        return errno;
    }

    // create the rest of the event group using fd[0] as the group leader
    for (int i = 1; i < dev->n_events; i++) {
        dev->fd[i] =
            __diet_perf_event_open(&dev->attr[i], pid, cpu, dev->fd[0], 0);
        if (dev->fd[i] == -1) {
            return errno;
        }
        ret = ioctl(dev->fd[i], PERF_EVENT_IOC_ID, &dev->id[i]);
        if (ret == -1) {
            return errno;
        }
    }

    return 0;
}

static inline int dietperf_parse_evlist(struct dietperf_ctx *ctx)
{
    int ret;

    if (!ctx)
        return EFAULT;

    memset(ctx, 0, sizeof(*ctx));

    const char *cmn_evlist = getenv("DIETPERF_CMN");
    if (cmn_evlist) {
        if (!*cmn_evlist)
            return EINVAL;
        // copy the string so we don't mutate callers env while parsing
        char *copy = strdup(cmn_evlist);
        if (!copy)
            return ENOMEM;
        ret = __diet_parse_evlist_CMN(ctx, copy);
        free(copy);
        if (ret)
            return ret;
    }

    char *pmu_evlist = getenv("DIETPERF_PMUv3");
    if (pmu_evlist) {
        ret = __diet_parse_evlist_PMUv3(ctx, pmu_evlist);
        if (ret)
            return ret;
    }

    if (!pmu_evlist && !cmn_evlist)
        return EINVAL;

    return 0;
}

static inline int dietperf_init(struct dietperf_ctx *ctx)
{
    int ret = 0;
    struct __dietperf_ctx *__ctx;
    struct __dietperf_device *__pmu;
    struct __dietperf_device *__cmn;

    if (!ctx)
        return EFAULT;

    if (ctx->pmu.n_events == 0 && ctx->cmn.n_events == 0)
        return EINVAL;

    if (ctx->pmu.n_events > DIETPERF_MAX_PMUv3_EVENTS ||
        ctx->cmn.n_events > DIETPERF_MAX_CMN_EVENTS)
        return EINVAL;

    // allocate and init internal state/context; store the ref in the external
    // user struct
    ctx->__ctx =
        (struct __dietperf_ctx *)calloc(1, sizeof(struct __dietperf_ctx));
    if (!ctx->__ctx)
        return errno;
    __ctx = ctx->__ctx;

    __pmu = &__ctx->pmu;
    if (ctx->pmu.n_events) {
        __pmu->enabled = true;
        __pmu->n_events = ctx->pmu.n_events;
        // only add to the list of devices if enabled
        __ctx->devices[__ctx->n_devices] = __pmu;
        __ctx->n_devices++;
    }

    __cmn = &__ctx->cmn;
    if (ctx->cmn.n_events) {
        __cmn->enabled = true;
        __cmn->n_events = ctx->cmn.n_events;
        __ctx->devices[__ctx->n_devices] = __cmn;
        __ctx->n_devices++;
    }

    // configure and setup PMUv3 group
    if (__pmu->enabled) {
        for (int i = 0; i < __pmu->n_events; i++)
            __diet_configure_event(&__pmu->attr[i], PERF_TYPE_RAW,
                                   ctx->pmu.evlist[i], 0, 0);
        // pid == 0 and cpu == -1 measures the calling process/thread on any CPU
        ret = __diet_create_perf_group(__pmu, 0, -1);
        if (ret) {
            goto err;
        }
    }

    // configure and setup CMN event group
    if (__cmn->enabled) {
        for (int i = 0; i < __cmn->n_events; i++) {
            // pack config, config1, and config2
            const struct dietperf_cmn_event *e = &ctx->cmn.evlist[i];
            __diet_pack_cmn_event(e, &__cmn->attr[i]);
            __diet_configure_event(
                &__cmn->attr[i], e->deviceid, __cmn->attr[i].config,
                __cmn->attr[i].config1, __cmn->attr[i].config2);
        }
        // pid == -1 and cpu == 0 measures all processes/threads on CPU0. CMN
        // is uncore so any CPU should work.
        ret = __diet_create_perf_group(__cmn, -1, 0);
        if (ret) {
            goto err;
        }
    }

    // reset all groups
    dietperf_for_each_device(dev, __ctx)
    {
        ret = ioctl(dev->fd[0], PERF_EVENT_IOC_RESET, PERF_IOC_FLAG_GROUP);
        if (ret == -1) {
            goto err;
        }
    }

    return ret;

err:
    dietperf_destroy(ctx);
    return ret;
}

static inline int dietperf_destroy(struct dietperf_ctx *ctx)
{
    if (!ctx)
        return EFAULT;

    if (!ctx->__ctx)
        return EOWNERDEAD;

    dietperf_for_each_device(dev, ctx->__ctx)
    {
        for (int i = 0; i < dev->n_events; i++) {
            close(dev->fd[i]);
        }
    }

    free(ctx->__ctx);
    // to avoid use-after-free, invalidate internal ctx/handle for future calls
    ctx->__ctx = NULL;

    return 0;
}

static inline int dietperf_start(struct dietperf_ctx *ctx)
{
    int ret = 0;

    if (!ctx)
        return EFAULT;

    if (!ctx->__ctx)
        return EOWNERDEAD;

    dietperf_for_each_device(dev, ctx->__ctx)
    {
        ret = ioctl(dev->fd[0], PERF_EVENT_IOC_ENABLE, PERF_IOC_FLAG_GROUP);
        if (ret == -1) {
            dietperf_destroy(ctx);
            return errno;
        }
    }

    return 0;
}

// accumulates values if dietperf_reset() is not called
#define dietperf_copy_vals_to_user(dev)                                        \
    do {                                                                       \
        ctx->dev.time_enabled = __ctx->dev.results.time_enabled;               \
        for (uint64_t i = 0; i < __ctx->dev.results.nr; i++) {                 \
            for (int j = 0; j < __ctx->dev.n_events; j++) {                    \
                if (__ctx->dev.results.values[i].id == __ctx->dev.id[j]) {     \
                    ctx->dev.values[i] += __ctx->dev.results.values[i].value;  \
                    break;                                                     \
                }                                                              \
            }                                                                  \
        }                                                                      \
    } while (0)

static inline int dietperf_stop(struct dietperf_ctx *ctx)
{
    int ret;
    struct __dietperf_ctx *__ctx = ctx->__ctx;

    if (!ctx)
        return EFAULT;

    if (!ctx->__ctx)
        return EOWNERDEAD;

    dietperf_for_each_device(dev, __ctx)
    {
        ret = ioctl(dev->fd[0], PERF_EVENT_IOC_DISABLE, PERF_IOC_FLAG_GROUP);
        if (ret == -1) {
            goto err;
        }
    }

    dietperf_for_each_device(dev, __ctx)
    {
        ret = read(dev->fd[0], &dev->results,
                   sizeof(struct __dietperf_read_format));
        if (ret == -1) {
            goto err;
        }
    }

    /*
     * The external/user structs for dietperf_pmuv3 and dietperf_cmn are
     * different types, so we can't access the dietperf_{pmuv3,cmn}->values with
     * dietperf_for_each_device() in a generic way without some horrendous
     * hacks. Just manually iterate through each device here until someone comes
     * up with a better idea.
     */
    dietperf_copy_vals_to_user(pmu);
    dietperf_copy_vals_to_user(cmn);

    return 0;

err:
    dietperf_destroy(ctx);
    return errno;
}

static inline int dietperf_reset(struct dietperf_ctx *ctx)
{
    int ret;
    struct __dietperf_ctx *__ctx = ctx->__ctx;

    if (!ctx)
        return EFAULT;

    if (!ctx->__ctx)
        return EOWNERDEAD;

    // zero internal counters
    memset(ctx->pmu.values, 0, sizeof(ctx->pmu.values));
    memset(ctx->cmn.values, 0, sizeof(ctx->cmn.values));

    // reset PMU counters
    dietperf_for_each_device(dev, __ctx)
    {
        ret = ioctl(dev->fd[0], PERF_EVENT_IOC_RESET, PERF_IOC_FLAG_GROUP);
        if (ret == -1) {
            dietperf_destroy(ctx);
            return errno;
        }
    }

    return ret;
}

static inline int dietperf_set_outdir(struct dietperf_ctx *ctx, const char *dir)
{
    struct __dietperf_ctx *__ctx = ctx->__ctx;
    struct stat st;
    char path[PATH_MAX];
    char dir_path[PATH_MAX];
    uint64_t dir_len, max_len;
    pid_t tid;
    uint32_t cpu;
    int ret;
    char cwd = '.';

    if (!ctx)
        return EFAULT;

    if (!ctx->__ctx)
        return EOWNERDEAD;

    // caller can pass in NULL for dir + set dir via an env var instead
    if (!dir) {
        dir = getenv("DIETPERF_OUTDIR");
        if (!dir) // no dir passed, use cwd
            dir = &cwd;
    }

    // we already have an open fd, assume the caller wants to change the
    // output dir, so close existing fd and attempt to open a new one
    if (__ctx->out.fd) {
        ret = close(__ctx->out.fd);
        __ctx->out.enabled = 0;
        if (ret == -1)
            return errno;
    }

    errno = 0;
    // if dir doesn't exist, try and create it - however we can only create a
    // directory one level deep, this is not recursive like the `mkdir -p`
    // command and will fail if parent dirs don't exist
    if ((stat(dir, &st) == -1) && errno == ENOENT) {
        ret = mkdir(dir, 0777);
        if (ret == -1)
            return errno;
    } else if (errno)
        return errno;

    // get the full path if caller passed relative
    if (realpath(dir, dir_path) == NULL)
        return errno;
    max_len = (PATH_MAX - NAME_MAX);
    dir_len = strnlen(dir_path, max_len) + 1;
    if (dir_len > max_len)
        return E2BIG;

    // filename is directory/cpuid_tid
    ret = syscall(SYS_getcpu, &cpu, NULL, NULL);
    if (ret == -1)
        return errno;
    tid = syscall(SYS_gettid); // gettid() cannot fail
    ret = snprintf(path, PATH_MAX, "%s/%u_%u", dir_path, cpu, tid);
    if (ret > PATH_MAX)
        return E2BIG;
    if (ret < 0)
        return ret;

    // if the file exists, O_TRUNC will clear the file and start writing from
    // offset 0
    // O_APPEND ensures that each call to dietperf_write() will append the
    // latest values to the end of the file
    __ctx->out.fd =
        open(path, O_CREAT | O_TRUNC | O_APPEND | O_RDWR | O_CLOEXEC, 0666);
    if (__ctx->out.fd < 0)
        return errno;

    __ctx->out.enabled = 1;

    return 0;
}

static inline int dietperf_write(struct dietperf_ctx *ctx)
{
    int ret = 0;
    const uint8_t entry_len = 255;
    struct __dietperf_ctx *__ctx = ctx->__ctx;

    if (!ctx)
        return EFAULT;

    if (!ctx->__ctx)
        return EOWNERDEAD;

    if (!__ctx->out.enabled || __ctx->out.fd < 0)
        return EINVAL;

    if (!ctx->pmu.n_events && !ctx->cmn.n_events)
        return EINVAL;

    errno = 0;
    for (int i = 0; i < ctx->pmu.n_events; i++) {
        char entry[entry_len];
        // format is: event_id,value,time_enabled
        snprintf(entry, entry_len, "%#06x,%lu,%lu\n", ctx->pmu.evlist[i],
                 ctx->pmu.values[i], ctx->pmu.time_enabled);
        ret = write(__ctx->out.fd, entry, strlen(entry));
        if (ret == -1)
            return errno;
    }

    for (int i = 0; i < ctx->cmn.n_events; i++) {
        char entry[entry_len];
        // format is: wp_val,wp_dev_sel,value,time_enabled
        // TODO: needs adjusting for non-watchpoint events
        snprintf(entry, entry_len, "%#lx,%u,%lu,%lu\n",
                 ctx->cmn.evlist[i].wp_val, ctx->cmn.evlist[i].wp_dev_sel,
                 ctx->cmn.values[i], ctx->cmn.time_enabled);
        ret = write(__ctx->out.fd, entry, strlen(entry));
        if (ret == -1)
            return errno;
    }

    return 0;
}

#endif /* DIETPERF_IMPLEMENTATION_H */
