/*
 * Copyright (C) Arm Ltd. 2025. All rights reserved.
 */
#include "gettid.h"

#include <sys/syscall.h>

pid_t _private_gettid(void)
{
    return (pid_t)syscall(SYS_gettid);
}

