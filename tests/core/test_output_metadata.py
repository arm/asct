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

from collections import OrderedDict
from dataclasses import fields as dataclass_fields, is_dataclass

import pytest

from asct.core.recipes.impl.system_info import SystemInfo
from asct.core.recipes.impl import system_info
from asct.lib.output_metadata import fields


@pytest.fixture
def fresh_system_info(monkeypatch):
    monkeypatch.setattr(SystemInfo, "_inst", None)
    return SystemInfo()


def test_load_field_metadata_caches_json_load(monkeypatch, tmp_path):
    metadata_path = tmp_path / fields.FIELD_METADATA_FILE
    metadata_path.write_text(
        '{"system-info": {"sections": {"report": {"label": "Report"}}, "field": {"label": "Field"}}}',
        encoding="utf-8",
    )

    json_load_calls = 0
    original_json_load = fields.json.load

    def counting_json_load(*args, **kwargs):
        nonlocal json_load_calls
        json_load_calls += 1
        return original_json_load(*args, **kwargs)

    monkeypatch.setattr(fields, "files", lambda _package: tmp_path)
    monkeypatch.setattr(fields.json, "load", counting_json_load)

    fields.load_field_metadata.cache_clear()
    try:
        assert fields.get_field_label("system-info", "field") == "Field"
        assert fields.get_section_label("system-info", "report") == "Report"
        assert fields.get_field_metadata_for_recipes(["system-info"])["system-info"]["field"]["label"] == "Field"
        assert json_load_calls == 1
    finally:
        fields.load_field_metadata.cache_clear()


def test_field_metadata_sections_are_declared():
    fields.load_field_metadata.cache_clear()
    try:
        metadata = fields.load_field_metadata()
    finally:
        fields.load_field_metadata.cache_clear()

    missing_sections = []
    for recipe_name, recipe_metadata in metadata.items():
        declared_sections = set(recipe_metadata.get("sections", {}))
        for field_path, field_metadata in recipe_metadata.items():
            if field_path == "sections":
                continue
            section_name = field_metadata.get("section")
            if section_name and section_name not in declared_sections:
                missing_sections.append((recipe_name, field_path, section_name))

    assert missing_sections == []


def test_system_info_metadata_covers_serialized_fields(fresh_system_info):
    sysinfo = fresh_system_info
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

    expected_fields = set()
    for attr in allowed_attrs:
        value = getattr(sysinfo, attr, None)
        if not is_dataclass(value):
            expected_fields.add(attr)
            continue

        for field in dataclass_fields(value):
            field_value = getattr(value, field.name, None)
            if is_dataclass(field_value):
                expected_fields.update(f"{attr}.{field.name}.{nested.name}" for nested in dataclass_fields(field_value))
            else:
                expected_fields.add(f"{attr}.{field.name}")

    fields.load_field_metadata.cache_clear()
    try:
        metadata = fields.load_field_metadata()["system-info"]
    finally:
        fields.load_field_metadata.cache_clear()

    metadata_fields = {field_path for field_path in metadata if field_path != "sections"}
    assert expected_fields - metadata_fields == set()


def test_system_info_stdout_preserves_legacy_labels(capsys, monkeypatch, fresh_system_info):
    monkeypatch.setattr(system_info.sr, "colorize", lambda value: value)
    monkeypatch.setattr(system_info.sr, "colorize_greenred", lambda value: value)
    monkeypatch.setattr(system_info.sr, "colorize_abled", lambda value: value)
    monkeypatch.setattr(system_info.sr, "root_required", lambda value: value)
    monkeypatch.setattr(system_info.sr, "is_superuser", lambda: True)
    monkeypatch.setattr(system_info.sr, "_is_arm", True)

    sysinfo = fresh_system_info
    sysinfo.report.collected_time = "2026-01-02 03:04:05+00:00"
    sysinfo.report.asct_ver = "1.2.3"
    sysinfo.report.run_as_root = True

    sysinfo.sys_hw.arch = "ARMv8"
    sysinfo.sys_hw.n_cpus = 4
    sysinfo.sys_hw.cpu_type = "4 x CPU"
    sysinfo.sys_hw.cpu_features = ["fp", "asimd"]
    sysinfo.sys_hw.cache_info = "size, associativity, sharing"
    sysinfo.sys_hw.cache_line_size = 64
    sysinfo.sys_hw.caches = {"L1D 64K": 4}
    sysinfo.sys_hw.atomics = True
    sysinfo.sys_hw.interconnect = ("CMN", 1)
    sysinfo.sys_hw.n_numa_nodes = 1
    sysinfo.sys_hw.numa_kern_cfg = True
    sysinfo.sys_hw.numa_nodes = OrderedDict([(0, (1024, [0, 1, 2, 3]))])
    sysinfo.sys_hw.sockets = 1

    sysinfo.sys_info.manufacturer = "Vendor"
    sysinfo.sys_info.product_name = "Product"
    sysinfo.sys_info.version = "SystemVersion"
    sysinfo.sys_info.serial = "Serial"
    sysinfo.sys_info.uuid = "UUID"
    sysinfo.bios_info.vendor = "BiosVendor"
    sysinfo.bios_info.version = "BiosVersion"
    sysinfo.bios_info.release_date = "2026-01-01"

    sysinfo.memory.total_size = 1024
    sysinfo.memory.type_str = "DDR"
    sysinfo.memory.manufacturer = "MemVendor"
    sysinfo.memory.part_number = "Part"
    sysinfo.memory.n_channels = 2
    sysinfo.memory.speed = 3200
    sysinfo.memory.data_width = 64
    sysinfo.memory.peak_theoretical_bw = 4096

    sysinfo.kern_cfg.ver = "kernel"
    sysinfo.kern_cfg.cfg_file = "config"
    sysinfo.kern_cfg.build_dir = "build"
    sysinfo.kern_cfg.uses_atomics = True
    sysinfo.kern_cfg.huge_pages = "huge"
    sysinfo.kern_cfg.thp = "madvise"
    sysinfo.kern_cfg.mpam = False
    sysinfo.kern_cfg.resctrl = False
    sysinfo.kern_cfg.distro = "distro"
    sysinfo.kern_cfg.libc_ver = "libc"
    sysinfo.kern_cfg.boot_info = "ACPI"
    sysinfo.kern_cfg.kpti = False
    sysinfo.kern_cfg.lockdown = "none"
    sysinfo.kern_cfg.mitigations = "mitigations"

    sysinfo.perf_feats.has_tools = True
    sysinfo.perf_feats.perf_dir = "/usr/bin/perf"
    sysinfo.perf_feats.perf_opencsd = False
    sysinfo.perf_feats.n_counters = 6
    sysinfo.perf_feats.perf_sampling = "SPE"
    sysinfo.perf_feats.perf_hw_trace = None
    sysinfo.perf_feats.paranoid = 0
    sysinfo.perf_feats.kptr_restrict = 1
    sysinfo.perf_feats.userspace_access = "disabled"
    sysinfo.perf_feats.interconnect = True
    sysinfo.perf_feats.kcore = True
    sysinfo.perf_feats.devmem = False
    sysinfo.perf_feats.bpf.bpf = True
    sysinfo.perf_feats.bpf.bpf_tool = "bpftool version"
    sysinfo.perf_feats.bpf.bpftrace = False

    sysinfo.to_stdout()

    output_lines = capsys.readouterr().out.splitlines()
    expected_lines = [
        "System feature report:",
        "  Collected:           2026-01-02 03:04:05+00:00",
        "  ASCT version:        1.2.3",
        "  Running as root:     True",
        "",
        "System hardware:",
        "  Architecture:        ARMv8",
        "  CPUs:                4",
        "  CPU types:           4 x CPU",
        "  CPU features:        ['fp', 'asimd']",
        "  Cache info:          size, associativity, sharing",
        "  Cache line size:     64",
        "  Caches:",
        "    4 x L1D 64K",
        "  Atomic operations:   True",
        "  Interconnect:        CMN x 1",
        "  NUMA nodes:          1",
        "    Node 0:",
        "      size:       1024kB",
        "      cpu_list: [0, 1, 2, 3]",
        "  Sockets:             1",
        "",
        "System Information",
        "  Manufacturer:        Vendor",
        "  Product Name:        Product",
        "  Version:             SystemVersion",
        "  Serial:              Serial",
        "  UUID:                UUID",
        "",
        "BIOS Information",
        "  Vendor:              BiosVendor",
        "  Version:             BiosVersion",
        "  Release Date:        2026-01-01",
        "",
        "Memory:",
        "  System memory:       1.0KiB",
        "  Type:                DDR",
        "  Manufacturer:        MemVendor",
        "  Part Number:         Part",
        "  # of channels:       2",
        "  Speed:               3200",
        "  Data Width:          64",
        "  Peak bandwidth:      4.1kB/s (theoretical) (1GB = 1,000,000,000 bytes)",
        "",
        "OS configuration:",
        "  Kernel:              kernel",
        "  Config:              config",
        "  Build dir:           build",
        "  Uses atomics:        True",
        "  Huge pages:          huge",
        "  Transparent HP:      madvise",
        "  MPAM configured:     False",
        "  resctrl:             False",
        "  Distribution:        distro",
        "  libc version:        libc",
        "  Boot info:           ACPI",
        "  KPTI enforced:       False",
        "  Lockdown:            none",
        "  Mitigations:         mitigations",
        "",
        "Performance features:",
        "  perf tools:          True",
        "  perf installed at:   /usr/bin/perf",
        "  perf with OpenCSD:   False",
        "  perf counters:       6",
        "  perf sampling:       SPE",
        "  perf HW trace:       None",
        "  perf paranoid:       0",
        "  kptr_restrict:       1",
        "  perf in userspace:   disabled",
        "  interconnect perf:   True",
        "  /proc/kcore:         True",
        "  /dev/mem:            False",
        "  eBPF:",
        "    kernel configured for BPF: True",
        "    bpftool installed:         True",
        "      bpftool version",
        "    bpftrace installed:        False",
    ]

    assert output_lines == expected_lines
