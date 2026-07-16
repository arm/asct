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

from cmntools.dmi import DMI, DMI_BIOS
from asct.core import logger as log
from dataclasses import InitVar, dataclass


class ASCT_DMI(DMI):
    """
    Local extension over cmntools DMI reader with BIOS convenience accessors.
    """

    def bios(self):
        """
        Return the first SMBIOS Type 0 (BIOS Information) entry, if present,
        with convenience attributes populated.
        """
        for d in self.structures(type=DMI_BIOS):
            d.vendor = d.string_at(0x04)
            d.version = d.string_at(0x05)
            d.release_date = d.string_at(0x08)
            return d
        return None


class MemoryProperties:
    """
    Get system memory properties by decoding DMI table.
    Will generally require root privilege.
    """

    def __init__(self, dmi_definitions: ASCT_DMI):
        self.speed = None  # MT/s
        self.n_channels = None
        self.data_width = None
        self.type_str = None
        self.manufacturer = None
        self.part_number = None
        # note: this assumes all RAM modules are the same speed, we will take the speed of the last
        # stick iterated through for total bandwidth calculations. where the RAM is a mix/match of
        # different speeds this will be unreliable, although this is probably unlikely in infra
        # server configurations
        try:
            for d in dmi_definitions.memory():
                self.speed = d.c_speed_mts
                self.data_width = d.d_width
                self.type_str = d.mem_type_str
                self.manufacturer = d.mfr
                self.part_number = d.part
                # DDR5 (DMI mem_type >= 0x20) physically have 2 32-bit channels,
                # but in DMI reporting, they are reported as 64-bit.
                # So we treat it as 1x64 rather than 2x32.
                if self.n_channels is None:
                    self.n_channels = 0
                self.n_channels += 1
        except (AttributeError, TypeError, ValueError, OSError) as e:
            log.error(f"error decoding memory information from DMI: {e}")

    def total_bandwidth(self):
        if self.data_width is None:
            return None
        n_bytes = self.data_width // 8
        return n_bytes * self.n_channels * (self.speed * 1000000)


@dataclass
class BiosInfo:
    """
    Get system BIOS information by decoding DMI table.
    Will generally require root privilege.
    """

    vendor: str = None
    version: str = None
    release_date: str = None
    dmi_definitions: InitVar[ASCT_DMI | None] = None

    def __post_init__(self, dmi_definitions: ASCT_DMI | None):
        if dmi_definitions is None:
            return
        try:
            d = dmi_definitions.bios()
            if d is not None:
                self.vendor = d.vendor
                self.version = d.version
                self.release_date = d.release_date
        except (AttributeError, TypeError, ValueError, OSError) as e:
            log.error(f"error decoding BIOS information from DMI: {e}")


@dataclass
class memory:
    total_size: int = None
    n_channels: int = None
    type_str: str = None
    manufacturer: str = None
    part_number: str = None
    speed: int = None
    data_width: int = None
    peak_theoretical_bw: int = None
