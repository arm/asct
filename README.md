<!--
SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>

SPDX-License-Identifier: Apache-2.0
-->

<!-- PUBLISH_OMIT:start -->
![sdist](https://github.com/Arm-Debug/asct/actions/workflows/build-sdist.yml/badge.svg)
[![Maintainability](https://qlty.sh/badges/ccf91760-a2b0-49e8-ae27-4f99deca7064/maintainability.svg)](https://qlty.sh/gh/Arm-Debug/projects/asct)
[![Test Coverage](https://qlty.sh/badges/ccf91760-a2b0-49e8-ae27-4f99deca7064/test_coverage.svg)](https://qlty.sh/gh/Arm-Debug/projects/asct)
<!-- PUBLISH_OMIT:end -->

# Arm System Characterization Tool

The Arm System Characterization Tool (ASCT) is a standalone command-line utility for running low-level benchmarks, diagnostic scripts, and system tests to analyze and debug performance on Arm-based platforms.

ASCT provides a standardized environment for evaluating key hardware characteristics, such as memory latency and bandwidth, and is especially suited for platform bring-up, system tuning, and architectural comparison tasks. It helps developers and system architects gain early and repeatable insights into performance-critical subsystems.

Current capabilities include:

- System report. Generate a structured inventory of CPU, caches, NUMA topology, operating system, kernel, and tooling state. You can also generate Arm Coherent Mesh Network (CMN) and network topology and configuration reports on demand. For more information, see [System report](docs/system_report.md).

- Memory latency and bandwidth benchmarks. Measure how latency and bandwidth change across cache levels and DRAM. Characterize NUMA effects, including idle latency, loaded latency, core-to-core latency, and peak bandwidth. For more information, see [Memory characterization](docs/memory.md).

- Storage latency and bandwidth benchmarks. Run controlled fio-based parameter sweeps. Vary request size, queue depth, process count, and access pattern. Measure bandwidth, IOPS, latency, and CPU utilization under input and output load. For more information, see [Storage characterization](docs/storage.md).

- System diff. Compare one or more ASCT run output directories. Highlight configuration differences and benchmark differences. Generate CSV and JSON output and plots for supported benchmarks. For more information, see [Compare run results](docs/sysdiff.md).


Planned features include:

- Hardware register inspection and configuration for debug and bring-up use

- Locking and synchronization stress tests

- Floating-point compute performance measurement in FLOPS

## Documentation

For detailed guidance, see:

- [Installation](INSTALL.md)

- [Getting started](USAGE.md)

- [System report](docs/system_report.md)

- [Memory characterization](docs/memory.md)

- [Storage characterization](docs/storage.md)

- [Compare run results](docs/sysdiff.md)
<!-- PUBLISH_OMIT:start -->
- [Developer guide](DEVELOPMENT.md)
<!-- PUBLISH_OMIT:end -->
