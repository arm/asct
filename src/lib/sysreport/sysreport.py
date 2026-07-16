#!/usr/bin/env python
# ---------------------------------------------------------------------------------
# SPDX-FileCopyrightText: Copyright (C) 2024-2026 Arm Limited and/or its affiliates
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

# This file has been modified.

"""
General system information, beyond what the platform module does.
E.g. cache sizes.

Some of this information might require sudo powers.

Similar to lscpu, but

 - prints more information about software configuration, particularly perf features

 - gives advice on what to change to enable more perf features

 - (TBD) better reporting of heterogeneous/asymmetric systems
"""

from functools import lru_cache
import os
import platform
import subprocess
import multiprocessing
import struct
import asct.core.logger as log

# import gzip for reading /proc/config.gz
try:
    import gzip
except ImportError:
    pass

from .sr_cpulist import system as system_info

from .strcolor import colorize

_is_arm = platform.machine() in ["armv8l", "aarch64"]


def file_data(fn):
    s = None
    if os.path.isfile(fn):
        with open(fn) as f:
            s = f.read().strip()
    return s


def file_int(fn):
    d = file_data(fn)
    return int(d) if d is not None else None


def colorize_redzero(s):
    return colorize(s, "red" if s == 0 else "green")


def colorize_greenred(s):
    return colorize(s, "red" if s is None else "green")


def colorize_abled(s):
    if s is not None:
        return colorize(["disabled", "enabled"][s], ["red", "green"][s])
    return "n/a"


def is_superuser():
    return os.geteuid() == 0


def kernel_config_file():
    """
    Return the filename of the (compressed or uncompressed) kernel config file, or None.
    """
    if os.path.exists("/proc/config.gz"):
        return "/proc/config.gz"
    bconf = "/boot/config-" + platform.release()
    if os.path.exists(bconf):
        return bconf
    return None


def kernel_config():
    """
    Return a map containing the current kernel configuration variables:
      { "CONFIG_XYZ": "y", ... }
    """
    fn = kernel_config_file()
    if fn is None:
        return None
    try:
        opener = gzip.open if fn.endswith(".gz") else open
        mode = "rt" if fn.endswith(".gz") else "r"

        with opener(fn, mode) as f:
            s = f.read()
    except (OSError, ValueError, TypeError, LookupError, RuntimeError):
        return None
    ck = {}
    if hasattr(s, "decode"):
        try:
            s = s.decode()
        except UnicodeDecodeError as e:
            log.warning("Failed to decode kernel config file: %s", e)

    for ln in s.split("\n"):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        ix = ln.index("=")
        ck[ln[:ix]] = ln[ix + 1 :]
    return ck


def run_cmd(cmd, log_func=log.debug):
    log.debug(">>> %s", cmd)
    args = cmd.split()
    try:
        p = subprocess.run(args, capture_output=True, check=True)
        log.debug(f"{p}")
    except FileNotFoundError:
        log_func(f"Command not found: {cmd}")
        raise
    except PermissionError:
        log_func(f"Permission denied when running command: {cmd}")
        raise
    except (OSError, subprocess.CalledProcessError) as e:
        log_func(f"Error running sysreport command: {e}")
        raise

    return (p.stdout, p.stderr)


def file_data_keys(fn):
    """
    Create a Python map from a file of the form
      a=b
      c=d
    """
    s = file_data(fn)
    if s is None:
        return None
    lr = s.split("\n")
    data = {}
    for ln in lr:
        ix = ln.find("=")
        if ix > 0:
            name = ln[:ix]
            value = ln[ix + 1 :].strip()
            if value.startswith('"'):
                value = value[1:-1]
            data[name] = value
    return data


def file_data_key(fn, k):
    m = file_data_keys(fn)
    if m is not None and k in m:
        return m[k]
    return None


def find_file_in_tree(d, fn):
    """
    If a file is found anywhere in a directory tree, return the first one found.
    Otherwise, return None. To avoid recursion, don't follow links.
    """
    for dp, _dirs, files in os.walk(d):
        if fn in files:
            return os.path.join(dp, fn)
    return None


def iomem_areas(toplevel=False):
    """
    Return the names of areas described in /proc/iomem. As non-root, we don't see the addresses.
    """
    areas = {}
    with open("/proc/iomem") as f:
        for ln in f:
            if toplevel and ln.startswith(" "):
                continue
            area = ln.strip().split(" : ")[1]
            areas[area] = True
    return areas.keys()


def acpi_irqs():
    """
    Get the IRQ numbers for PMU, SPE and TRBE from the APIC table.
    Not applicable to non-Arm, or to DT systems.
    """
    if not _is_arm:
        return None
    if not is_superuser():
        return None
    try:
        irqs = {}
        with open("/sys/firmware/acpi/tables/APIC", "rb") as f:
            f.read(4)  # signature (b"APIC")
            f.read(32)  # general ACPI header
            f.read(8)  # APIC
            while True:
                ih = f.read(2)
                if not ih:
                    break
                (itype, ilen) = struct.unpack("<BB", ih)
                identifier = ih + f.read(ilen - 2)
                if itype == 0xB:
                    (_, _, _, _, _, pmu_irq, _, _, _, _, _, _, _, _, _, spe_irq) = struct.unpack(
                        "<IIIIIIQQQQIQQBBH", identifier[:80]
                    )
                    if pmu_irq:
                        irqs["PMU"] = pmu_irq
                    if spe_irq:
                        irqs["SPE"] = spe_irq
                    if len(identifier) >= 82:
                        trbe_irq = struct.unpack("<H", identifier[80:82])[0]
                        if trbe_irq:
                            irqs["TRBE"] = trbe_irq
                    break  # stop at first GICC
    except (OSError, struct.error, ValueError) as e:
        log.warning("Failed to read ACPI APIC table: %s", e)
        return None
    return irqs


_arm_cpu_arch = {
    (0x41, 0xD03): (8, 0),  # Cortex-A53
    (0x41, 0xD07): (8, 0),  # Cortex-A57
    (0x41, 0xD08): (8, 0),  # Cortex-A72
    (0x41, 0xD0C): (8, 2),  # Neoverse N1
    (0x41, 0xD40): (8, 4),  # Neoverse V1
    (0x41, 0xD49): (9, 0),  # Neoverse N2
    (0x41, 0xD4F): (9, 0),  # Neoverse V2
    (0x41, 0xD83): (9, 2),  # Neoverse V3AE
    (0x41, 0xD84): (9, 2),  # Neoverse V3
    (0x6D, 0xD49): (9, 0),  # Azure Cobalt 100
}


def arm_arch(s):
    """
    Arm: Try to deduce Arm architecture (v8.4, v9.2 etc.) from CPU types.
    """
    arch = None
    for spec in s.cpu_types():
        key = (spec.implementer_code, spec.model_code)
        if key in _arm_cpu_arch:
            narch = _arm_cpu_arch[key]
            if arch is not None and arch != narch:
                raise AssertionError(f"mismatch: {arch=} vs. {narch=}")
            arch = narch
    return arch


class System:
    """
    Miscellaneous information about a complete system.
    """

    def __init__(self):
        self.system = system_info()
        if _is_arm:
            self.arm_arch = arm_arch(self)
        self.kernel_config = kernel_config()
        self.cached_vulnerabilities = None
        self.cached_irqs = None
        self._perf_max_counters = None

    def cpu_types(self):
        """
        Return a list of CPU types. This will only contain more than one
        entry for heterogeneous (big.LITTLE) systems.
        It is not indexed by CPU number.
        """
        return self.system.spec_to_cpulist.keys()

    def get_cpu_features(self):
        """
        Return CPU features already found in self.system. Just use information from the first CPU found.
        Note:
            This method assumes that all CPUs in the system have the same features.
            If the system has heterogeneous CPUs, the returned features may only represent the first CPU found
            and not all of them.
        """
        # Get the first CPU and use its features
        one_cpu = next(iter(self.system.cpus()), None)
        if one_cpu is None:
            return []
        return one_cpu.spec.features

    def architecture(self):
        if _is_arm and self.arm_arch is not None:
            (ma, mi) = self.arm_arch
            return "ARMv{:d}.{:d}".format(ma, mi)
        return platform.machine()

    def is_arm_architecture(self, ma, mi=0):
        return _is_arm and self.arm_arch is not None and self.arm_arch >= (ma, mi)

    def get_distribution(self):
        """
        Return a free-format string describing the distribution.
        """
        s = file_data("/etc/redhat-release")
        if s is not None:
            s = s.replace("Red Hat Enterprise Linux", "RHEL")
            s = s.replace(" release", "")
            if s.endswith(")"):
                s = s[: s.index(" (")]
        else:
            for path, key in (
                ("/etc/lsb-release", "DISTRIB_DESCRIPTION"),
                ("/etc/os-release", "NAME"),
            ):
                s = file_data_key(path, key)
                if s is not None:
                    break
        return s

    def is_ACPI(self):
        return boot_info_type() == "ACPI"

    def get_kernel_version(self):
        """
        Get kernel version, as a string, e.g. "6.5.1-rc7" returns "6.5.1"
        """
        s = platform.release()
        ix = s.find("-")
        if ix >= 0:
            s = s[:ix]
        return s

    def get_kernel_maj_min(self):
        """
        Get kernel version as a tuple, e.g. (6, 5)
        """
        v = self.get_kernel_version().split(".")
        return (int(v[0]), int(v[1]))

    def is_kernel_at_least(self, v):
        return self.get_kernel_maj_min() >= v

    def get_kernel_config(self, var, default=None):
        if not var.startswith("CONFIG_"):
            raise ValueError(f"kernel config variable must start with CONFIG_, given: {var}")
        if self.kernel_config is not None and var in self.kernel_config:
            return self.kernel_config[var]
        return default

    def kernel_config_enabled(self, var):
        return self.get_kernel_config(var) in ["y", "m"]

    def has_loadable_kernel_module(self, ko):
        """
        Check if a loadable kernel module is present in /lib/modules.
        Caller must know the full path (starting with "kernel").
        """
        if not ko.endswith(".ko"):
            raise ValueError(f"name must end with .ko, given: {ko}")
        mdir = "/lib/modules/" + platform.release()
        return find_file_in_tree(mdir, ko)

    def get_cache_line_size(self) -> int | None:
        """
        Even if cache info isn't available under /sys/bus/cpu, we ought to be
        able to get cache line size.
        """
        try:
            (out, _err) = run_cmd("getconf LEVEL1_DCACHE_LINESIZE", log.warning)
        except (FileNotFoundError, PermissionError, subprocess.CalledProcessError) as e:
            # minimal busybox system might lack getconf
            log.warning(f"Failed to get cache line size using getconf: {e}")
            return None
        try:
            cache_line_size = int(out)
        except ValueError:
            log.warning(f"Failed to parse cache line size from getconf output: {out}")
            return None
        return cache_line_size

    def get_libc_version(self):
        lv = platform.libc_ver()
        return "{} {}".format(lv[0], lv[1])

    def get_cpu_count(self, online_only=True):
        # Get the number of online CPUs
        n1 = self.system.n_cpus(online_only=online_only)
        if online_only:
            n2 = multiprocessing.cpu_count()
            if n1 != n2:
                raise ValueError(f"mismatch on number of CPUs: {n1} vs {n2}")
        return n1

    def irqs(self):
        """
        Arm: get the IRQ numbers for performance features. This tells us whether
        the features are exposed by firmware (or hypervisor, in the case of a guest).
        """
        if self.cached_irqs is None:
            irqs = acpi_irqs()
            if irqs is None:
                irqs = {}  # distinguish not yet obtained from n/a
            self.cached_irqs = irqs
        return self.cached_irqs

    def has_irq(self, s):
        """
        Check if an IRQ is registered, for PMU, SPE or TRBE
        """
        return s in self.irqs()

    def perf_max_counters(self):
        if self._perf_max_counters is None:
            self._perf_max_counters = perf_max_counters()
        return self._perf_max_counters

    def vulnerabilities(self):
        if self.cached_vulnerabilities is None:
            self.cached_vulnerabilities = {}
            vd = "/sys/devices/system/cpu/vulnerabilities"
            if os.path.isdir(vd):
                for rd in os.listdir(vd):
                    d = os.path.join(vd, rd)
                    try:
                        vul = file_data(d)
                    except (PermissionError, UnicodeDecodeError, FileNotFoundError, OSError):
                        vul = None
                    self.cached_vulnerabilities[rd] = vul
        return self.cached_vulnerabilities

    def is_KPTI_enabled(self):
        for vm in self.vulnerabilities().values():
            if vm is None:
                return None
            if vm == "Mitigation: PTI":
                return True
        return False

    def get_lockdown(self):
        ld = self.get_kernel_config("CONFIG_LSM")
        if ld is not None:
            if ld[0] == '"':
                ld = ld[1:-1]
            ld = ld.split(",")
        return ld

    def system_interconnect(self):
        """
        Check if this system has an Arm CMN interconnect, by looking at /proc/iomem.
        There seems to be no better way than looking for specific ACPI ids.
        We'll assume that if a system does have CMN, it will be homogeneous.
        """
        itype = None
        n = 1
        for a in iomem_areas(toplevel=True):
            a = a.split(":")[0]
            if a in ["ARMHC600", "ARMHC650", "ARMHC700"]:
                t = "CMN-" + a[5:]
                if itype is None:
                    itype = t
                elif t == itype:
                    n += 1
                else:
                    itype = "<mixed?>"
                    n += 1
        return (itype, n)

    def has_CMN_interconnect(self):
        """
        Return true if the system has an Arm CMN interconnect of any kind.
        """
        if has_event_source("arm_cmn_0"):
            # If the arm-cmn PMU driver is enabled, there must be a CMN.
            return True
        # Otherwise, scan for interconnects.
        (ic, _n) = self.system_interconnect()
        return ic is not None and ic.startswith("CMN-")

    def has_MPAM(self):
        return self.get_kernel_config("CONFIG_MPAM") == "y"

    def has_resctrl(self):
        return os.path.exists("/sys/fs/resctrl")

    def cpu_has_SPE(self):
        """
        Report if the system has Arm's SPE (Statistical Profiling Extension).
        This is not exposed as a HWCAP and we can't infer it from architecture level,
        because mobile cores tend not to have it. We have to do it by model name/number.
        Also report (by returning -1) if the implementation is known to be biased.
        """
        spe_type = 0  # not present
        for ct in self.cpu_types():
            if ct.str_full().startswith("Arm Neoverse"):
                if spe_type == 0:
                    spe_type = 1
                if ct.implementer_code == 0x41:
                    if ct.model_code == 0xD0C and ct.stepping < (4, 1):
                        spe_type = -1  # erratum 1694299
                    elif ct.model_code == 0xD40 and ct.stepping < (1, 1):
                        spe_type = -1  # erratum 1694300
        return spe_type


def kernel_build_dir(check=True):
    build_dir = "/lib/modules/" + platform.release() + "/build"
    if check and not os.path.isdir(build_dir):
        return None
    return build_dir


def is_exec_shell_script(file):
    """
    Returns a boolean indicating whether the specified file is an executable
    shell script or not.
    """
    is_script = False
    if not os.path.exists(file):
        return False
    with open(file, "rb") as f:
        maybe_shebang_bytes = f.read(2)
        if maybe_shebang_bytes == b"#!" and os.access(file, os.X_OK):
            is_script = True
    return is_script


@lru_cache(maxsize=1)
def perf_binary():
    """
    Get the canonical location of the perf binary. This might not exist.
    Not thread safe!

    /usr/bin/perf is usually a redirector script, but it's possible that perf
    was built by hand and copied to this location.

    # If $PATH contains a redirector script, return the actual install path.
    # Otherwise assume it's a user-installed binary and honour that path.
    """
    try:
        (out, _err) = run_cmd("which perf")
    except (OSError, subprocess.CalledProcessError):
        return ""
    else:
        found_path = out.decode().strip()
        if is_exec_shell_script(found_path):
            found_path = "/usr/lib/linux-tools/" + platform.release() + "/perf"
        return found_path if os.path.exists(found_path) else ""


def perf_binary_imports(lib):
    perf_bin = perf_binary()
    if not perf_bin:
        return False
    try:
        (out, _err) = run_cmd(f"/usr/bin/ldd {perf_bin}")
    except (OSError, subprocess.CalledProcessError):
        return None
    return lib in out.decode()


def perf_binary_has_opencsd():
    return perf_binary_imports("libopencsd.so")


@lru_cache(maxsize=1)
def perf_installed():
    """
    Check whether perf command-line tools are installed.
    """
    perf_bin = perf_binary()
    if not perf_bin:
        return False

    # Run a very simple "perf" subcommand - don't use "perf stat" as this may fail
    # for unprivileged due to security settings, even if events are available.
    try:
        rc = subprocess.run(
            [perf_bin, "config"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).returncode
    except (OSError, subprocess.CalledProcessError) as e:
        log.warning(f"Error running command: {e}")
        return False
    return rc == 0


def perf_max_counters():
    """
    Find out how many hardware PMU counters are available, by creating successively larger groups.
    As non-weak groups (not marked with 'W'), these should not fall back to ungrouped.
    But perf won't report failure to create a group via the return code,
    so we have to process the output.

    Note: this may under-report if there is other perf activity on the system,
    e.g. a privileged user running a perf command that pins system-wide counters.

    Currently this depends on perf tools being installed.
    We could make it more robust by using perf_event_open (via ctypes).

    We use instructions as a proxy for general-purpose counters.
    The dedicated cycle counter is not included.
    """
    if not perf_installed():
        return None
    for i in range(1, 31):
        # Use braces to ensure that counters are scheduled as a group.
        events = "{" + ",".join(["instructions:u"] * i) + "}"
        cmd = "perf stat -x, -e " + events + " -- true"
        try:
            (_out, err) = run_cmd(cmd, log.warning)
        except (OSError, subprocess.CalledProcessError):
            return None
        if err.decode().startswith("<not"):
            return i - 1
    return None


def perf_event_paranoid():
    return file_int("/proc/sys/kernel/perf_event_paranoid")


def kptr_restrict():
    try:
        return file_int("/proc/sys/kernel/kptr_restrict")
    except (OSError, UnicodeDecodeError):
        return None


def has_event_source(s):
    # /sys/bus/event_source/devices contains links to /sys/devices,
    # for those devices which provide events
    return os.path.exists("/sys/bus/event_source/devices/" + s)


def perf_precise_sampling(s):
    if platform.machine() == "x86_64" and s.system.has_cpu_feature("pebs"):
        return "PEBS"
    return None


def perf_noninvasive_sampling():
    if _is_arm and has_event_source("arm_spe_0"):
        return "SPE"
        # It might be disabled because kpti is enabled
    return None


def perf_hardware_trace(s):
    """
    Return true if the platform supports non-invasive program flow tracing,
    e.g. Arm ETM/ETE, or Intel PT.
    """
    if platform.machine() == "x86_64":
        if s.system.has_cpu_feature("intel_pt"):
            return "PT"
    elif (
        _is_arm
        and os.path.exists("/sys/bus/event_source/devices/cs_etm")
        and list(os.listdir("/sys/bus/coresight/devices"))
    ):
        return "ETM"
    return None


def perf_user_access():
    return file_int("/proc/sys/kernel/perf_user_access")


def perf_interconnect(s):
    """
    Return true if interconnect performance metrics are available, None if unknown.
    """
    if _is_arm and s.has_CMN_interconnect():
        return has_event_source("arm_cmn_0")
    return None  # other interconnect - don't know


def boot_info_type():
    s = None
    # Either /sys/firmware/acpi or /proc/acpi seems to work as a test for ACPI.
    # /proc/acpi is often empty though.
    if os.path.isdir("/sys/firmware/acpi"):
        s = "ACPI"
    if os.path.isdir("/proc/device-tree"):
        if s is not None:
            raise AssertionError("both acpi and device-tree detected as boot_info_types!")
        s = "DT"
    return s


def cache_info():
    """
    Report what kind of information is available about cache geometry.
    """
    # sc = "/sys/bus/cpu/devices/cpu0/cache"
    sc = "/sys/devices/system/cpu/cpu0/cache"
    if os.path.isdir(sc):
        s0 = sc + "/index0"
        cl = []
        if os.path.isfile(s0 + "/size"):
            cl.append("size")
        if os.path.isfile(s0 + "/ways_of_associativity"):
            cl.append("associativity")
        if os.path.isfile(s0 + "/shared_cpu_list"):
            cl.append("sharing")
        if not cl:
            return None
        return ", ".join(cl)
    return None


def has_atomics(s):
    """
    Report whether the platform has atomic opertations such as atomic add.
    Load-exclusive/store-exclusive are not considered here.
    """
    if platform.machine() == "x86_64":
        return True
    return s.has_cpu_feature("atomics")


def kernel_uses_atomics(s):
    if not has_atomics(s.system):
        return False
    if platform.machine() == "x86_64":
        return True
    if platform.machine() == "aarch64" and s.kernel_config is not None:
        return s.kernel_config_enabled("CONFIG_ARM64_LSE_ATOMICS")
    return None


def kernel_hugepages(skip_zero=False):
    """
    Return a list of (page size, nr_hugepages) configured to the kernel.
    It's tempting to read /proc/sys/vm/nr_hugepages, but this only reports
    pages of a specific size.
    """
    # return file_int("/proc/sys/vm/nr_hugepages")
    hpdir = "/sys/kernel/mm/hugepages"
    if not os.path.exists(hpdir):
        return

    for d in os.listdir(hpdir):
        if not d.startswith("hugepages-"):
            continue
        dp = os.path.join(hpdir, d)
        nr = file_int(dp + "/nr_hugepages")
        if nr > 0 or (not skip_zero):
            yield (d[10:], nr)


def kernel_hugepages_str(skip_zero=False):
    huge_pages = list(kernel_hugepages(skip_zero=skip_zero))
    if huge_pages:
        return ", ".join(["{}: {:d}".format(sz, nr) for (sz, nr) in huge_pages])
    return "disabled"


def kernel_thp(s):
    """
    Return the enablement state of transparent huge pages.
    If the kernel has been built with CONFIG_TRANSPARENT_HUGEPAGE=n the file
    below will not exist.
    """
    if not s.kernel_config_enabled("CONFIG_TRANSPARENT_HUGEPAGE"):
        return None
    hps = file_data("/sys/kernel/mm/transparent_hugepage/enabled")
    if hps is None:
        return None
    for h in hps.split():
        if h.startswith("["):
            return h[1:-1]
    return None


def lockdown_str(ld):
    if ld is not None:
        return ", ".join([str(s) for s in ld])
    return ld


def kernel_supports_bpf(s):
    """
    Check the kernel config for CONFIG_BPF - There might be other BPF config options we might want to check
    """
    return s.kernel_config_enabled("CONFIG_BPF")


def bpftool_installed():
    """
    Check whether the bpftool is installed and what it supports.
    On some systems it might exist as a script informing users how to install.
    """
    cmd = "/usr/sbin/bpftool"
    if os.path.exists(cmd):
        try:
            (out, err) = run_cmd(cmd + " -V")
        except (OSError, subprocess.CalledProcessError) as e:
            log.error("Failed to run bpftool: %s", e)
        else:
            if not err.decode().startswith("WARNING: bpftool not found"):
                # Strip the 'b' and replace the newline with a space so it's displayed on a single line
                return out.decode().replace("\n", " ")
            # The bpftool exists as a script, essentially it's not installed.
            # Running it simply informs the user to install the tool
    return None


def bpftrace_installed():
    """
    Check whether the bpftrace tool is installed
    """
    cmd = "/usr/bin/bpftrace"
    if os.path.exists(cmd):
        try:
            (out, _err) = run_cmd(cmd + " -V")
        except (OSError, subprocess.CalledProcessError):
            return None
        return out.decode()
    return None


def vulnerabilities_str(vl):
    sl = []
    for k, v in vl.items():
        if v is None:
            # e.g. permission denied when we tried to read it
            sl.append("{}".format(k))
        elif v.startswith("Mitigation:"):
            sl.append("{}:{}".format(k, v[12:]))
        elif v == "Not affected":
            pass
        else:
            sl.append("{}:{}".format(k, v))
    return "; ".join(sl)


def advice(s):
    """
    Give some advice about system changes that would improve observability.

    Advice may make assumptions about the user's intended use case,
    and their level of privilege. E.g. it may say things like
      "to enable performance analysis of the kernel, rebuild with CONFIG..."
    For some users this might not be either appropriate or actionable.
    """
    if False:
        if len(list(kernel_hugepages(skip_zero=True))) == 0:
            yield ("huge pages not enabled", [])
    if not s.is_kernel_at_least((5, 0)):
        yield (
            "kernel version {} may lack support for new perf features".format(s.get_kernel_version()),
            ["update kernel"],
        )
    if not perf_installed():
        # TBD: we could advise on how to install perf, e.g.
        #   Ubuntu: "sudo apt-get install linux-tools-`uname -r`"
        #   Amazon Linux: "yum install perf"
        yield (
            "perf tools not installed",
            ["install perf package (see https://learn.arm.com/install-guides/perf)", "or build from kernel sources"],
        )
    # ensure perf is built with OpenCSD
    elif _is_arm and not perf_binary_has_opencsd():
        yield ("perf tools cannot decode hardware trace", ["build with CORESIGHT=1"])
    if perf_event_paranoid() > 0:
        yield ("System-level events can only be monitored by privileged users", ["sysctl kernel.perf_event_paranoid=0"])
    if perf_event_paranoid() <= 3 and not s.perf_max_counters():
        corrs = []
        if _is_arm and not s.has_irq("PMU"):
            corrs.append("ensure APIC table describes PMU interrupt")
        yield ("Hardware perf events are not available", corrs)
    if not os.path.exists("/proc/kcore"):
        yield ("/proc/kcore not enabled, kernel profiling degraded", ["rebuild kernel with CONFIG_PROC_KCORE"])
    if not perf_interconnect(s) and s.has_CMN_interconnect():
        ck = s.get_kernel_config("CONFIG_ARM_CMN")
        problem = "CMN interconnect perf events not enabled"
        if ck in ["m", "y"]:
            yield (problem, ["check boot log for CMN driver problems"])
        else:
            yield (problem, ["rebuild kernel with CONFIG_ARM_CMN enabled"])
    if _is_arm:
        spe = s.cpu_has_SPE()
        if spe:
            corrs = []
            if not perf_noninvasive_sampling():
                # CPU has SPE, but apparently not available in perf
                if s.is_KPTI_enabled():
                    corrs.append("disable kernel page-table isolation: boot with kpti=off")
                if not s.has_irq("SPE"):
                    corrs.append("ensure APIC table describes SPE interrupt")
                ck = s.get_kernel_config("CONFIG_ARM_SPE_PMU")
                if ck == "n":
                    corrs.append("ensure kernel is built with SPE support (CONFIG_ARM_SPE_PMU)")
                elif ck == "m" and not s.has_loadable_kernel_module("arm_spe_pmu.ko"):
                    corrs.append("kernel module arm_spe_pmu.ko must be built")
                yield ("non-invasive sampling (SPE) not enabled", corrs)
            if spe == -1:
                yield (
                    "SPE sampling on {} is biased (hardware erratum)".format(next(iter(s.cpu_types()))),
                    ["allow for bias"],
                )
    if _is_arm and not perf_hardware_trace(s):
        corrs = []
        # advice for v8:
        #  - CoreSight system description in device tree / ACPI DSDT
        #  - rebuild with CONFIG_CORESIGHT
        # advice for v9:
        #  - describe TRBE interrupt in ACPI APIC (or DT equivalent)
        #  - rebuild with CONFIG_CORESIGHT
        if not s.kernel_config_enabled("CONFIG_CORESIGHT"):
            corrs.append("rebuild kernel with CONFIG_CORESIGHT")
        if s.is_arm_architecture(9):
            if s.is_ACPI() and not s.has_irq("TRBE"):
                corrs.append("ensure APIC table describes TRBE interrupt")
        elif s.is_ACPI():
            corrs.append("ensure ACPI describes CoreSight trace fabric")
        yield ("hardware trace not enabled", corrs)


def ls_caches(s):
    caches: dict[str, int] = {}  # key = cache name, value = n caches
    for c in s.system.caches():
        ct = "{} {}".format(c.type_str(), c.geometry_str())
        if ct not in caches:
            caches[ct] = 0
        caches[ct] += 1
    return {k: caches[k] for k in sorted(caches.keys())}


def root_required(s):
    if is_superuser():
        return s or "N/A"
    return s or "root required - run with sudo"
