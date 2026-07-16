/* 
 * Copyright (C) Arm Ltd. 2025. All rights reserved.
 *
 * Fast CRC32 implementations using standard C operations 
 */

#include "crc32.h"

#include <assert.h>

uint32_t c_crc32b(uint32_t crc, uint8_t byte)
{
    uint32_t x, x01, x012, t1;
    crc = crc ^ byte;
    x = (crc ^ (crc << 6)) << 24;
    x01 = (x ^ (x >> 1));
    crc = (crc >> 8);
    x012 = (x01 ^ (x >> 2));
    t1 = (x012 ^ (x012 >> 6));
    return crc ^ (x >> 26) ^ (x >> 16) ^ (x01 >> 22) ^ t1 ^ (t1 >> 4);
}


uint32_t c_crc32h(uint32_t crc, uint16_t hword)
{
    uint32_t x, x01, x012, t1;
    crc = crc ^ hword;
    x = (crc ^ (crc << 6) ^ (crc << 9) ^ (crc << 10) ^ (crc << 12)) << 16;
    x01 = (x ^ (x >> 1));
    crc = (crc >> 16);
    x012 = (x01 ^ (x >> 2));
    t1 = (x012 ^ (x012 >> 6));
    return crc ^ (x >> 26) ^ (x >> 16) ^ (x01 >> 22) ^ t1 ^ (t1 >> 4);
}


uint32_t c_crc32w(uint32_t crc, uint32_t word)
{
    uint32_t x, x0, f6, f2, f3, x01, x012, t1;
    x0 = crc ^ word;
    f6 = (x0 ^ (x0 << 6));
    f2 = (x0 ^ (x0 << 1));
    f3 = (f2 ^ (x0 << 2));
    x = f6 ^ (f6 << 10) ^ (x0 << 9) ^ (x0 << 12) ^ (f3 << 24) ^
             (f3 << 28) ^ (x0 << 31);
    x01 = (x ^ (x >> 1));
    x012 = (x01 ^ (x >> 2));
    t1 = (x012 ^ (x012 >> 6));
    crc = (x >> 26) ^ (x >> 16) ^ (x01 >> 22) ^ t1 ^ (t1 >> 4);
    return crc;
}


uint32_t c_crc32d(uint32_t crc, uint64_t word)
{
    uint64_t xl, x0, f6, f2, f3, f4;
    uint32_t x, x01, x012, t1;
    x0 = crc ^ word;
    f6 = (x0 ^ (x0 << 6));
    f2 = (x0 ^ (x0 << 1));
    f3 = (f2 ^ (x0 << 2));
    f4 = (f2 ^ (x0 << 3));
    xl = f6 ^ (f6 << 10) ^ (x0 << 9) ^ (x0 << 12) ^ (f3 << 24) ^
      (f3 << 28) ^ (f4 << 31) ^ (x0 << 37) ^ (f2 << 44) ^ (f4 << 47) ^
                (f3 << 53) ^ (x0 << 58) ^ (f4 << 60);
    x = (xl >> 32);
    x01 = (x ^ (x >> 1));
    x012 = (x01 ^ (x >> 2));
    t1 = (x012 ^ (x012 >> 6));
#if 0
    crc = (x >> 58) ^ (x >> 48) ^ (x01 >> 54) ^ (t1 >> 32) ^ (t1 >> 36);
#else
    crc = (x >> 26) ^ (x >> 16) ^ (x01 >> 22) ^ t1 ^ (t1 >> 4);
#endif
    return crc;
}


/*
 * Buffer CRC32. To match zlib etc., the input and output CRC are
 * both inverted i.e. XORed with 0xffffffff.
 */
uint32_t crc32_buffer(uint32_t crc, void const *buf, size_t size)
{
    uint8_t const *pb = (uint8_t const *)buf;
    crc ^= 0xffffffff;
#if 1
    uint64_t const *pd;
    while (size > 0 && ((uintptr_t)pb % 8)) {
        crc = crc32b(crc, *pb++);
        --size;
    }
    if (size > 0) {
        pd = (uint64_t const *)pb;
        while (size >= 8) {
            crc = crc32d(crc, *pd++);
            size -= 8;
        }
        pb = (uint8_t const *)pd;
    }
#endif
    while (size > 0) {
        crc = crc32b(crc, *pb++);
        --size;
    }
    return crc ^ 0xffffffff;
}


#ifdef CRC32_TEST

#include <stdio.h>
#include <string.h>
#include <stdlib.h>

static uint32_t crc32_rand32(void)
{
    static uint32_t k = 0;
    return crc32w(0, ++k);
}


static uint64_t crc32_rand64(void)
{
    uint64_t x = crc32_rand32();
    return (x << 32) | crc32_rand32();
}


static uint32_t hash_uint32(uint32_t n)
{
    return crc32w(0, n) >> 8;
}


int main(void)
{
    int n_fails = 0;
    static union {
        unsigned char b[64];
        uint64_t d[8];
    } buf;
    int i;
    for (i = 0; i < 10; ++i) {
        uint64_t x = crc32_rand64();
        uint32_t crc = 0;
        uint32_t crc_b = c_crc32b(crc, x);
        uint32_t crc_h = c_crc32h(crc, x);
        uint32_t crc_w = c_crc32w(crc, x);
        uint32_t crc_x = c_crc32d(crc, x);
        uint32_t crc_b2 = __crc32b(crc, x);
        uint32_t crc_h2 = __crc32h(crc, x);
        uint32_t crc_w2 = __crc32w(crc, x);
        uint32_t crc_x2 = __crc32d(crc, x);
        printf("0x%016llx: %08x/%08x %08x/%08x %08x/%08x %08x/%08x",
            (unsigned long long)x,
            crc_b, crc_b2, crc_h, crc_h2, crc_w, crc_w2, crc_x, crc_x2);
        if (crc_b != crc_b2 || crc_h != crc_h2 || crc_w != crc_w2 || crc_x != crc_x2) {
            printf(" *mismatch*");
            ++n_fails;
        }
        printf("\n");
    }
    for (i = 0; i < sizeof buf.d / sizeof buf.d[0]; ++i) {
        buf.d[i] = crc32_rand64();
    }
    printf("random:");
    for (i = 0; i < 4; ++i) {
        printf(" %016llx", (unsigned long long)buf.d[i]);
    }
    printf("\n");
    printf("  %08x\n", crc32_buffer(0, buf.b, 32));
    printf("  %08x\n", crc32_buffer(crc32_buffer(0, buf.b, 13), buf.b+13, 19));
    printf("  %08x\n", crc32_buffer(crc32_buffer(crc32_buffer(0, buf.b, 11), buf.b+11, 7), buf.b+18, 14));
    struct tcs {
        char const *str;
        uint32_t expected;
    } const strs[] = {
        { "test",         0xd87f7e0c },
        { "hello world",  0x0d4a1185 },
        { "1234",         0x9be3e0a3 },
        { NULL, 0 }
    };
    for (struct tcs const *p = strs; p->str != NULL; ++p) {
        uint32_t c = crc32_buffer(0, p->str, strlen(p->str));
        printf("%20s: %08x %08x\n", p->str, c, p->expected);
        if (c != p->expected) {
            ++n_fails;
        }
    }
    printf("%20s: %08x\n", "\"\\0\"", crc32_buffer(0, "\0", 1));
    printf("A, B:\n");
    printf("  %08x %08x\n", crc32_buffer(0, "A", 1), crc32_buffer(0, "B", 1));
    printf("  %08x %08x\n", crc32b(0, 'A'), crc32b(0, 'B'));

    printf("Hash function crc32w(0, x), crc32w(x, 0), crc32w(x, x):\n");
    static uint32_t const nums[] = { 0, 1, 2, 3, 4, 5, 6, 7, 8, 16, 0x1000, 0x2000, 0x4000, 0x4001, 0x4002, 0x8000, 0x8001, 0x8002, 0x10000 };
    for (i = 0; i < (sizeof nums / sizeof nums[0]); ++i) {
        printf("  0x%08x: 0x%08x 0x%08x 0x%08x 0x%08x\n", nums[i], crc32w(0, nums[i]), crc32w(nums[i], 0), crc32w(1, nums[i]), crc32w(nums[i], nums[i]));
    }
#define N_BINS 4
    int bins[N_BINS];
    memset(bins, 0, sizeof bins);
    for (i = 0; i < 100; ++i) {
        int r = hash_uint32(i) % N_BINS;
        ++bins[r];
    }
    for (i = 0; i < N_BINS; ++i) {
        printf("  %u: %5u\n", i, bins[i]);
    }

    /* Finally report and exit */
    printf("fails: %d\n", n_fails);
    return (n_fails > 0) ? EXIT_FAILURE : EXIT_SUCCESS;
}

#endif
