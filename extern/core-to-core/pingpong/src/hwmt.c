/*
 * Copyright (C) Arm Ltd. 2025. All rights reserved.
 */

#include "hwmt.h"

#include <stdio.h>
#include <string.h>

static char const *const smt_control = "/sys/devices/system/cpu/smt/control";

static int g_not_implemented = 0;

int hwmt_status(void)
{
    if (g_not_implemented) {
        return HWMT_NOTIMPLEMENTED;
    }
    int rc = HWMT_ERROR;
    char s[20];
    FILE *fd = fopen(smt_control, "r");
    if (!fd) {
        return HWMT_ERROR;
    }
    rc = fread(s, 1, sizeof s, fd);
    if (rc <= 0) {
        /* didn't read anything */
    } if (!strncmp(s, "off", 3)) {
        rc = HWMT_OFF;
    } else if (!strncmp(s, "on", 2)) {
        rc = HWMT_ON;
    } else if (!strncmp(s, "notimplemented", 14)) {
        rc = HWMT_NOTIMPLEMENTED;
        g_not_implemented = 1;
    } 
    fclose(fd);
    return rc;
}


static int hwmt_write_control(char const *s)
{
    FILE *fd = fopen(smt_control, "w");
    if (!fd) {
        return HWMT_ERROR;
    }
    fwrite(s, 1, strlen(s), fd);
    fclose(fd);
    return 0;
}


int hwmt_set(int x)
{
    if (g_not_implemented) {
        return (x == HWMT_OFF) ? HWMT_OFF : HWMT_NOTIMPLEMENTED;
    } else if (x == HWMT_ON || x == HWMT_OFF) {
        return hwmt_write_control((x == HWMT_ON) ? "on" : "off");
    } else {
        return HWMT_ERROR;
    }
}
