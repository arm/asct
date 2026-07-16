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

from __future__ import annotations

import sys
import json
from io import StringIO
from os import path
from contextlib import redirect_stdout
from typing import Any
from collections.abc import Iterable, Sequence  # noqa: TC003
from collections import defaultdict
from dataclasses import dataclass, field
from cmntools import cmn_detect_cpu, cmn_unlock
from cmntools.cmn_diagram import CMNDiagram
from cmntools.cmn_discover import system_description, system_is_remote
from cmntools.cmn_enum import CMN_PROP_HNF, CMN_PORT_DEVTYPE_HNS, CMN_PROP_CCG
from cmntools.cmn_list import CMNLister, print_routing, list_logical
from cmntools.cmn_regdump import CMNRegDumper
from cmntools.cmn_select import cmn_select_merge
from cmntools.dmi import DMI
from cmntools import cmn_devmem_find, cmn_perfcheck
from cmntools.cmn_devmem import cmn_from_opts
from cmntools import cmn_json
from asct.core import logger as log


@dataclass
class Options:
    """Options for CMN register dumping and listing.
    These options control various aspects of CMN access and output formatting.
    """

    cmn_base: str | None = None
    cmn_root_offset: int = 0
    cmn_locations: str | None = None
    cmn_locs_no_cache: bool = True
    cmn_instance: int | None = None
    cmn_version: str | None = None
    cmn_iomem: str = "/proc/iomem"
    cmn_dt_base: str | None = None
    secure_access: bool | None = None
    list_cmn: bool = False
    cmn_diag: bool = False
    cmn_defer: bool = True
    list_logical: bool = False
    list: bool = False
    routing: bool = False
    node_type: int = 0
    port_type: int = 0
    node_match: str | None = None
    register_slices: bool = False
    verbose: int = 0
    include_read_only: bool = True
    include_zero: bool = True
    fields: bool = True
    descriptions: bool = True
    node: Any | None = None
    reg: Any | None = None
    flat: bool = False
    max_desc: int = 72


def _valid_cache(S):
    """
    Check the current system info against the CMN configuration file.

    Args:
        S: CMN System description object
    return:
        True if the cache is valid or unknown, False otherwise
    """
    system_uuid = None
    # try to get the system UUID from DMI
    # this requires root privileges
    # may not be available in some environments such as VMs
    try:
        D = DMI()
        system_uuid = D.system().uuid
    except (OSError, RuntimeError, ValueError) as e:
        log.debug(f"Could not get system UUID from DMI: {e}")

    if system_uuid is None:
        log.warning("Cannot compute system hash; skipping system validation")
        return True  # cannot validate

    return S.system_uuid == system_uuid


def _system_from_json_file(fn=None, check_timestamp=False, validate_cache=True):
    """
    Load the CMN system description from a file or the default cache.

    Args:
        fn: Path to the JSON descriptor. If None, use the default cache path.
        check_timestamp: If True, verify the descriptor is up to date (not older than the last reboot).
        validate_cache: If True, verify the descriptor matches the current system UUID.
    return:
        The system description object, or None if unavailable.
    """
    if fn is None:
        fn = cmn_json.cmn_config_filename()

    with open(fn) as f:
        data = json.load(f)
        S = cmn_json.system_from_json(data, filename=fn)
        if validate_cache and not _valid_cache(S):
            log.warning(
                "CMN system description cache is stale or mismatched. "
                "Run '--detect' to rebuild. See ASCT documentation."
            )
        if check_timestamp:
            cmn_json.check_system_description_time(S)
        return S
    return None


def get_cmn_data(validate_cache=True):
    """
    Retrieve the CMN system description data from cache.
    Args:
        validate_cache: If True, validates the cache against system UUID.
    return:
        CMN System description object or None if not found.
    """
    try:
        cmn_data = _system_from_json_file(validate_cache=validate_cache)
        if cmn_data is not None and not cmn_data.has_cpu_mappings():
            log.warning("CPU mappings not present. Please run with --detect to detect CPUs.")
            cmn_data = None
    except FileNotFoundError as e:
        log.info("No CMN data found. Please run with '--detect'. See ASCT documentation for details.")
        log.debug(f"CMN system description file not found. {e}")
        cmn_data = None
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as e:
        log.info("No CMN data found")
        log.debug(f"Error loading CMN data: {e}")
        cmn_data = None

    if not cmn_data:
        log.debug("No CMN data found in the system report.")

    return cmn_data


class CMNRegDumperWithJson(CMNRegDumper):
    # NOTE: This class must be reviewed and updated if the upstream CMN Tools logic
    # or register/field schema changes.
    # CMNRegDumperWithJson mirrors the behavior of CMNRegDumper while collecting
    # structured data for JSON output.
    # Any changes to register selection, access, or formatting in CMNRegDumper
    # must be reflected here to keep the human-readable output and JSON data consistent.
    def __init__(self, json_output: bool = True, **kwargs):
        """
        Initialize the instance.

        Parameters:
            json_output (bool, optional): Whether to produce JSON-formatted output. Defaults to True.
            **kwargs: Additional keyword arguments forwarded to the base class initializer.

        Attributes:
            json_output (bool): Flag indicating if JSON output is enabled.
            json_data (list): Container for accumulated JSON-serializable data.
        """
        super().__init__(**kwargs)
        self.json_output = json_output
        self.json_data = []

    def node_dump_regs(self, n):
        """Dump registers for a given node.
           Overrides base method to return structured data when JSON output is enabled.
        Args:
            n: Node object to dump registers from.
        Returns:
            dict | None: Structured data when JSON output is enabled; otherwise None.
        """
        if not self.json_output:
            return super().node_dump_regs(n)

        node_data = {
            "registers": [],
        }

        rm = self.node_regmap(n)
        if rm is None:
            return None

        self.node_loc_str = self.locator_str(n)
        printed_node = False
        for reg in rm.regs():
            if not self.reg_selected(reg.name):
                continue

            self.n_selected += 1
            if not self.reg_is_readable(n, reg):
                continue

            try:
                raw_value = self.reg_read(n, reg)
            except Exception as e:  # noqa: BLE001
                # Keep best-effort CMN dumps running even when cmn-tools raises
                # unexpected exceptions for a single register.
                log.warning(f"Could not read {self.locator_str(n)}.{reg.name}: {e}")
                continue

            if raw_value == 0 and self.o_skip_zeroes:
                log.debug(f"{reg}: excluded because zero")
                continue

            self.n_selected_2 += 1
            if not printed_node:
                log.debug("Node: %s at 0x%x", n, n.node_base_addr)
                printed_node = True

            registers = self.reg_dump(reg, raw_value)
            if registers:
                node_data["registers"].append(registers)

            # Check to see if any reserved bits (not mapped by named fields) are set.
            # This may indicate that we've mis-identified the product version, or the node type.
            if reg.has_fields:
                extra_bits = raw_value & reg.reserved_mask
                if extra_bits != 0:
                    node_data["extra_bits"] = extra_bits
                    log.debug("    %s %s reserved bits are set: 0x%x", n, reg, extra_bits)
                    self.n_regs_reserved_bits_set += 1

        return node_data

    def reg_dump(self, reg, raw_value):
        """
        Collect and dump register information. Overrides base method to return structured
        data when JSON output is enabled. If JSON output is enabled, returns a dictionary
        describing the register. Otherwise, delegates to the base implementation which prints
        the information directly to stdout.
        Args:
            reg: Register descriptor object.
            raw_value: Raw register value to report.
        Returns:
            dict | None: Structured data when JSON output is enabled; otherwise None.
        """

        # instead of printing, collect data for JSON output
        if self.json_output:
            return {
                "node": self.node_loc_str,
                "reg_name": reg.name,
                "address": reg.addr,
                "value": hex(raw_value),
                "access": reg.access,
                "reset": reg.reset[0] if reg.reset else None,
                "description": reg.desc,
                "fields": self.reg_dump_fields(reg, raw_value) if reg.has_fields else [],
            }
        super().reg_dump(reg, raw_value)
        return None

    def reg_dump_fields(self, reg, raw_value):
        """Dump fields of a register. Overrides base method to return
           structured data when JSON output is enabled.
        Args:
            reg: Register descriptor object.
            raw_value: Raw register value to report.
        """
        if not self.json_output:
            return super().reg_dump_fields(reg, raw_value)

        result = []
        for fld in reg.fields:
            val = fld.extract(raw_value)

            if val == 0 and self.o_skip_zeroes:
                continue

            result.append({
                "node": self.node_loc_str,
                "reg_name": reg.name,
                "field_name": fld.name,
                "value": hex(val),
                "bit_range": fld.range_str(),
                "description": fld.desc,
            })
        return result

    @staticmethod
    def to_string(regs: list[dict], indent: int = 5) -> str:
        """
        Generate a formatted, human-readable string for register metadata.
        Args:
            regs (list[dict]): A list of register dicts.
            indent (int): Number of leading spaces per line. Defaults to 5.
        Returns:
            str: Formatted text; multiple registers are separated by a blank line.
        """

        def _one(reg):
            """Generate string for one register dict."""
            lines = [
                f"Node        : {reg.get('node')}",
                f"Register    : {reg.get('reg_name')}",
                f"Address     : 0x{reg.get('address', 0):x}",
                f"Value       : {reg.get('value')}",
                f"Access      : {reg.get('access')}",
                f"Reset       : {reg.get('reset')}",
                f"Description : {reg.get('description')}",
            ]
            fields = reg.get("fields", [])
            if fields:
                lines.append("Fields:")
                lines.extend([
                    f"{f.get('bit_range', ''):>8}  "
                    f"{f.get('field_name', ''):<12} = "
                    f"{f.get('value', ''):<6}  "
                    f"{f.get('description', '')}"
                    for f in reg.get("fields", [])
                ])

            return "\n".join(" " * indent + line for line in lines)

        return "\n\n".join(_one(r) for r in regs)

    def cmn_dump_regs(self, C):
        """Collect non-empty register dumps for a CMN topology.
        Initializes regmaps from C.product_config, then aggregates dumps from the root
        node, each XP, and their port nodes.
        Args:
            C: Context/object providing product_config, rootnode, XPs(), and port_nodes(i).
        Returns:
            list: List of register dump structures collected from the topology.
        """
        result = []
        for node in self.cmn_nodes(C):
            try:
                node_data = self.node_dump_regs(node)
            except Exception as e:  # noqa: BLE001
                # Keep best-effort CMN dumps running even when cmn-tools raises
                # unexpected exceptions for a single node.
                log.warning(f"Could not dump CMN node {node}: {e}")
                continue
            if node_data is not None:
                result.append(node_data)
        return result


@dataclass
class CPUGrid:
    """2D grid of CPU identifiers mapped to CMN XP (x, y) tiles.

    The grid is indexed as ``rows[y][x]``. Each cell contains a sorted tuple of CPU
    IDs present at that tile; an empty tuple means no CPUs.
    """

    dim_x: int
    dim_y: int
    rows: list[list[tuple[int, ...]]] = field(default_factory=list)

    @classmethod
    def from_cmn(cls, cmn, cpu_objects: Iterable) -> CPUGrid:
        """Build a grid from a CMN-like object and CPU objects.

        Args:
            cmn: Object with dimX and dimY attributes.
            cpu_objects: Iterable where each item has:
                - .cpu (CPU id)
                - .port.xp.XY() returning (x, y) coordinates.

        Returns:
            CPUGrid with rows[y][x] as a sorted tuple of CPU IDs at (x, y).
        """
        dim_x = int(getattr(cmn, "dimX", 0))
        dim_y = int(getattr(cmn, "dimY", 0))

        tiles: defaultdict[tuple[int, int], set[int]] = defaultdict(set)
        for co in cpu_objects:
            x, y = co.port.xp.XY()
            tiles[x, y].add(co.cpu)

        rows = [[tuple(sorted(tiles.get((x, y), ()))) for x in range(dim_x)] for y in range(dim_y)]
        return cls(dim_x=dim_x, dim_y=dim_y, rows=rows)

    def format(self, *, reverse: bool = True) -> list[str]:
        """Return aligned row strings suitable for printing.
        Args:
            reverse: If True, print highest Y first (top-down).
        Returns:
            List of strings, one per row.
        """
        if not self.rows or self.dim_x == 0 or self.dim_y == 0:
            return ["[]"]

        def cell_str(cell: Sequence[int]) -> str:
            return f"({','.join(map(str, cell))})" if cell else "()"

        col_widths = [max(len(cell_str(row[x])) for row in self.rows) for x in range(self.dim_x)]

        ordered_rows = reversed(self.rows) if reverse else self.rows
        return [
            "[" + " ".join(cell_str(cell).ljust(col_widths[i]) for i, cell in enumerate(row)) + "]"
            for row in ordered_rows
        ]


@dataclass
class CMN_CPU_LIST:
    """Container for multiple CMN row list.

    meshes: seq -> RowListMesh
    Provides unified formatting for all or selected CMN instances.
    """

    meshes: dict[int, CPUGrid] = field(default_factory=dict)

    @classmethod
    def from_system(cls, S) -> CMN_CPU_LIST:
        """Build a CMN_CPU_LIST from a system description.
        Args:
            S: System description object with .cpus() and .CMNs attributes.
        Returns:
            CMN_CPU_LIST instance.
        """
        meshes: dict[int, CPUGrid] = {}
        if not S.has_cpu_mappings():
            return cls(meshes)

        cmn_map: dict[int, list] = {}

        # Group CPU objects by CMN sequence number
        for co in S.cpus():
            cmn_map.setdefault(co.port.CMN().cmn_seq, []).append(co)

        # Build CPUGrid for each CMN
        for seq, cpu_objs in cmn_map.items():
            C = next((c for c in S.CMNs if c.cmn_seq == seq), None)
            meshes[seq] = CPUGrid.from_cmn(C, cpu_objs)
        return cls(meshes=meshes)

    def format(self, seq: int | None = None, reverse: bool = True) -> dict[int, list[str]]:
        """Format the CPU grids for all or a specific CMN instance.
        Args:
            seq: If provided, only format the specified CMN sequence number.
            reverse: If True, print highest Y value first (top-down).
        Returns:
            Dict mapping CMN sequence numbers to their formatted row strings.
        """
        out: dict[int, list[str]] = {}
        # Format each mesh
        for k in sorted(self.meshes.keys()):
            if seq is not None and k != seq:
                continue
            out[k] = self.meshes[k].format(reverse=reverse)
        return out


class ASCT_CMN:
    def __init__(self, cmn, secure_access: bool = False):
        """Initialize the ASCT_CMN instance.
        Args:
            cmn: Required context/configuration object. Must provide `cmn_seq` (an identifier)
                and `product_config` (the product configuration or version).
        Raises:
            ValueError: If `cmn` is not provided or evaluates to falsy.
        Attributes:
            cmn: The provided context object.
            id: Identifier derived from `cmn.cmn_seq`.
            version: Product configuration/version derived from `cmn.product_config`.
            indent: Base indentation level used for formatting (default: 4).
            sub_indent: Secondary indentation level, computed as `indent + 4`.
        """

        if not cmn:
            raise ValueError("cmn must be provided to ASCT_CMN")
        self.cmn = cmn
        self.id = cmn.cmn_seq
        self.version = cmn.product_config
        self.secure_access = secure_access
        self.indent = 4
        self.sub_indent = self.indent + 4

    def __str__(self):
        hn_type = "S" if self.has_HNS else "F"
        # Build lines of the summary string, applying
        # use the self.indent for formatting
        lines = [
            f"{' ' * self.indent}CMN Instance #{self.id}",
            f"{' ' * (self.indent)}===============",
            f"{' ' * self.sub_indent}CMN version : {self.version}",
            f"{' ' * self.sub_indent}CHI version : {self.chi_version}",
            f"{' ' * self.sub_indent}X/Y config  : {self.size_str}",
            f"{' ' * self.sub_indent}HN-{hn_type} count  : {self.hnf_or_hns_count}",
            f"{' ' * self.sub_indent}CCG count   : {self.ccg_count}",
        ]
        return "\n".join(lines)

    def summary_dict(self):
        """Return a dictionary representation of the CMN summary data."""
        return {
            "version": str(self.version),
            "CHI version": self.chi_version,
            "X/Y config": self.size_str,
            "hn_type": "S" if self.has_HNS else "F",
            "hn_count": self.hnf_or_hns_count,
            "CCG count": self.ccg_count,
        }

    @property
    def has_HNS(self):
        """
        Return True if the CMN has HN-S nodes, False otherwise.
        """
        for node in self.cmn.ports(properties=CMN_PROP_HNF):
            if node.connected_type == CMN_PORT_DEVTYPE_HNS:
                return True
        return False

    @property
    def chi_version(self):
        """
        Return the CHI version string.
        """
        return self.cmn.product_config.chi_version_str()

    @property
    def frequency(self):
        """
        Return the CMN frequency in Hz, or None if not known.
        """
        log.debug(f"Getting frequency for CMN instance #{self.id}")
        if hasattr(self.cmn, "frequency") and self.cmn.frequency is not None:
            return "%.2f GHz" % (self.cmn.frequency / 1e9)

        return None

    @property
    def size(self):
        """
        Return the CMN size as (dimX, dimY).
        """
        return (self.cmn.dimX, self.cmn.dimY)

    @property
    def size_str(self):
        """
        Return the CMN size as a string "dimX x dimY".
        """
        return f"{self.cmn.dimX} x {self.cmn.dimY}"

    @property
    def slc_capacity_per_home_node(self):
        """
        Return the SLC capacity per home node in bytes, or None if not known.
        """
        return None

    @property
    def sn_count(self):
        """
        Return the number of SN nodes in the CMN.
        """
        return len(list(self.cmn.sn_ids()))

    @property
    def hnf_or_hns_count(self):
        """
        Return the number of home nodes (HN-F/S) in the CMN.
        """
        return len(list(self.cmn.home_nodes()))

    @property
    def ccg_count(self):
        """
        Return the number of CCG nodes in the CMN.
        """
        return len(list(self.cmn.nodes(CMN_PROP_CCG)))

    def get_registers(self):
        """
        Dump the CMN registers to the given filename.
        """
        opts = Options()
        opts.fields = True
        json_output = True

        # Set up the register dumper
        D = CMNRegDumperWithJson(
            json_output=json_output,
            regdefs_dir=None,
            regmaps=None,
            descriptions=opts.descriptions,
            description_limit=opts.max_desc,
            fields=opts.fields,
            include_read_only=opts.include_read_only,
            skip_zeroes=(not opts.include_zero),
            match_reg_names=opts.reg,
            match_nodes=cmn_select_merge(opts.node),
            flat=opts.flat,
        )

        # select CMN instances.
        opts.cmn_base = [self.cmn.periphbase]
        opts.cmn_root_offset = self.cmn.rootnode_offset
        opts.secure_access = self.secure_access
        CS = cmn_from_opts(opts)
        printed_sec_warning = False
        buf = StringIO()
        result = []

        # Redirect stdout to capture any debug output from the dumper
        with redirect_stdout(buf):
            for C in CS:
                if not C.secure_accessible and not printed_sec_warning:
                    log.debug("** Showing Non-Secure registers only")
                    printed_sec_warning = True
                result = D.cmn_dump_regs(C)
                if D.had_errors():
                    log.debug("** Warnings/errors encountered - check full output for details")
        # If not JSON output, print captured output
        if not json_output:
            print(buf.getvalue())

        return result

    @staticmethod
    def register_dict(register):
        register = register or {}
        return {
            "node": register.get("node"),
            "reg_name": register.get("reg_name"),
            "address": register.get("address"),
            "value": register.get("value"),
            "access": register.get("access"),
            "reset": register.get("reset"),
            "description": register.get("description"),
            "fields": list(register.get("fields") or []),
        }

    def registers_str(self):
        """
        Return a string representation of the CMN registers."""
        result = self.get_registers()

        string_data = self.sub_indent * " " + "Registers:\n"

        for i in result:
            string_data += CMNRegDumperWithJson.to_string(i["registers"], indent=self.sub_indent + 3)
            string_data += "\n"

        return string_data

    def diagram(self):
        """
        Return a TextDiagram object representing the CMN topology.
        """
        D = CMNDiagram(self.cmn, small=True)
        D.update()
        output = f"{D.str_color(no_color=False, force_color=True, for_file=sys.stdout)}"
        return "\n".join([f"        {line}" for line in output.splitlines()])

    def latency(self):
        """
        Return the estimated latency in nanoseconds between two nodes in the CMN.
        """
        raise NotImplementedError("latency not implemented for this CMN API")

    def list_nodes(self):
        """
        Return a list of all nodes in the CMN.
        """
        print("Listing CMN nodes:")
        opts = Options()
        if not (opts.list or opts.list_logical or opts.routing):
            opts.list = True
        match = cmn_select_merge(opts.node_match)
        opts.list = True
        L = CMNLister(
            None, verbose=opts.verbose, port_props=opts.port_type, node_props=opts.node_type, node_match=match
        )

        CS = cmn_from_opts(opts)
        for C in CS:
            if opts.list:
                L.show_cmn(C)
            if opts.list_logical:
                list_logical(C)
            if opts.routing:
                print_routing(CS, verbose=opts.verbose)

    @property
    def summary(self):
        """
        Return a summary string for the CMN.
        """
        cmn_data = get_cmn_data(validate_cache=False)
        return CMN_CPU_LIST.from_system(cmn_data)

    def diagram_summary_str(self):
        """
        Return a string representation of the CMN summary
        which includes the CPU grid layout.
        """
        summary = self.summary
        result = ""
        if summary and summary.meshes:
            formatted = summary.format()
            for seq, lines in formatted.items():
                if seq != self.id:
                    continue
                result += self.sub_indent * " " + "CPU Grid Layout:\n"
                for line in lines:
                    result += (self.sub_indent + 4) * " " + " " + line + "\n"

        return result


def discover(overwrite: bool = False, frequency: bool = False, output: str | None = None):
    """
    Perform any necessary discovery steps for the CMN API.
    Args:
        overwrite: If True, overwrite existing output file.
        frequency: If True, attempt to determine CMN frequency.
        output: Path to output JSON file.
    Raises:
        RuntimeError: If discovery fails or CMN interconnects are not found.
    """

    if output is None:
        output = cmn_json.cmn_config_filename()

    opts = Options()
    ok = True
    S = system_description(opts=opts, frequency=frequency)

    if not S.CMNs:
        # This toolkit is currently specific to CMN, and it's not useful to save
        # a system descriptor if the system doesn't have CMN.
        log.warning(f"CMN interconnects not found (system = '{S.system_type}')")
        guest_type = cmn_devmem_find.system_is_probably_guest()
        if guest_type:
            log.warning(f"System appears to be running as a {guest_type} guest")

        raise RuntimeError("CMN interconnects not found")

    # Report discovered CMNs
    for c in S.CMNs:
        log.info(f"Found {c}")

    if not overwrite and path.exists(output):
        log.warning(f"File already exists {output}")
        ok = False
    else:
        log.info(f"Writing system configuration to {output}...")
        cmn_json.json_dump_file_from_system(S, output)

    if not system_is_remote(S) and not cmn_perfcheck.check_cmn_pmu_events():
        ok = False

    if not ok:
        raise RuntimeError("Discovery failed")


def has_cmn_data():
    """
    Check if CMN data is available.
    """
    return path.exists(cmn_json.cmn_config_filename())


def detect_cpus(update: bool = False):
    """
    Detect and return a list of CPUs connected to the CMN.
    param update: If True, updates existing CMN JSON with
    CPU mappings in the system description. If False, skips detection if
    CPU mappings already exist.
    return: None
    """

    args = [
        "--json",
        cmn_json.cmn_config_filename(),
        "--time",
        "1.0",
        "--detection-level",
        "5.0",
        "--retries",
        "3",
        "--retry-multiplier",
        "2.0",
        "--perf-bin",
        "perf",
    ]
    if update:
        args.append("--update")

    try:
        cmn_detect_cpu.main(args)
    except SystemExit as e:
        if e.code not in (None, 0):
            raise RuntimeError("CPU detection failed") from e


def cmn_lock_unlock_registers(node_type: str = "all", lock: bool = True):
    """
    Lock or unlock CMN registers for secure access.
    This function is a wrapper around the cmn_unlock module's main function,
    providing a simplified interface for locking or unlocking CMN registers with predefined options.
    Note that this operation may require elevated privileges and should be performed with caution,
    Raises:
        RuntimeError: If locking or unlocking fails.
    """
    action = "lock" if lock else "unlock"
    target_state = "locked" if lock else "unlocked"
    log.debug(f"{action.capitalize()}ing CMN registers for secure access...")
    try:
        # suppress output from cmn_unlock and log success or failure
        buf = StringIO()
        with redirect_stdout(buf):
            cmn_unlock.main([f"--node={node_type}", "--lock" if lock else "--unlock"])
        output = buf.getvalue()

        # check output for success message; this is a
        # simple heuristic and may need to be updated if cmn_unlock's
        # output changes
        expected_outputs = [f"Target now {target_state}", f"Target already {target_state}"]
        if not any(expected in output for expected in expected_outputs):
            raise RuntimeError(f"Unexpected output from cmn_unlock: {output}")

        log.debug(f"CMN registers {target_state} successfully.")
    except Exception as e:
        log.error(f"Failed to {action} CMN registers: {e}")
        raise RuntimeError(f"CMN register {action}ing failed") from e
