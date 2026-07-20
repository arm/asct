/*
Copyright (C) ARM Ltd. 2016.

Synthetic workload generator / executor.

This module constructs and executes synthetic workloads based on a set of
generic input parameters (characteristics) describing aspects such as

   - code working set
   - data working set
   - branch predictability
   - use of various instruction groups

The resulting workload, when run, should consume CPU and system resources
corresponding to its characteristics.
*/


#ifndef __included_loadgen_h
#define __included_loadgen_h

#ifndef ASCT
#include "genelf.h"
#endif /* ASCT */

#include "block.h"

#include <stdint.h>


/* Instruction set for workload */
typedef enum {
    ISA_NONE,
    ISA_T32,
    ISA_A32,
    ISA_A64,
    ISA_X86,
    ISA_MAX
} isa_t;

extern isa_t isa_local(void);


/*
Workload characteristics structure.

This is filled in by the client, to specify the workload.
*/
typedef struct {
    /* Instruction set for generated workload. */
    isa_t isa;
    /* Data working set in bytes. Currently assumed to be flat
       (i.e. randomly distributed, not clumped). */
    unsigned long data_working_set;
    /* The data pointer offset can be set non-zero to try and defeat
       linked-list prefetchers. The offset will be applied to pointers
       stored in the data working set, and adjusted for in the loads. */
    unsigned int data_pointer_offset;
    /* How sparse is the data? This multiplier is applied to the
       addresses within the data. (A default of 0 has the effect of 1.) */
    unsigned int data_dispersion;
    /* Alignment of pointers in the data working set - e.g. 1 for
       byte alignment. Set to 0 for natural alignment. */
    unsigned int data_alignment;

    /* Instruction working set in bytes. */
    unsigned long inst_working_set;
    /* Instruction group size in bytes. Can be -ve to generate instruction
       groups in reverse. */
    int inst_group_size;
    unsigned int inst_mispredict_rate;

#define WL_MEM_BW                0x01   /* Measure for memory bandwidth not latency */
#define WL_MEM_NONTEMPORAL       0x02   /* Use non-temporal loads where possible */
#define WL_MEM_LOAD_EXTRA        0x04   /* Generate an additional (unused) load */
#define WL_MEM_LOAD_PAIR         0x08   /* Use a non-temporal load */
#define WL_MEM_PREFETCH          0x10   /* Issue a software prefetch before loading */
#define WL_MEM_STREAM            0x20   /* Use stream rather than random workload */
#define WL_MEM_NO_HUGEPAGE       0x40   /* Request no huge-pages */
#define WL_MEM_HUGEPAGE          0x80   /* Request huge-pages */
#define WL_MEM_FORCE_HUGEPAGE   0x100   /* Request huge-pages even when small */
#define WL_MEM_BARRIER          0x200   /* Generate a load barrier after each load */
#define WL_MEM_ACQUIRE          0x400   /* Use load-acquire instruction */
#define WL_MEM_STORE           0x1000   /* Generate stores as well as loads */
#define WL_MEM_RELEASE         0x2000   /* Use store-release instruction */
#define WL_MEM_ATOMIC          0x4000   /* Use atomic instruction */
#define WL_DEPEND              0x8000   /* Force total dependency chain */
#define WL_MEM_BARRIER_SYSTEM 0x10000   /* e.g. DMB SY */
#define WL_MEM_BARRIER_SYNC   0x20000   /* Serializing wrt instructions: DSB instead of DMB */
#define WL_SERIALIZE          0x40000   /* Full serialization barrier e.g. ISB */
#define WL_MEM_NOP           0x100000   /* Generate a NOP before each load */
#define WL_MEM_NOP2          0x200000   /* Generate two NOPs before each load */
#define WL_MEM_NUMA          0x400000   /* Place data on specified NUMA nodes */
#define WL_MEM_BLOCKED       0x800000   /* Use sub-blocking in pointer chain */
    uint32_t workload_flags;       /* WL_xxx flags */
    unsigned long nodemask;        /* NUMA node mask */

    /* Floating-point intensity - FP ops per memory reference. */
    unsigned int fp_intensity;
    /* Arithmetic precision */
#define FP_PRECISION_FP16    1
#define FP_PRECISION_SINGLE  2
#define FP_PRECISION_DOUBLE  3
    unsigned int fp_precision;   /* 1: FP16, 2: SP, 3: DP */
    unsigned int fp_simd;        /* 0: scalar, N: N-way SIMD */
#define FP_OP_MOV 0
#define FP_OP_IADD 1
#define FP_OP_IXOR 2
#define FP_OP_NEG 3
#define FP_OP_ADD 4
#define FP_OP_MUL 5
#define FP_OP_DIV 6
#define FP_OP_SQRT 7
#define FP_OP_FMA 8     /* up to here, we must match arrays in loadinst.c */
#define FP_OP_FMAA 9
#define FP_OP_MULADD 10
#define FP_OP_DOT2 11
#define FP_OP_DOT4 12
#define FP_OP_DIST2 13
    unsigned int fp_operation;
    unsigned int fp_concurrency;     /* Number of concurrent ops: 1 = back-to-back */
    double fp_value;             /* Floating-point data value initializer */
    double fp_value2;            /* Floating-point data value corrector */

    /* Floating-point flags can modify both the target configuration and
       our generated code. */
#define FP_FLAG_DENORMAL_GEN   0x01   /* Code generation: use denormal inputs */
#define FP_FLAG_DENORMAL_FTZI  0x02   /* Target mode: flush to zero on input */
#define FP_FLAG_DENORMAL_FTZO  0x04   /* Target mode: flush to zero on output */
#define FP_FLAG_DENORMAL_FTZ   (FP_FLAG_DENORMAL_FTZI|FP_FLAG_DENORMAL_FTZO)
#define FP_FLAG_ALTERNATE      0x08   /* Use alternate instruction form (whatever it is) */
#define FP_FLAG_SIMPLE_VAL     0x10   /* Use simple (possibly fast) value */
#define FP_FLAG_CONVERGE       0x20   /* For DIV, converge to result of 1.0 */
#define FP_FLAG_LOAD_CONST     0x40   /* Load constants from memory */
    uint32_t fp_flags;                /* FP_FLAG_xxx */

    /* Debugging/diagnostic flags for workload generation. */
#define WORKLOAD_DEBUG_NO_MPROTECT     1   /* don't do mprotect() even if we need to */
#define WORKLOAD_DEBUG_NO_UNIFICATION  2   /* don't do cache unification even if we need to */
#define WORKLOAD_DEBUG_DUMMY_CODE      4   /* never generate code */
#define WORKLOAD_DEBUG_NO_WX           8   /* avoid write+execute */
#define WORKLOAD_DEBUG_NO_FREE      0x10   /* don't free any memory - in case race */
#define WORKLOAD_DEBUG_TRIAL_RUN    0x20   /* check workload runs, immediately after construction */
#define WORKLOAD_DEBUG_ARMIE_ROI    0x40   /* generate RoI instructions (not NOP-compatible) for ArmIE */
#define WORKLOAD_DEBUG_NO_NAME      0x80   /* don't use prctl() to give names to memory areas */
    uint32_t debug_flags;             /* WORKLOAD_DEBUG_xxx */
    unsigned long inst_target;        /* Target no. of insts for one execution of workload */
    unsigned int barrier_interval;    /* Instructions between instruction barrier */
} Character;


void workload_init(Character *);


/*
What the entry point for a workload looks like.
There may also be implicit floating-point arguments (TBD improve).
*/
typedef void *(* dummy_fn_t)(void *, void *, void *);


/*
When generating the workload code, we keep track of how
many instructions of these different categories we expect
to execute. This can then be calibrated against observed
performance events.
*/
typedef enum InstCounter {
    /* The following correspond to hardware counters. */
    COUNT_INST,          /* Total instructions */
    COUNT_BRANCH,        /* Any kind of branch or transfer of control */
    COUNT_FLOP_HALF,     /* Half-precision floating-point operations */
    COUNT_FLOP_SP,       /* SP floating-point operations: FMA counts 2, SIMD counts N */
    COUNT_FLOP_DP,       /* DP floating-point operations: FMA counts 2, SIMD counts N */
    COUNT_MOVE,          /* Register moves (any kind) */
    COUNT_INST_RD,       /* Memory read instructions */
    COUNT_BYTES_RD,      /* Memory read bytes */
    COUNT_INST_WR,       /* Memory write instructions */
    COUNT_BYTES_WR,      /* Memory write bytes */
    COUNT_FENCE,         /* Fences/barriers */
#define COUNT_MEM_PREFETCH COUNT_INST   /* Don't count prefetches as reads */
    /* The following are more arbitrary measures, when we are generating
       sequences of instructions (e.g. dot-product). */
    COUNT_UNIT,
    /* Number of counter types, for sizing counter arrays */
    COUNT_MAX
} inst_counter_t;


struct inst_counters {
    unsigned int n[COUNT_MAX];
};


/*
Details of a workload created to implement the workload characteristics
requested by a client.
*/
typedef struct {
    /* Data passed in by client */
    Character c;         /* Copy of workload characteristics as specified by client */

    /* Data about the generated workload code */
    struct inst_counters expected;  /* Count values per entry call */
    unsigned int n_chain_steps;  /* number of data steps per iteration */
    elf_t elf_image;     /* Internal descriptor for ELF generation */

    /* Data required to run the workload */
    dummy_fn_t entry;    /* Code entry point */
    void *entry_args[2]; /* Arguments for entry point */

    /* Following are internal details - shouldn't really be exposed here */
    Block *code_mem;
    Block *data_mem;

    /* Current status of the workload */
    volatile unsigned int references;   /* Number of threads running this workload */

    /* Anything else needed by the workload */
    uint64_t scratch[16]; /* Scratch space for spills etc. */
} Workload;


/*
 * Builds a workload with the given characteristics.
 * Returns a workload object.
 */
Workload *workload_create(Character const *);

/*
 * Increment the reference count on a workload.
 */
void workload_add_reference(Workload *);

/*
 * Decrement the reference count and possibly destroy the workload.
 */
void workload_remove_reference(Workload *);

/*
 * Destroy a workload object.
 * Return 1 if the workload was actually freed, 0 if deferred.
 */
int workload_free(Workload *);

/*
 * Run the first iteration of a workload in the current thread, and then stop.
 * Multiple threads can concurrently run the same workload.
 */
void workload_run_once(Workload *);

/*
 * Run N iterations of a workload in the current thread.
 */
void *workload_run(Workload *, void *, unsigned int);

/*
 * Dump workload to an ELF file.
 */
int workload_dump(Workload *, char const *fn, unsigned int flags);

/*
 * Check if a workload is runnable within the current process -
 * i.e. has not been generated for dumping to ELF and running on a different ISA.
 */
int workload_is_runnable(Workload *);

#endif /* included */

