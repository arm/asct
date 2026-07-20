/*
 * Copyright (C) Arm Ltd. 2025. All rights reserved.
 *
 * Define gettid() in case C library doesn't provide it
 */

#ifndef __included_gettid_h
#define __included_gettid_h

#include <unistd.h>

extern pid_t _private_gettid(void);
#undef gettid
#define gettid() _private_gettid()

#endif /* included */
