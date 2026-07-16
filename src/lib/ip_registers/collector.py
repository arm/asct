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

from asct.core import logger as log


class RegDumper:
    """
    Iterate over a register space, using provided register definitions.
    """

    def __init__(self, verbose=0, regdefs=None):
        self.verbose = verbose
        self.regdefs = regdefs

    def collect(self, instances, reg_list=None, fields=False, exclude_volatile=False, start_offset=0, end_offset=None):
        """
        Return register data as dictionaries, without changing the human-readable
        dump() output path.
        """

        def reg_selected(rl, name):
            if not rl:
                return True
            return any(e.search(name) for e in rl)

        instances = list(instances)
        rows = []
        for rm in self.regdefs.maps_by_addr():
            if self.verbose:
                log.debug(f"register map: {rm}")
            for r in rm.regs():
                if not reg_selected(reg_list, r.name):
                    continue
                if r.addr < start_offset:
                    if self.verbose:
                        log.debug(f"excluding before offset 0x{start_offset:x}: {r}")
                    continue
                if end_offset is not None and r.addr >= end_offset:
                    if self.verbose:
                        log.debug(f"excluding after offset 0x{end_offset:x}: {r}")
                    continue
                if exclude_volatile and r.is_volatile:
                    if self.verbose:
                        log.debug(f"excluding volatile register: {r}")
                    continue
                rel_addr = rm.addr + r.addr
                for inst_ix, m in enumerate(instances):
                    value = m.read32(rel_addr)
                    row = {
                        "instance": inst_ix,
                        "base": getattr(m, "pa", None),
                        "block_address": rm.addr,
                        "block_name": rm.name,
                        "offset": r.addr,
                        "address": rel_addr,
                        "reg_name": r.name,
                        "value": value,
                        "access": r.access,
                        "security": r.security,
                        "description": r.desc,
                        "fields": [],
                    }
                    if fields:
                        for f in r.fields:
                            fvalue = f.extract(value)
                            if f.is_reserved and fvalue == 0:
                                continue
                            row["fields"].append({
                                "field_name": f.name,
                                "bit_range": f.range_str(),
                                "value": fvalue,
                                "description": f.desc,
                            })
                    rows.append(row)
        return rows


def collect_registers(
    ucie_dump_module,
    ip="ucie",
    regdefs=None,
    base=None,
    regs=None,
    dry_run=False,
    fields=False,
    exclude_volatile=False,
    start_offset=0,
    end_offset=None,
    verbose=0,
):
    """
    Collect register data for callers that need structured output.
    """
    known_ip = ucie_dump_module._known_ip
    regdefs_from_file = ucie_dump_module.regdefs_from_file
    regdefs_size = ucie_dump_module.regdefs_size
    round_up = ucie_dump_module.round_up
    FakeInstance = ucie_dump_module.FakeInstance
    instance_maps = ucie_dump_module.instance_maps

    if ip not in known_ip:
        raise ValueError(f"unknown IP: {ip} (known: {list(known_ip.keys())})")

    (defs_fn, addrs) = known_ip[ip]
    if regdefs:
        defs_fn = regdefs
    if base:
        addrs = [base]
    defs = regdefs_from_file(defs_fn)
    size = round_up(regdefs_size(defs), 0x10000)
    D = RegDumper(regdefs=defs, verbose=verbose)
    if dry_run:
        instances = [FakeInstance()]
    else:
        instances = instance_maps(addrs, size)
    return D.collect(
        instances,
        reg_list=regs,
        fields=fields,
        start_offset=start_offset,
        end_offset=end_offset,
        exclude_volatile=exclude_volatile,
    )
