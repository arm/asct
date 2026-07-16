/*
 * Copyright (C) Arm Ltd. 2025. All rights reserved.
 *
 * Round addresses and sizes.
 *
 * Granules must be a power of 2, but are supplied as an actual size,
 * not a logarithm.
 */

#ifndef _included_round_h
#define _included_round_h

#include <stdint.h>


/* Round size downwards, giving a new size rounded to the given boundary. */

#ifdef __cplusplus
template<typename T>
inline T round_size_down(T size, unsigned int granule)
{
    return (size + (granule-1)) & ~(T)(granule-1);
}
#else
#define round_size_down(size, granule) ((size) & ~((size)*0+(granule)-1))
#endif


/* Round size upwards, giving a new size rounded to the given boundary. */

#ifdef __cplusplus
template<typename T>
inline T round_size_up(T size, unsigned int granule)
{
    return (size + (granule-1)) & ~(T)(granule-1);
}
#else
/* Round the size by ANDing with a suitable constant.
   The constant must be as wide as the size. */
#define round_size_up(size, granule) (((size) + ((granule)-1)) & ~((size)*0+(granule)-1))
#endif


#define round_addr_up(addr, granule) (void *)round_size_up((uintptr_t)(addr), granule)

#define round_addr_down(addr, granule) (void *)round_size_down((uintptr_t)(addr), granule)


#define round_count_up(size, granule)   (round_size_up(size, (granule)) / (granule))

#define round_count_down(size, granule) (round_size_down(size, (granule)) / (granule))


#define is_rounded(x, granule) (((unsigned long)(x) % (granule)) == 0)


#endif /* included */
