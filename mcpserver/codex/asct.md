---
# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

description: Run ASCT to characterize a system
---

Your goal is to help a user to understand the system characteristics and, in the process, discover performance anomalies so the user can take action to fix them.  Use the MCP server tools to help with this. There are two major characterizations: memory and storage. 

Primary workflow:
1. Confirm ASCT folder exists
2. Prepare ASCT execution environment.
3. Collect system information.
4. Run memory benchmarks.  You can get the list of benchmarks by running `asct help`, then look for features with `memory` as one of the keywords.
5. Run storage benchmarks. You can get the list of benchmarks by running `asct help`, then look for features with `storage` as one of the keywords.
6. Show PNG artifacts in chat.
7. Summarize results and artifacts.

Steps to follow:
* First, determine the ASCT root directory: use the user-provided path if already given; otherwise ask for the absolute ASCT installation path.
* Then, as root, go to the ASCT folder and activate the Python virtual environment; if it is missing, follow the installation instructions included with the current ASCT package before continuing (for example, `README.txt` in release bundles, or `README.md` in source checkouts).
* Get system information as root
* Run memory features as root
* Run storage features as root

Tool usage guidance:
- Ensure dependencies are satisfied: `numactl`. For storage benchmarks, `fio` 3.36 or later is required. Python must be 3.10 or later.
- Prefer exact commands from ASCT help by running `asct help`
- Capture stderr for failures and continue with best-effort diagnostics.
- By default, ASCT creates an output directory named: `data.<YYYYMMDD_HHMMSS_microseconds>`.
- Run tool with root privileges, Prefer `sudo -s` so the working folder stays the same, then activate the Python environment as root to get root access.
- Don't run ASCT with extra `--verbose` or `--output-dir` flags.  Let ASCT create new output folder, then detect and use the newly created `data.*` directory for artifacts and analysis.

- As you run ASCT, do not use `--no-progress-bar` to suppress output.  Keep the console output visible in chat so users can see progress. Do not hide or collapse it so users can monitor progress in real time.
- After each benchmark run, find generated `*.png` files in the latest `data.*` directory and display each PNG in chat (do not only list file paths).
- If a PNG fails to render, report the file path and the rendering error, then continue displaying the remaining PNG files.

Arm-specific guidance:
- Use `arm-mcp/knowledge_base_search` for Arm microarchitecture insights.  This can be used when giving summary of the results interpretation.

Insight guidance:
- Enrich the following insights with Arm-specific guidance when possible.
- For memory, pay attention to single-core performance and multi-core performance. For L1 measurement, compare against Arm published architectural numbers as validation.
  - Pay attention to the shape of latency-sweep graph to see whether the memory-level latency is good.
  - DRAM latency in latency sweep should be close to same-NUMA-node latency in idle-latency runs
  - For the bandwidth sweep, relate the transition data size to the latency sweep; they should be similar.
  - Cross-NUMA same node bandwidth could be compared against ALL Reads bandwidth in peak-bandwidth measurement with a scale factor of number of NUMA nodes which can be found in the system report.
  - For loaded latency, the latency number at highest injected NOPs can be compared against the DRAM latency in latency sweep.  They should be similar.
  - For peak bandwidth: if % Peak Theoretical is available, it should be higher than 60%; if it is unavailable (for example, in some virtualized environments), report it as N/A and do not apply the 60% check.

- For storage, 
  - Pay attention to saturation pattern, also can compare the read rate against the memory read rate from memory benchmarking.  
  - If they are too close to memory rate, it is likely the measurement is wrong as all the runs should have `direct=1` in `fio` settings.


Pitfalls to avoid:
- Ensure the asct is the one you installed by validating `which asct` after venv activation.
- Do not skip environment activation before running ASCT.
- Do not claim full system-info coverage when command was run without root.
- Do not omit output directory path.
- Do not interrupt ASCT run - they can take 30 minutes to run memory and storage benchmark sets.
- When looking for output folder, do not just look for `data.*` as it will contain previous runs.  Try to track newly created folder every time you run ASCT. You can also verify by comparing the folder name against the time you run ASCT as timestamp is encoded in folder name.


Output format:
Status: success | partial | failed
Environment: <venv activated / created + installed / failed>
Commands run:
- <command 1>
- <command 2>
Results:
- <benchmark>: <ok/partial/fail + short note + png generated>
Artifacts:
- output_dir: <absolute path>
- key files: <comma-separated existing files>
Plots shown in chat:
- <embedded png 1>
- <embedded png 2>
Insights:
- <overall insights>
- <memory specific insights>
- <storage specific insights>
