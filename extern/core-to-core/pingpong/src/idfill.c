/*
 * Copyright (C) Arm Ltd. 2025. All rights reserved.
 */

#include <assert.h>

#include "idfill.h"

#include "vatopa.h"
#include "crc32.h"

#include <string.h>
#include <stdio.h>
#include <unistd.h>


int idfill_fill(void *base, size_t size, char const *sig, int with_pa)
{
    int pa_not_available = 0;
    unsigned long const page_size = sysconf(_SC_PAGESIZE);
    unsigned char *p;
    idfill_t st;
    assert((uint64_t)base % page_size == 0);
    assert(size % page_size == 0);
    assert(sizeof st == 64);
    strcpy(st.sig, "FILL");
    if (sig) {
        strncpy(st.sig+4, sig, sizeof st.sig-5);
    }
    for (p = base; p < (unsigned char *)base+size; p += page_size) {
        unsigned int lno;
        /* Force this page to be allocated and receive a PA */
        *(unsigned char volatile *)p = 'x';
        uint64_t page_pa;
        if (with_pa) {
            /* We shouldn't need barriers, as vatopa() contains system calls,
               which will serialize */
            page_pa = vatopa(p);
            if (page_pa == 0) {
                pa_not_available = 1;
            }
        } else {
            page_pa = 0;
        }
        for (lno = 0; lno < page_size; lno += 64) {
            st.va0 = st.va1 = (uint64_t)(p+lno);
            st.pa0 = st.pa1 = with_pa ? (page_pa + lno) : 0;
            st.checksum = 0;
            st.checksum = crc32_buffer(0, &st, sizeof st);
            memcpy(p+lno, &st, sizeof st);
        }
    }
    return pa_not_available ? IDFILL_NO_PA : 0;
}


int idfill_validate(idfill_t const *stp)
{
    idfill_t st;
    if (stp->va0 != stp->va1 || stp->pa0 != stp->pa1) {
        return IDFILL_MISMATCH;
    }
    st = *stp;
    st.checksum = 0;
    if (crc32_buffer(CRC32_INIT, &st, sizeof st) != stp->checksum) {
        return IDFILL_CRC;
    }
    if ((uint64_t)stp != stp->va0) {
        return IDFILL_MOVED;
    }
    return IDFILL_OK;
}
