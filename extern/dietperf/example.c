/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include <assert.h>
#include <stdio.h>

#include "dietperf.h"

void workload();
void print_values(struct dietperf_ctx *ctx);
int basic_usage(void);
int env_var_usage(void);
int output_to_file_usage(void);
int test_call_after_destroy(void);

int main()
{
    int ret = 0;

    /* There are two ways to specify events to collect:
     *
     * 1. Manually create a dietperf_ctx struct, fill out evlists + n_events
     */
    ret = basic_usage();
    printf("basic_usage() return code: %d\n", ret);

    /*
     * 2. Create an empty/zero'd dietperf_ctx struct and populate it based on
     *    the values in the environment variables DIETPERF_PMUv3/DIETPERF_CMN
     */
    ret = env_var_usage();
    printf("env_var_usage() return code: %d\n", ret);

    /*
     * Values can be saved to CSV file
     */
    ret = output_to_file_usage();
    printf("output_to_file_usage() return code: %d\n", ret);

    /*
     * Tests
     */
    ret = test_call_after_destroy();
    assert(ret == EOWNERDEAD);

    return 0;
}

int basic_usage(void)
{
    int ret = 0;

    // Create a dietperf_ctx struct, fill out evlists + n_events
    struct dietperf_ctx ctx = {
        .pmu.evlist = {0x1, 0x11, 0x8}, // PMUv3 hex codes
        .pmu.n_events = 3,
        .cmn.evlist =
            {
                {
                    // .deviceid from /sys/bus/event_source/devices/arm_cmn/type
                    .deviceid = 0x4c,
                    .type = 0x7770,    // watchpoint type
                    .eventid = 0,      // if type is WP, eventid must be
                                       // WP_UP (0) or WP_DOWN (2)
                    .bynodeid = false, // not filtering by node
                    .nodeid = 0,       // unused
                    .occupid = 0,      // only for non-WP events

                    .wp_dev_sel = 0,
                    .wp_chn_sel = 0,
                    .wp_grp = 0,
                    .wp_exclusive = false,
                    .wp_combine = 0, // default
                    .wp_val = 0x200000000ULL,
                    .wp_mask = 0xffffffe07fffffffULL,
                },
                {
                    .deviceid = 0x4c,
                    .type = 0x7770,
                    .eventid = 0,
                    .bynodeid = false, // not filtering by node
                    .nodeid = 0,       // unused
                    .occupid = 0,      // only for non-WP events

                    .wp_dev_sel = 1,
                    .wp_chn_sel = 0,
                    .wp_grp = 0,
                    .wp_exclusive = false,
                    .wp_combine = 0, // default
                    .wp_val = 0x200000000ULL,
                    .wp_mask = 0xffffffe07fffffffULL,
                },
            },
        .cmn.n_events = 2,
    };

    ret = dietperf_init(&ctx);
    if (ret)
        return ret;

    ret = dietperf_start(&ctx);
    if (ret)
        return ret;

    workload();

    ret = dietperf_stop(&ctx);
    if (ret)
        return ret;

    print_values(&ctx);

    /*
     * Counters are accumulating unless you use dietperf_reset() to reset them
     * back to zero. That is, you can start and stop multiple times and the
     * values will accumulate in dietperf_ctx->device_type.values
     */
    ret = dietperf_reset(&ctx);
    if (ret)
        return ret;

    ret = dietperf_destroy(&ctx);
    if (ret)
        return ret;

    return ret;
}

int env_var_usage(void)
{
    int ret = 0;
    struct dietperf_ctx ctx = {0};

    /*
     *    Use environment variables to select counters for measuring. Allows
     *    changing counters on an instrumented binary without re-compilation.
     *
     *    Create an empty/zero'd dietperf_ctx struct and populate it based on
     *    the values in the environment variables DIETPERF_PMUv3/DIETPERF_CMN
     *
     *    DIETPERF_PMUv3 should be set to a comma separated list of raw hex
     *    event codes e.g.
     *
     *      DIETPERF_PMUv3=0x1,0x8,0x11
     *
     *    DIETPERF_CMN is set to the same as the string that would be provided
     *    to the perf tool stat command e.g.
     *
     *      perf stat -e arm_cmn_0/type=0x7770,eventid=0x2,wp_dev_sel=1,
     *      wp_chn_sel=0,wp_grp=0,wp_val=0x200000000,wp_mask=0xffffffe07fffffff/
     *
     *    where arm_cmn_0 is the device/cmn mesh to be targeted and found at:
     *
     *      /sys/bus/event_source/devices/arm_cmn_<n>
     *
     *    Each CMN event should be terminated with a '/' and multiple events can
     *    be comma separated e.g.
     *
     *      DIETPERF_CMN=arm_cmn_0/type=0x7770,eventid=0x2,wp_dev_sel=1,
     *      wp_chn_sel=0,wp_grp=0,wp_val=0x200000000,
     *      wp_mask=0xffffffe07fffffff/,arm_cmn_1/type=0xa,eventid=0xc/
     *
     *    See `perf list --details` to see the encoding for various events
     *
     *    dietperf_parse_evlist() will parse both environment variables (if they
     *    exist) and populate dietperf_ctx with the relevant info
     */
    ret = dietperf_parse_evlist(&ctx);
    if (ret)
        return ret;

    ret = dietperf_init(&ctx);
    if (ret)
        return ret;

    ret = dietperf_start(&ctx);
    if (ret)
        return ret;

    workload();

    ret = dietperf_stop(&ctx);
    if (ret)
        return ret;

    print_values(&ctx);

    ret = dietperf_destroy(&ctx);
    if (ret)
        return ret;

    return ret;
}

int output_to_file_usage(void)
{
    int ret = 0;
    struct dietperf_ctx ctx = {0};

    ret = dietperf_parse_evlist(&ctx);
    if (ret)
        return ret;

    ret = dietperf_init(&ctx);
    if (ret)
        return ret;

    /*
     * To output values in CSV format into a file, specify the output directory
     * or use NULL to use current working directory:
     *     ret = dietperf_set_outdir(&ctx, NULL);
     *     ret = dietperf_set_outdir(&ctx, "relative/path");
     *     ret = dietperf_set_outdir(&ctx, "/full/path/to/outdir/");
     *
     * A value of NULL will also check the DIETPERF_OUTDIR environment varable
     * and use that if it exists, otherwise the current working directory will
     * be used
     *
     * Must be called AFTER dietperf_init()
     *
     * dietperf will attempt to create the directory if it doesn't exist, but
     * will not recursively create parent directories - this call will fail if
     * parent directories do not exist
     *
     * This call just configures the output file. To write the values to file,
     * see dietperf_write()
     */
    ret = dietperf_set_outdir(&ctx, "outdir");
    if (ret)
        printf("dietperf: failed to set output dir\n");

    ret = dietperf_start(&ctx);
    if (ret)
        return ret;

    workload();

    ret = dietperf_stop(&ctx);
    if (ret)
        return ret;

    print_values(&ctx);

    /*
     * Call to dietperf_write will write the values from
     * dietperf_ctx->device_type.values to file in CSV format
     *
     * Subsequent calls will append the values to the same file
     */
    ret = dietperf_write(&ctx);
    if (ret)
        printf("dietperf: failed to write output file\n");

    /*
     * Counters are accumulating unless you use dietperf_reset() to reset them
     * back to zero. That is you can start and stop multiple times and the
     * values will accumulate in dietperf_ctx->device_type.values
     */
    ret = dietperf_reset(&ctx);
    if (ret)
        return ret;

    ret = dietperf_start(&ctx);
    if (ret)
        return ret;

    workload();

    ret = dietperf_stop(&ctx);
    if (ret)
        return ret;

    ret = dietperf_write(&ctx);
    if (ret)
        printf("dietperf: failed to write output dir\n");

    ret = dietperf_destroy(&ctx);
    if (ret)
        return ret;

    return ret;
}

int test_call_after_destroy(void)
{
    int ret = 0;

    struct dietperf_ctx ctx = {
        .pmu.evlist = {0x1, 0x11, 0x8}, // PMUv3 hex codes
        .pmu.n_events = 3,
    };

    ret = dietperf_init(&ctx);
    if (ret)
        return ret;

    ret = dietperf_start(&ctx);
    if (ret)
        return ret;

    workload();

    ret = dietperf_stop(&ctx);
    if (ret)
        return ret;

    ret = dietperf_destroy(&ctx);
    if (ret)
        return ret;

    /*
     * Calling an API function after dietperf_destroy() should fail returning
     * error code 130 EOWNERDEAD - context has been destroyed
     */
    ret = dietperf_start(&ctx);
    if (ret)
        return ret;

    return ret;
}

void print_values(struct dietperf_ctx *ctx)
{
    printf("---------------------------\n");
    printf("PMUv3 time_enabled: %lu\n", ctx->pmu.time_enabled);
    for (int i = 0; i < ctx->pmu.n_events; i++) {
        printf("%#x: %lu\n", ctx->pmu.evlist[i], ctx->pmu.values[i]);
    }

    printf("CMN time_enabled: %lu\n", ctx->cmn.time_enabled);
    for (int i = 0; i < ctx->cmn.n_events; i++) {
        printf("%#lx,dev=%d: %lu\n", ctx->cmn.evlist[i].wp_val,
               ctx->cmn.evlist[i].wp_dev_sel, ctx->cmn.values[i]);
    }
    printf("---------------------------\n");
}

#define NOP_1 asm volatile("nop");
#define NOP_4 NOP_1 NOP_1 NOP_1 NOP_1
#define NOP_16 NOP_4 NOP_4 NOP_4 NOP_4
#define NOP_64 NOP_16 NOP_16 NOP_16 NOP_16
#define NOP_256 NOP_64 NOP_64 NOP_64 NOP_64
#define NOP_1024 NOP_256 NOP_256 NOP_256 NOP_256
void workload(void)
{
    // 2048 nops
    NOP_1024;
    NOP_1024;
}
