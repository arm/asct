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

import sys
from os import path
import importlib.util
import re
from glob import glob
from asct.core import logger as log
from asct.lib.ip_registers.collector import collect_registers as collect_ip_registers


def _find_register_dump():
    """
    Locate the register dumper in a source checkout or packaged tree.
    """
    cur = path.abspath(path.dirname(__file__))
    for _ in range(8):
        patterns = [
            path.join(cur, "extern", "cmn-tools", "systems", "*", "ucie_dump.py"),
            path.join(cur, "extern", "cmn-tools", "systems", "*", "scripts", "ucie_dump.py"),
            path.join(cur, "systems", "*", "ucie_dump.py"),
        ]
        for pattern in patterns:
            matches = sorted(glob(pattern))
            if not matches:
                continue
            fn = matches[0]
            if path.isfile(fn):
                return fn
        parent = path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    raise FileNotFoundError("could not find systems/*/ucie_dump.py")


def _load_register_dump():
    fn = _find_register_dump()
    module_dir = path.dirname(fn)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    spec = importlib.util.spec_from_file_location("_asct_register_dump", fn)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def collect_registers(
    ip: str, reg_filter: list[str] | None = None, fields: bool = True, exclude_volatile: bool = True, verbose: int = 0
):
    """
    Collect IP scratch registers as structured dictionaries.
    """
    module = _load_register_dump()
    regs = [re.compile(val, flags=re.IGNORECASE) for val in reg_filter] if reg_filter else []
    registers = collect_ip_registers(
        module, ip=ip, regs=regs, fields=fields, exclude_volatile=exclude_volatile, verbose=verbose
    )

    for reg in registers:
        for key in ("base", "block_address", "offset", "address", "value"):
            if isinstance(reg.get(key), int):
                reg[key] = hex(reg[key])

        for field in reg.get("fields", []) or []:
            if isinstance(field.get("value"), int):
                field["value"] = hex(field["value"])

    return registers


def is_ip_dump_available():
    """Check if the IP dumper is available."""
    try:
        _find_register_dump()
    except FileNotFoundError:
        log.debug("Register dumper not found, IP register collection will be unavailable.")
        return False
    log.debug("Register dumper found, IP register collection will be available.")
    return True
