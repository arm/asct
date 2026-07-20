# ---------------------------------------------------------------------------------
# SPDX-FileCopyrightText: Copyright (C) 2025-2026 Arm Limited and/or its affiliates
# SPDX-FileCopyrightText: <open-source-office@arm.com>
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
# ---------------------------------------------------------------------------------

from collections import defaultdict
import csv
import glob
import os
import asct.core.logger as log
from asct.core.managers.ubench_reporter import get_reporter

ARMV8_PMUV3_EVENTS = {
    "SW_INCR": 0x0000,
    "L1I_CACHE_REFILL": 0x0001,
    "L1I_TLB_REFILL": 0x0002,
    "L1D_CACHE_REFILL": 0x0003,
    "L1D_CACHE": 0x0004,
    "L1D_TLB_REFILL": 0x0005,
    "LD_RETIRED": 0x0006,
    "ST_RETIRED": 0x0007,
    "INST_RETIRED": 0x0008,
    "EXC_TAKEN": 0x0009,
    "EXC_RETURN": 0x000A,
    "CID_WRITE_RETIRED": 0x000B,
    "PC_WRITE_RETIRED": 0x000C,
    "BR_IMMED_RETIRED": 0x000D,
    "BR_RETURN_RETIRED": 0x000E,
    "UNALIGNED_LDST_RETIRED": 0x000F,
    "BR_MIS_PRED": 0x0010,
    "CPU_CYCLES": 0x0011,
    "BR_PRED": 0x0012,
    "MEM_ACCESS": 0x0013,
    "L1I_CACHE": 0x0014,
    "L1D_CACHE_WB": 0x0015,
    "L2D_CACHE": 0x0016,
    "L2D_CACHE_REFILL": 0x0017,
    "L2D_CACHE_WB": 0x0018,
    "BUS_ACCESS": 0x0019,
    "MEMORY_ERROR": 0x001A,
    "INST_SPEC": 0x001B,
    "TTBR_WRITE_RETIRED": 0x001C,
    "BUS_CYCLES": 0x001D,
    "CHAIN": 0x001E,
    "L1D_CACHE_ALLOCATE": 0x001F,
    "L2D_CACHE_ALLOCATE": 0x0020,
    "BR_RETIRED": 0x0021,
    "BR_MIS_PRED_RETIRED": 0x0022,
    "STALL_FRONTEND": 0x0023,
    "STALL_BACKEND": 0x0024,
    "L1D_TLB": 0x0025,
    "L1I_TLB": 0x0026,
    "L2I_CACHE": 0x0027,
    "L2I_CACHE_REFILL": 0x0028,
    "L3D_CACHE_ALLOCATE": 0x0029,
    "L3D_CACHE_REFILL": 0x002A,
    "L3D_CACHE": 0x002B,
    "L3D_CACHE_WB": 0x002C,
    "L2D_TLB_REFILL": 0x002D,
    "L2I_TLB_REFILL": 0x002E,
    "L2D_TLB": 0x002F,
    "L2I_TLB": 0x0030,
    "REMOTE_ACCESS": 0x0031,
    "LL_CACHE": 0x0032,
    "LL_CACHE_MISS": 0x0033,
    "DTLB_WALK": 0x0034,
    "ITLB_WALK": 0x0035,
    "LL_CACHE_RD": 0x0036,
    "LL_CACHE_MISS_RD": 0x0037,
    "REMOTE_ACCESS_RD": 0x0038,
    "L1D_CACHE_LMISS_RD": 0x0039,
    "OP_RETIRED": 0x003A,
    "OP_SPEC": 0x003B,
    "STALL": 0x003C,
    "STALL_SLOT_BACKEND": 0x003D,
    "STALL_SLOT_FRONTEND": 0x003E,
    "STALL_SLOT": 0x003F,
    "L1D_CACHE_RD": 0x0040,
    "L1D_CACHE_WR": 0x0041,
    "L1D_CACHE_REFILL_RD": 0x0042,
    "L1D_CACHE_REFILL_WR": 0x0043,
    "L1D_CACHE_REFILL_INNER": 0x0044,
    "L1D_CACHE_REFILL_OUTER": 0x0045,
    "L1D_CACHE_WB_VICTIM": 0x0046,
    "L1D_CACHE_WB_CLEAN": 0x0047,
    "L1D_CACHE_INVAL": 0x0048,
    "L1D_TLB_REFILL_RD": 0x004C,
    "L1D_TLB_REFILL_WR": 0x004D,
    "L1D_TLB_RD": 0x004E,
    "L1D_TLB_WR": 0x004F,
    "L2D_CACHE_RD": 0x0050,
    "L2D_CACHE_WR": 0x0051,
    "L2D_CACHE_REFILL_RD": 0x0052,
    "L2D_CACHE_REFILL_WR": 0x0053,
    "L2D_CACHE_WB_VICTIM": 0x0056,
    "L2D_CACHE_WB_CLEAN": 0x0057,
    "L2D_CACHE_INVAL": 0x0058,
    "L2D_TLB_REFILL_RD": 0x005C,
    "L2D_TLB_REFILL_WR": 0x005D,
    "L2D_TLB_RD": 0x005E,
    "L2D_TLB_WR": 0x005F,
    "BUS_ACCESS_RD": 0x0060,
    "BUS_ACCESS_WR": 0x0061,
    "BUS_ACCESS_SHARED": 0x0062,
    "BUS_ACCESS_NOT_SHARED": 0x0063,
    "BUS_ACCESS_NORMAL": 0x0064,
    "BUS_ACCESS_PERIPH": 0x0065,
    "MEM_ACCESS_RD": 0x0066,
    "MEM_ACCESS_WR": 0x0067,
    "UNALIGNED_LD_SPEC": 0x0068,
    "UNALIGNED_ST_SPEC": 0x0069,
    "UNALIGNED_LDST_SPEC": 0x006A,
    "LDREX_SPEC": 0x006C,
    "STREX_PASS_SPEC": 0x006D,
    "STREX_FAIL_SPEC": 0x006E,
    "STREX_SPEC": 0x006F,
    "LD_SPEC": 0x0070,
    "ST_SPEC": 0x0071,
    "LDST_SPEC": 0x0072,
    "DP_SPEC": 0x0073,
    "ASE_SPEC": 0x0074,
    "VFP_SPEC": 0x0075,
    "PC_WRITE_SPEC": 0x0076,
    "CRYPTO_SPEC": 0x0077,
    "BR_IMMED_SPEC": 0x0078,
    "BR_RETURN_SPEC": 0x0079,
    "BR_INDIRECT_SPEC": 0x007A,
    "ISB_SPEC": 0x007C,
    "DSB_SPEC": 0x007D,
    "DMB_SPEC": 0x007E,
    "CSDB_SPEC": 0x007F,
    "EXC_UNDEF": 0x0081,
    "EXC_SVC": 0x0082,
    "EXC_PABORT": 0x0083,
    "EXC_DABORT": 0x0084,
    "EXC_IRQ": 0x0086,
    "EXC_FIQ": 0x0087,
    "EXC_SMC": 0x0088,
    "EXC_HVC": 0x008A,
    "EXC_TRAP_PABORT": 0x008B,
    "EXC_TRAP_DABORT": 0x008C,
    "EXC_TRAP_OTHER": 0x008D,
    "EXC_TRAP_IRQ": 0x008E,
    "EXC_TRAP_FIQ": 0x008F,
    "RC_LD_SPEC": 0x0090,
    "RC_ST_SPEC": 0x0091,
    "L3D_CACHE_RD": 0x00A0,
    "L3D_CACHE_WR": 0x00A1,
    "L3D_CACHE_REFILL_RD": 0x00A2,
    "L3D_CACHE_REFILL_WR": 0x00A3,
    "L3D_CACHE_WB_VICTIM": 0x00A6,
    "L3D_CACHE_WB_CLEAN": 0x00A7,
    "L3D_CACHE_INVAL": 0x00A8,
    "SAMPLE_POP": 0x4000,
    "SAMPLE_FEED": 0x4001,
    "SAMPLE_FILTRATE": 0x4002,
    "SAMPLE_COLLISION": 0x4003,
    "CNT_CYCLES": 0x4004,
    "STALL_BACKEND_MEM": 0x4005,
    "L1I_CACHE_LMISS": 0x4006,
    "L2D_CACHE_LMISS_RD": 0x4009,
    "L2I_CACHE_LMISS": 0x400A,
    "L3D_CACHE_LMISS_RD": 0x400B,
    "TRB_WRAP": 0x400C,
    "PMU_OVFS": 0x400D,
    "TRB_TRIG": 0x400E,
    "PMU_HOVFS": 0x400F,
    "TRCEXTOUT0": 0x4010,
    "TRCEXTOUT1": 0x4011,
    "TRCEXTOUT2": 0x4012,
    "TRCEXTOUT3": 0x4013,
    "CTI_TRIGOUT4": 0x4018,
    "CTI_TRIGOUT5": 0x4019,
    "CTI_TRIGOUT6": 0x401A,
    "CTI_TRIGOUT7": 0x401B,
    "LDST_ALIGN_LAT": 0x4020,
    "LD_ALIGN_LAT": 0x4021,
    "ST_ALIGN_LAT": 0x4022,
    "MEM_ACCESS_CHECKED": 0x4024,
    "MEM_ACCESS_CHECKED_RD": 0x4025,
    "MEM_ACCESS_CHECKED_WR": 0x4026,
    "TSTART_RETIRED": 0x4030,
    "TCOMMIT_RETIRED": 0x4031,
    "TME_TRANSACTION_FAILED": 0x4032,
    "TME_INST_RETIRED_COMMITTED": 0x4034,
    "TME_CPU_CYCLES_COMMITTED": 0x4035,
    "TME_FAILURE_CNCL": 0x4038,
    "TME_FAILURE_NEST": 0x4039,
    "TME_FAILURE_ERR": 0x403A,
    "TME_FAILURE_IMP": 0x403B,
    "TME_FAILURE_MEM": 0x403C,
    "TME_FAILURE_SIZE": 0x403D,
    "TME_FAILURE_TLBI": 0x403E,
    "TME_FAILURE_WSET": 0x403F,
}

# Dictionary for reverse lookup given hexcode
REVERSE_ARMV8_PMUV3_EVENTS = {v: k for k, v in ARMV8_PMUV3_EVENTS.items()}


def output_dir(_benchmark_name):
    # use a sub-directory for each benchmark to keep results separated
    return os.path.join(get_reporter().current_benchmark_dir(), "pmu_data", "perf")


# configure dietperf using environment variables
def setup_env(raw_event_names, benchmark_name):
    unique_event_names = list(dict.fromkeys(raw_event_names))  # Remove duplicates
    # maximum 6x events + 1x CPU_CYCLE counter total for arm64
    # dietperf does not currently support multiplexing
    if len(unique_event_names) > 7:
        raise ValueError(
            f"Maximum PMUv3 events is 7. {len(unique_event_names)} events were provided:{{unique_event_names}}"
        )
    unique_event_ids = [ARMV8_PMUV3_EVENTS[n] for n in unique_event_names]
    # event id's are stored as integers, convert to hex strings
    unique_event_hexcodes_csv = ",".join([hex(x) for x in unique_event_ids])

    # dietperf can only create directories one level deep, not recursive parent directories
    # create the full directory hierarchy here if it doesn't already exist
    outdir = output_dir(benchmark_name)
    try:
        os.makedirs(outdir, exist_ok=True)
    except OSError as e:
        log.error(f"Unable to create output directory '{outdir}': {e}")
        raise

    return {
        "DIETPERF_PMUv3": unique_event_hexcodes_csv,
        "DIETPERF_OUTDIR": outdir,
    }


# Current format is:
#   "L1D_CACHE_REFILL_RD": {
#     "0": 42.0,
#     "1": 44.0,
#     [...]
#   },
#   "L1D_CACHE_REFILL_RD:time_enabled_ns": {
#     "0": 1252440,
#     "1": 1199800,
#    [...]
#   },
#    "L1_Rd_Misses": {
#      "0": 42.0,
#      "1": 44.0,
#      [...]
#    },
#    "L1_Rd_Misses:time_enabled_ns": {
#      "0": 1252440,
#      "1": 1199800,
#      [...]
# ... where the raw event counter and separately named metric and values are duplicated within the dataframe
def retrieve_pmu_data(benchmark_name):
    result_files = glob.glob(os.path.join(output_dir(benchmark_name), "*"))
    result_files = sorted(result_files, key=os.path.getmtime)  # sort by oldest files first

    def recursive_defaultdict():
        return defaultdict(recursive_defaultdict)

    pmu_data = recursive_defaultdict()
    counter = 0
    for path in result_files:
        with open(path, "r", newline="") as f:
            rdr = csv.reader(f)
            for row in rdr:
                try:  # lookup event name
                    event_id = row[0]  # hex string e.g. 0x1234
                    event_name = REVERSE_ARMV8_PMUV3_EVENTS[int(event_id, 16)]
                except KeyError:
                    log.error(f"PMUv3 event ID not found in map: {event_id}")
                    raise
                except ValueError as err:
                    log.error(f"Non-integer event ID found in CSV file: {row[0]} {err}")
                    raise
                try:  # cast
                    value = int(row[1])
                    time_enabled = int(row[2])
                except (ValueError, IndexError):
                    log.error(f"Invalid PMUv3 event value found in CSV: value:{row[1]} time_enabled:{row[2]}")
                    raise
                pmu_data[event_name] = value
                pmu_data[event_name + ":time_enabled_ns"] = time_enabled
            counter += 1

    return pmu_data
