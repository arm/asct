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

import datetime
import os
import re
import pandas as pd
from collections import OrderedDict
from copy import deepcopy
from functools import cached_property
from dataclasses import dataclass, asdict, is_dataclass
import asct.sysreport.sysreport as sr
from asct.core.benchspec.benchspec import ASCTBenchmarkConfig
from asct.core.recipes.configuration.metadata import ASCT_RECIPE_METADATA, get_recipe
from asct.core.recipes.recipe_base import RecipeBase
from asct.core.utility.format import memsize_str
from asct.core.utility.misc import flatten_dict
from asct.core.datatypes import ASCTSingleton
from asct.core import logger as log
from asct.core.cmd.helpers.version_helpers import get_version
from asct.core.cmn.asct_dmi import ASCT_DMI, MemoryProperties, BiosInfo, memory
from asct.lib.output_metadata.fields import field_string, section_string


@dataclass
class report:
    collected_time: datetime = None
    asct_ver: str = None
    run_as_root: bool = None


@dataclass
class sys_hw:
    arch: str = None
    n_cpus: int = None
    cpu_type: str = None
    cpu_features: list = None
    cache_info: str = None
    cache_line_size: int = None
    cache_size_dict: dict[str, int] = None
    caches: {str, int} = None
    atomics: bool = None
    interconnect: tuple[str, int] = None
    n_numa_nodes: int = None
    numa_nodes: OrderedDict[str, tuple[int, list[int]]] = None
    numa_kern_cfg: bool = None
    sockets: int = None

    @cached_property
    def cpu_list_per_numa_node(self) -> OrderedDict:
        """
        Return an OrderedDict mapping NUMA node IDs to their CPU lists.
        Empty CPU lists are skipped.
        cached_property to avoid repeated computation.
        The result is cached (cached_property) after the first access
        and persists for the instance lifetime.
        """
        cpu_lists = OrderedDict()
        for node, (_, cpus) in self.numa_nodes.items():
            # skip empty cpu lists (if any)
            if not cpus:
                continue
            cpu_lists[node] = cpus
        return cpu_lists

    @cached_property
    def n_cpus_per_numa_node(self) -> OrderedDict:
        """
        Return a OrderedDict of CPU counts, one per NUMA node.
        cached_property to avoid repeated computation.
        The result is cached (cached_property) after the first access
        and persists for the instance lifetime.
        """
        return OrderedDict((node, len(cpu_list)) for node, cpu_list in self.cpu_list_per_numa_node.items())

    @cached_property
    def last_cpus_per_numa_node(self) -> OrderedDict:
        """
        Return a OrderedDict of last CPU, one per NUMA node.
        cached_property to avoid repeated computation.
        The result is cached (cached_property) after the first access
        and persists for the instance lifetime.
        """
        return OrderedDict((node, max(cpu_list)) for node, cpu_list in self.cpu_list_per_numa_node.items() if cpu_list)

    @cached_property
    def cpus_to_numa_node_map(self) -> OrderedDict:
        """
        Return a mapping of CPU ID to NUMA node ID.
        cached_property to avoid repeated computation.
        The result is cached (cached_property) after the first access
        and persists for the instance lifetime.
        """
        cpu_to_node = OrderedDict()
        for node, (_, cpus) in self.numa_nodes.items():
            for cpu in sorted(cpus):
                cpu_to_node[cpu] = node
        return cpu_to_node


@dataclass
class sys_info:
    manufacturer: str = None
    product_name: str = None
    version: str = None
    serial: str = None
    uuid: str = None


@dataclass
class kern_cfg:
    ver: str = None
    cfg_file: str = None
    build_dir: str = None
    uses_atomics: bool = None
    huge_pages: str = None
    thp: str = None
    mpam: bool = None
    resctrl: bool = None
    distro: str = None
    libc_ver: str = None
    boot_info: str = None
    kpti: bool = None
    lockdown: str = None
    mitigations: str = None


@dataclass
class bpf:
    bpf: bool = None
    bpf_tool: bool = None
    bpf_tool_ver: str = None
    bpftrace: bool = None


@dataclass
class perf_feats:
    has_tools: str = None
    perf_dir: str = None
    perf_opencsd: str = None
    n_counters: int = None
    perf_sampling: str = None
    perf_hw_trace: str = None
    paranoid: int = None
    kptr_restrict: int = None
    userspace_access: str = None
    interconnect: bool = None
    kcore: bool = None
    devmem: bool = None
    bpf: bpf = None


class SystemInfo(RecipeBase, metaclass=ASCTSingleton):
    """
    RecipeBase-derived class for running and reporting sysreport results.
    """

    def __init__(self, metadata=None):
        # SystemInfo is instantiated early by command/setup code before recipes are
        # created via the normal registry path, so it resolves its own metadata.
        if metadata is None:
            metadata = get_recipe("system-info", ASCT_RECIPE_METADATA)
        if metadata is None:
            raise AssertionError("SystemInfo metadata not found")
        RecipeBase.__init__(self, metadata=metadata)

        self.priority = 0  # run before all other recipes to have system info available for them
        self.report = report()
        self.sys_hw = sys_hw()
        self.memory = memory()
        self.kern_cfg = kern_cfg()
        self.perf_feats = perf_feats(bpf=bpf())
        self.bios_info = BiosInfo()

        self._result = None
        self.kernel_config = None
        self.advice = None
        self.vulnerabilities = None
        self._dmi_definitions: ASCT_DMI | None = None
        self._dmi_checked = False
        self.sys_info = sys_info()
        self.super_user = os.geteuid() == 0
        self._ready = False

        self.initialize_config()

    def _create_default_config(self):
        return ASCTBenchmarkConfig(
            advice=False,
            kernel_config=False,
            vulnerabilities=True,
        )

    @property
    def dmi_definitions(self) -> ASCT_DMI | None:
        """
        Get system info properties (manufacturer, product name) by decoding DMI table.
        Will generally require root privilege.
        """
        if self._dmi_checked:
            return self._dmi_definitions

        try:
            self._dmi_definitions = ASCT_DMI()
        except PermissionError:
            log.error("Cannot decode DMI - root privilege is required")
        except FileNotFoundError:
            log.error("Cannot find DMI tables")
        except (OSError, RuntimeError, ValueError, TypeError) as ex:
            log.error(f"DMI table decode error: {ex}")

        self._dmi_checked = True
        return self._dmi_definitions

    @property
    def ready(self):
        return self._ready

    def run_function(self):
        """
        Run the sysreport and collect results.
        """
        if not self.super_user:
            log.warning("Not running as root, therefore some information is unavailable")

        misc_info = sr.System()

        self.report.collected_time = datetime.datetime.now(datetime.timezone.utc).isoformat(" ")
        self.report.asct_ver = get_version()
        self.report.run_as_root = self.super_user

        self.sys_hw.arch = misc_info.architecture()
        self.sys_hw.n_cpus = misc_info.get_cpu_count()
        self.sys_hw.cpu_type = ", ".join([
            "{:d} x {}".format(len(cl), ct.str_full()) for (ct, cl) in misc_info.system.spec_to_cpulist.items()
        ])
        self.sys_hw.cpu_features = misc_info.get_cpu_features()

        self.sys_hw.cache_info = sr.cache_info()
        self.sys_hw.cache_line_size = misc_info.get_cache_line_size()
        self.sys_hw.cache_size_dict = {}
        # from misc_info.system-caches() we get a big list of cache information with repeated information due
        # to multiple CPUS.  Try to create a size dict simply capturing level to size mapping.
        for cache in misc_info.system.caches():
            if not cache.contains("D"):
                # Skip non-data caches, "D" stands for data cache. See Cache.contains() for more details.
                continue
            # Add the cache size to the dict if the level is not already present, otherwise skip it.
            saved_size = self.sys_hw.cache_size_dict.setdefault(f"L{cache.level}", cache.size)
            if saved_size != cache.size:
                log.error(
                    f"Encountered inconsistent cache size information for level {cache.level}: "
                    f"previously {saved_size} bytes, now {cache.size} bytes. "
                    "This may indicate a reporting issue or an unusual system configuration."
                )

        self.sys_hw.caches = sr.ls_caches(misc_info)
        self.sys_hw.atomics = sr.has_atomics(misc_info.system)
        self.sys_hw.interconnect = misc_info.system_interconnect()
        self.sys_hw.n_numa_nodes = misc_info.system.n_nodes()
        self.sys_hw.numa_nodes = OrderedDict()
        # sort by node ID and store in OrderedDict to have consistent ordering
        for node in sorted(misc_info.system.numa_nodes.keys()):
            self.sys_hw.numa_nodes[node] = misc_info.system.numa_nodes[node]
        self.sys_hw.numa_kern_cfg = misc_info.kernel_config_enabled("CONFIG_NUMA")
        self.sys_hw.sockets = misc_info.system.n_packages()

        if self.dmi_definitions is not None:
            try:
                d = self.dmi_definitions.system()
                self.sys_info.manufacturer = d.mfr
                self.sys_info.product_name = d.product
                self.sys_info.version = d.version
                self.sys_info.serial = d.serial
                self.sys_info.uuid = str(d.uuid)
            except (AttributeError, TypeError, ValueError):
                log.error("DMI tables do not contain system information")

        # actual usable memory as per /proc/meminfo MemTotal i.e.
        # physical RAM minus kernel binary and some other bits
        self.memory.total_size = misc_info.system.phys_mem

        if self.dmi_definitions is not None:
            m = MemoryProperties(self.dmi_definitions)
            self.memory.n_channels = m.n_channels
            self.memory.speed = m.speed
            self.memory.data_width = m.data_width
            self.memory.peak_theoretical_bw = m.total_bandwidth()
            self.memory.type_str = m.type_str
            self.memory.manufacturer = m.manufacturer
            self.memory.part_number = m.part_number
            self.bios_info = BiosInfo(dmi_definitions=self.dmi_definitions)

        self.kern_cfg.ver = misc_info.get_kernel_version()
        self.kern_cfg.cfg_file = sr.kernel_config_file()
        self.kern_cfg.build_dir = sr.kernel_build_dir()
        self.kern_cfg.uses_atomics = sr.kernel_uses_atomics(misc_info)
        self.kern_cfg.huge_pages = sr.kernel_hugepages_str()
        self.kern_cfg.thp = sr.kernel_thp(misc_info) or "disabled"
        self.kern_cfg.mpam = misc_info.has_MPAM()
        self.kern_cfg.resctrl = misc_info.has_resctrl()
        self.kern_cfg.distro = misc_info.get_distribution()
        self.kern_cfg.libc_ver = misc_info.get_libc_version()
        self.kern_cfg.boot_info = sr.boot_info_type()
        self.kern_cfg.kpti = misc_info.is_KPTI_enabled()
        self.kern_cfg.lockdown = sr.lockdown_str(misc_info.get_lockdown())
        self.kern_cfg.mitigations = sr.vulnerabilities_str(misc_info.vulnerabilities())

        perf_inst = sr.perf_installed()
        self.perf_feats.has_tools = perf_inst
        if perf_inst:
            self.perf_feats.perf_dir = sr.perf_binary()

        self.perf_feats.perf_opencsd = sr.perf_binary_has_opencsd()
        self.perf_feats.n_counters = misc_info.perf_max_counters()
        self.perf_feats.perf_sampling = sr.perf_noninvasive_sampling()
        self.perf_feats.perf_hw_trace = sr.perf_hardware_trace(misc_info)
        self.perf_feats.paranoid = sr.perf_event_paranoid()
        self.perf_feats.kptr_restrict = sr.kptr_restrict()
        self.perf_feats.userspace_access = sr.perf_user_access()
        self.perf_feats.interconnect = sr.perf_interconnect(misc_info)
        self.perf_feats.kcore = os.path.exists("/proc/kcore")
        self.perf_feats.devmem = os.path.exists("/dev/mem")

        self.perf_feats.bpf.bpf = sr.kernel_supports_bpf(misc_info)
        bpftool = sr.bpftool_installed()
        self.perf_feats.bpf.bpf_tool = bpftool
        if bpftool is not None:
            self.perf_feats.bpf.bpf_tool_ver = bpftool
        self.perf_feats.bpf.bpftrace = sr.bpftrace_installed()

        if self._cfg.advice:
            self.advice = list(sr.advice(misc_info))

        if self._cfg.kernel_config:
            self.kernel_config = sr.kernel_config()

        if self._cfg.vulnerabilities:
            self.vulnerabilities = misc_info.vulnerabilities()

        self._ready = True

        return self

    def show_advice(self):
        """
        Print helpful advice about changes that could improve performance observability.
        """
        printed = False
        for obs, acts in self.advice:
            if not printed:
                # Always start with a blank line before any actions / recommendations are printed
                print("\nActions that can be taken to improve performance tools experience:")
                printed = True
            print("  {}".format(obs))
            for act in acts:
                print("    {}".format(act))

    def to_dict(self):
        """
        Convert only specific dataclass attributes to a dictionary,
        skipping any that are None at the top level.
        """
        if self._loaded_raw_result is not None:
            return self._loaded_raw_result

        allowed_attrs = [
            "report",
            "sys_hw",
            "sys_info",
            "bios_info",
            "memory",
            "kern_cfg",
            "perf_feats",
            "advice",
            "vulnerabilities",
            "kernel_config",
        ]

        result = {}
        for attr in allowed_attrs:
            value = getattr(self, attr, None)
            if value is not None:  # Skip if whole attribute is None
                result[attr] = asdict(value) if is_dataclass(value) else value
        return result

    def _field(self, field_path: str, value, label_width: int = 20, indent: str = "  "):
        return field_string(self.name, field_path, value, label_width=label_width, indent=indent)

    def _section(self, section_name: str, prefix: str = "", suffix: str = ":"):
        return section_string(self.name, section_name, prefix=prefix, suffix=suffix)

    def to_stdout(self):
        """
        Show system characteristics:
        - hardware
        - kernel
        - perf features available
        """
        print(self._section("report"))
        print(self._field("report.collected_time", self.report.collected_time))
        print(self._field("report.asct_ver", self.report.asct_ver))
        print(self._field("report.run_as_root", sr.colorize(self.report.run_as_root)))
        # Hardware features
        print(self._section("hardware", prefix="\n"))
        print(self._field("sys_hw.arch", self.sys_hw.arch))
        print(self._field("sys_hw.n_cpus", self.sys_hw.n_cpus))
        print(self._field("sys_hw.cpu_type", self.sys_hw.cpu_type))
        print(self._field("sys_hw.cpu_features", self.sys_hw.cpu_features))
        # Show a summary of all the caches.
        print(self._field("sys_hw.cache_info", sr.colorize(self.sys_hw.cache_info)))
        print(self._field("sys_hw.cache_line_size", sr.colorize(self.sys_hw.cache_line_size)))
        print(self._field("sys_hw.caches", "").rstrip())
        caches = self.sys_hw.caches
        for c in caches:
            print("    {:d} x {}".format(caches[c], c))
        print(self._field("sys_hw.atomics", sr.colorize(self.sys_hw.atomics)))
        (itype, n) = self.sys_hw.interconnect
        print(self._field("sys_hw.interconnect", "{} x {:d}".format(sr.colorize(itype), n)))
        n_nodes = self.sys_hw.n_numa_nodes
        numa_nodes_str = "{:d}".format(n_nodes)
        if not self.sys_hw.numa_kern_cfg:
            numa_nodes_str += " (CONFIG_NUMA=n)"
        print(self._field("sys_hw.n_numa_nodes", numa_nodes_str))
        if n_nodes > 0:
            for node in range(n_nodes):
                print(
                    "    Node {:d}:\n      size: {:>10}kB\n      cpu_list: {}".format(
                        node, self.sys_hw.numa_nodes[node][0], self.sys_hw.numa_nodes[node][1]
                    )
                )
        print(self._field("sys_hw.sockets", "{:d}".format(self.sys_hw.sockets)))
        # System Infomration from DMI table
        print(self._section("system", prefix="\n", suffix=""))
        print(self._field("sys_info.manufacturer", sr.root_required(self.sys_info.manufacturer)))
        print(self._field("sys_info.product_name", sr.root_required(self.sys_info.product_name)))
        print(self._field("sys_info.version", sr.root_required(self.sys_info.version)))
        print(self._field("sys_info.serial", sr.root_required(self.sys_info.serial)))
        print(self._field("sys_info.uuid", sr.root_required(self.sys_info.uuid)))
        # BIOS information from SMBIOS Type 0 fields
        print(self._section("bios", prefix="\n", suffix=""))
        print(self._field("bios_info.vendor", sr.root_required(self.bios_info.vendor)))
        print(self._field("bios_info.version", sr.root_required(self.bios_info.version)))
        print(self._field("bios_info.release_date", sr.root_required(self.bios_info.release_date)))
        # Memory
        print(self._section("memory", prefix="\n"))
        print(
            self._field(
                "memory.total_size",
                memsize_str(self.memory.total_size, suffix="B", precision=1),
            )
        )
        # this memory info comes from DMI, decoding that requires root priv
        print(self._field("memory.type_str", sr.root_required(self.memory.type_str)))
        print(self._field("memory.manufacturer", sr.root_required(self.memory.manufacturer)))
        print(self._field("memory.part_number", sr.root_required(self.memory.part_number)))
        print(self._field("memory.n_channels", sr.root_required(self.memory.n_channels)))
        print(self._field("memory.speed", sr.root_required(self.memory.speed)))
        print(self._field("memory.data_width", sr.root_required(self.memory.data_width)))

        bw_str = None
        if not sr.is_superuser():
            bw_str = sr.root_required(None)
        elif self.memory.peak_theoretical_bw is not None:
            bw_str = (
                memsize_str(self.memory.peak_theoretical_bw, base="decimal", suffix="B", precision=1)
                + "/s (theoretical) (1GB = 1,000,000,000 bytes)"
            )
        if bw_str:
            print(self._field("memory.peak_theoretical_bw", bw_str))

        # Kernel features
        print(self._section("os", prefix="\n"))
        print(self._field("kern_cfg.ver", self.kern_cfg.ver))
        print(self._field("kern_cfg.cfg_file", sr.colorize(self.kern_cfg.cfg_file)))
        # print("  32-bit support:      %s" % (colorize(s.kernel_config_enabled("CONFIG_COMPAT"))))
        print(self._field("kern_cfg.build_dir", sr.colorize(self.kern_cfg.build_dir)))
        print(self._field("kern_cfg.uses_atomics", sr.colorize(self.kern_cfg.uses_atomics)))
        print(self._field("kern_cfg.huge_pages", sr.colorize(self.kern_cfg.huge_pages)))
        print(self._field("kern_cfg.thp", sr.colorize(self.kern_cfg.thp)))
        if sr._is_arm:
            print(self._field("kern_cfg.mpam", sr.colorize(self.kern_cfg.mpam)))
        print(self._field("kern_cfg.resctrl", sr.colorize(self.kern_cfg.resctrl)))
        print(self._field("kern_cfg.distro", sr.colorize(self.kern_cfg.distro)))
        print(self._field("kern_cfg.libc_ver", sr.colorize(self.kern_cfg.libc_ver)))
        print(self._field("kern_cfg.boot_info", sr.colorize(self.kern_cfg.boot_info)))
        print(self._field("kern_cfg.kpti", sr.colorize(self.kern_cfg.kpti)))
        print(self._field("kern_cfg.lockdown", sr.colorize(self.kern_cfg.lockdown)))
        print(self._field("kern_cfg.mitigations", self.kern_cfg.mitigations))
        # Perf features
        print(self._section("performance", prefix="\n"))
        print(self._field("perf_feats.has_tools", sr.colorize(self.perf_feats.has_tools)))
        if self.perf_feats.has_tools:
            print(self._field("perf_feats.perf_dir", self.perf_feats.perf_dir))
        print(self._field("perf_feats.perf_opencsd", sr.colorize(self.perf_feats.perf_opencsd)))
        print(self._field("perf_feats.n_counters", self.perf_feats.n_counters))
        print(self._field("perf_feats.perf_sampling", sr.colorize_greenred(self.perf_feats.perf_sampling)))
        print(self._field("perf_feats.perf_hw_trace", sr.colorize_greenred(self.perf_feats.perf_hw_trace)))
        print(self._field("perf_feats.paranoid", self.perf_feats.paranoid))  # 0 is not bad, it's good
        print(self._field("perf_feats.kptr_restrict", self.perf_feats.kptr_restrict))
        print(
            self._field(
                "perf_feats.userspace_access",
                sr.colorize_abled(self.perf_feats.userspace_access),
            )
        )
        print(self._field("perf_feats.interconnect", sr.colorize_greenred(self.perf_feats.interconnect)))
        print(self._field("perf_feats.kcore", sr.colorize(self.perf_feats.kcore)))
        print(self._field("perf_feats.devmem", sr.colorize(self.perf_feats.devmem)))
        print(self._section("bpf", prefix="  "))
        print(
            self._field(
                "perf_feats.bpf.bpf",
                sr.colorize_greenred(self.perf_feats.bpf.bpf),
                label_width=26,
                indent="    ",
            )
        )
        print(
            self._field(
                "perf_feats.bpf.bpf_tool",
                sr.colorize(self.perf_feats.bpf.bpf_tool is not None),
                label_width=26,
                indent="    ",
            )
        )
        if self.perf_feats.bpf.bpf_tool is not None:
            print("      {}".format(sr.colorize(self.perf_feats.bpf.bpf_tool)))
        print(
            self._field(
                "perf_feats.bpf.bpftrace",
                sr.colorize(self.perf_feats.bpf.bpftrace),
                label_width=26,
                indent="    ",
            )
        )

        if self.advice is not None:
            self.show_advice()

        if self.kernel_config is not None:
            for k, d in self.kernel_config.items():
                print("  {:<30} = {}".format(k, d))

        if self.vulnerabilities is not None:
            print(self._section("vulnerabilities", prefix="\n"))
            for k, d in self.vulnerabilities.items():
                print("  {:<20} {}".format(k, d))

    def to_csv_str(self):
        """
        Save the sysreport results to a CSV file.
        """
        flat_dict = flatten_dict(self.to_dict())
        df = pd.DataFrame(list(flat_dict.items()))
        return df.to_csv(index=False, header=False)

    @classmethod
    def _normalize_diff_data(cls, data: dict | None) -> dict:
        """Backfill system-info fields so legacy and current runs flatten to the same diff shape."""
        if not isinstance(data, dict):
            return data or {}

        normalized = deepcopy(data)

        bios_info_data = normalized.setdefault("bios_info", {})
        bios_info_data.setdefault("vendor", None)
        bios_info_data.setdefault("version", None)
        bios_info_data.setdefault("release_date", None)

        memory_data = normalized.setdefault("memory", {})
        memory_data.setdefault("manufacturer", None)
        memory_data.setdefault("part_number", None)

        sys_hw_data = normalized.setdefault("sys_hw", {})
        cpu_features = sys_hw_data.get("cpu_features")
        if isinstance(cpu_features, list):
            sys_hw_data["cpu_features"] = {str(index): feature for index, feature in enumerate(cpu_features)}

        return normalized

    @staticmethod
    def _parse_cache_size(size_token: str) -> float | None:
        if not isinstance(size_token, str):
            return None
        match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([KMG])", size_token)
        if match is None:
            return None
        value = float(match.group(1))
        multiplier = {"K": 1024, "M": 1024**2, "G": 1024**3}[match.group(2)]
        return value * multiplier

    @classmethod
    def _derive_cache_size_dict(cls, caches: dict[str, int] | None) -> dict[str, float]:
        if not isinstance(caches, dict):
            return {}

        cache_sizes: dict[str, float] = {}
        for cache_desc in caches:
            if not isinstance(cache_desc, str):
                continue
            parts = cache_desc.split()
            if len(parts) < 2:
                continue
            level = parts[0][:2]
            if level not in {"L1", "L2", "L3"}:
                continue
            size = cls._parse_cache_size(parts[1])
            if size is None:
                continue
            cache_sizes[level] = max(cache_sizes.get(level, 0.0), size)
        return cache_sizes

    def get_diff_data(self):
        if self._loaded_raw_result is None:
            raise RuntimeError(f"result data was not loaded for {self.name}")
        return self._normalize_diff_data(self._loaded_raw_result)

    def deserialize(self, data):
        if not data:
            return
        _, self._loaded_raw_result = self._deserialize_payload(data)
        loaded_data = self._loaded_raw_result or {}
        sys_hw_data = dict(loaded_data.get("sys_hw", {}))
        if "cache_size_dict" not in sys_hw_data:
            derived_cache_sizes = self._derive_cache_size_dict(sys_hw_data.get("caches"))
            if derived_cache_sizes:
                sys_hw_data["cache_size_dict"] = derived_cache_sizes
        interconnect = sys_hw_data.get("interconnect")
        if isinstance(interconnect, list):
            sys_hw_data["interconnect"] = tuple(interconnect)
        numa_nodes = sys_hw_data.get("numa_nodes")
        if isinstance(numa_nodes, dict):
            sys_hw_data["numa_nodes"] = OrderedDict(
                (int(node_id), tuple(node_info))
                for node_id, node_info in sorted(numa_nodes.items(), key=lambda item: int(item[0]))
            )
        loaded_data["sys_hw"] = sys_hw_data

        self.report = report(**loaded_data.get("report", {}))
        self.sys_hw = sys_hw(**sys_hw_data)
        self.sys_info = sys_info(**loaded_data.get("sys_info", {}))
        self.bios_info = BiosInfo(**loaded_data.get("bios_info", {}))
        self.memory = memory(**loaded_data.get("memory", {}))
        perf_feats_data = loaded_data.get("perf_feats", {})
        self.perf_feats = perf_feats(**{
            **perf_feats_data,
            "bpf": bpf(**perf_feats_data.get("bpf", {})),
        })
        self.kern_cfg = kern_cfg(**loaded_data.get("kern_cfg", {}))
        self.advice = loaded_data.get("advice")
        self.vulnerabilities = loaded_data.get("vulnerabilities")
        self.kernel_config = loaded_data.get("kernel_config")
        self._ready = bool(loaded_data)
        self.result = self
