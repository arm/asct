/*
 * Copyright (C) Arm Ltd. 2025. All rights reserved.
 *
 * Memory block management for workload generator. 
 */

#ifndef __included_block_h
#define __included_block_h

#include <stdio.h>
#include <stddef.h>
#include <stdint.h>


/*
 * Properties of an allocated memory block.
 *
 * This is a descriptor for a block (typically large and aligned)
 * which we allocate as a code or data working set.
 *
 * The descriptor is initialized by the caller to describe how to
 * allocate the block.
 * Some fields are filled in on allocation, and also possibly updated
 * during the block's lifetime (e.g. prot is kept up to date by
 * block_protect).
 */
typedef struct block_s {
    void *owner;             /* Owning object (e.g. Python object) or NULL */

    /* Input parameters */
    size_t size_req;         /* Size actually wanted, in bytes */
    unsigned int is_exec:1;           /* Allocate as executable */
    unsigned int is_readonly:1;       /* Allocate as read-only */
    unsigned int is_no_hugepage:1;    /* Forbid allocation as huge pages */
    unsigned int is_hugepage:1;       /* Request opportunistic promotion to huge pages if large enough */
    unsigned int is_force_hugepage:1; /* Request promotion to huge pages even for small allocations */
    unsigned int is_numa:1;           /* Place on a specific NUMA node */
    unsigned long nodemask;  /* NUMA node mask */
    uint16_t fill_type;      /* Block fill type (see BLOCK_FILL_xx) */
    char const *user_name;   /* Helpful name (NULL if not required) */

    /* Output and current status */
    void *base;              /* Base virtual address, as allocated (page-aligned for mmap) */
    unsigned long size;      /* Size obtained - maybe rounded up to pages etc. */
    int prot;                /* Current protection flags */
    unsigned int is_mmap:1;           /* Block was obtained by mmap (not malloc) */
} Block;


#define BLOCK_FILL_NONE          0    /* default zero fill: possible zero-block sharing */
#define BLOCK_FILL_BYTE(x)       (0x100 + (x))    /* fill with a byte */
#define BLOCK_FILL_DEFAULT       1    /* fill with a non-zero byte or pattern */
#define BLOCK_FILL_RANDOM        2    /* random, seeded with block VA */
#define BLOCK_FILL_IDFILL_NO_PA  3    /* use block_idfill with no PA */
#define BLOCK_FILL_IDFILL_PA     4    /* use block_idfill with PA */


/*
 * Allocate and initialize a new block descriptor object on the heap.
 *
 * When no longer needed, caller should call block_free() to free
 * any allocated memory, and then call free() on the descriptor itself.
 *
 * It is not necessary to use this - caller can instead construct their
 * own descriptor and zero-initialize it or call block_init().
 */
Block *block_new(void);


/*
 * Initialize a block object, e.g. if caller provided on the stack.
 * Currently equivalent to zero-initialization.
 */
Block *block_init(Block *);


/*
 * Allocate memory for the block, according to the input parameters
 * the caller has put in the descriptor. Return base address
 * (also in the descriptor) or NULL.
 */
void *block_alloc(Block *);


/*
 * Apply protections (PROT_EXEC etc.) to the block.
 * The current protections are cached in the 'prot' field and
 * this call is a no-op if they already match the request.
 */
int block_protect(Block *, int);


/*
 * Apply memory advice as per madvise() e.g. MADV_HUGEPAGE.
 */
int block_advise(Block *, int);


/*
 * Bind the block to a specific set of NUMA nodes.
 */
int block_bind_nodemask(Block *, unsigned long);


/*
 * Set a name string for the block, that will show up in /proc/x/maps.
 * "myname" will show up as "[anon:myname]"
 * "The name can contain only printable ascii characters (isprint(3)),
 * except '[', ']', '\', '$', and '`'".
 * NULL removes the name.
 */
int block_set_name(Block *, char const *);


/*
 * Fill the block contents in various ways
 */
int block_fill(Block *, uint16_t);


/*
 * Fill the block's lines with self-identifying signatures
 */
int block_idfill(Block *, char const *, int);


/*
 * Return the checksum of the entire block.
 * Uses CRC32 in the same mode as e.g. Python binascii.crc32().
 */
uint32_t block_crc32(Block const *);


/*
 * Free the memory described by the descriptor.
 * Don't free the descriptor itself.
 *
 * This is a null operation if no memory has been allocated
 * for the descriptor, but it is not valid to pass NULL here.
 *
 * block_alloc() can be called again on the resulting object.
 */
void block_free(Block *);


/*
 * Dump a block in hex dump format.
 */
void block_fprint(Block const *, FILE *, int /*max_lines*/);


#endif /* included */
