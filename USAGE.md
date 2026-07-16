<!--
SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>

SPDX-License-Identifier: Apache-2.0
-->

# Getting started

You can run ASCT with several commands that follow this pattern:

```
asct [command] [arguments]
```

|Command|Description| More information|
|-------|-----------|-----------------|
|`asct report cmn`|Collects information about the Arm Coherent Mesh Network (CMN) interconnect when it is present on your system| See [System report](docs/system_report.md)|
|`asct diff`|Compares results from previous ASCT runs| See [Compare run results](docs/sysdiff.md)|
|`asct list`|Lists available benchmarks| See [asct list command](#asct-list-command)|
|`asct run`|Runs a list of benchmarks based on a provided list of keywords| See [asct run command](#asct-run-command)|
|`asct report system-info`|Displays system information and exits. ASCT also includes this information by default with every benchmark run.|See [System report](docs/system_report.md)|
|`asct config`|Writes or verifies benchmark user configuration files|See [asct config command](#asct-config-command)|

For more information on a specific command, run:

```
asct [command] --help
```

To display the ASCT version, run:

```
asct version
```

To get started, run the default set of benchmarks:

```
sudo asct run
```

> [!IMPORTANT]
> Some benchmarks require `sudo` or root privileges to configure huge pages and access certain system information.
> You can run ASCT without `sudo`, but some benchmarks might be unavailable or have limited functionality.

### `asct run` command

The `asct run` command runs one or more benchmarks.

#### Default behavior

```
sudo asct run
```

Running the `asct run` command with no arguments executes a default set of benchmarks and displays the results in the terminal.

The default set does not include storage benchmarks. To run storage benchmarking, select storage benchmarks explicitly, for example with the `storage` keyword or specific storage sweep names.

Each time you run `asct run`, ASCT collects system information and includes it with the benchmark results. ASCT also saves detailed output in a directory under the current working directory.

The output can include data in multiple formats, such as CSV and JSON. Some benchmarks also generate additional artifacts, such as plots or raw data dumps.

By default, ASCT creates an output directory named: `data.<YYYYMMDD_HHMMSS_microseconds>`.

You can change the output location using the `--output-dir` flag.

#### Select benchmarks

To run all available benchmarks:

```
sudo asct run all
```

To run specific benchmarks, pass a list of benchmark names as arguments to the `asct run` command.

For example, to run the `latency-sweep` and `idle-latency` benchmarks:

```
sudo asct run latency-sweep idle-latency
```

Alternatively, each benchmark also has associated keywords that you can use to select multiple benchmarks that match those keywords.

For example, to run all benchmarks tagged with the `memory` keyword:

```
sudo asct run memory
```

To run all benchmarks tagged with the `storage` keyword:

```
sudo asct run storage
```

You can exclude benchmarks by prefixing the name or keyword with a caret (`^`).

For example, to run all benchmarks but exclude all of those tagged with the `bandwidth` keyword:

```
sudo asct run all ^bandwidth
```

> [!NOTE]
> If a benchmark is a dependency for running another benchmark, excluding it has no effect.
> For example, if you use `^latency-sweep` to exclude the `latency-sweep` benchmark, but another benchmark depends on `latency-sweep`, the `latency-sweep` benchmark still runs.

To view the list of available benchmarks and their keywords, run the following command:

```
asct list
```

#### Output options

The `run` command also supports the following arguments:

- `--format`, `-f` `[stdout, csv, json]`
    - Specify the output format, either to the terminal with `stdout` (default), individual CSV files (`benchmark-name.csv`), or a single combined JSON file (`report.json`)

        For example:
        ```
        asct run idle-latency --format=json
        ```

- `--log-level`, `-L` `[debug,info,warning,error,critical]`
    - Set the verbosity level (`info` by default).

- `--log-file` `LOG_FILE`
    - Specify the output file for logs, based on the `--log-level` setting. ASCT writes logs to this file and also prints them to standard error `stderr`.
    - If no log messages are generated, ASCT does not create the log file.

- `--output-dir`, `-o` `OUTPUT_DIR`
    - Set the directory for output files. By default, ASCT saves output files in a directory named `data.<YYYYMMDD_HHMMSS_microseconds>` in the current working directory. Use this flag to specify a different directory. You can specify an absolute or a relative path.

- `--force`
    - When the output directory specified by `--output-dir` already exists, ASCT displays an error and quits to avoid overwriting data. Use the `--force` flag to overwrite the output directory if it exists.

- `--quiet`, `-q`
    - Disable all output to `stdout` and `stderr`, including critical errors and log messages. Use `--log-file` to capture and view logs.

- `--no-progress-bar`
    - Disable the animated progress bar. Single-line update messages display instead.

### `asct list` command

Run the following command to get the list of available benchmarks and their associated keywords:

```
asct list
```

### `asct config` command

The `asct config` command writes or verifies benchmark user configuration files.

#### Save a configuration file

Use `asct config save` to generate a JSON configuration file from ASCT defaults.

```
asct config save --config-file my-config.json
```

If no file is specified, ASCT writes to `config.json` in the current directory.

You can limit output to selected benchmarks or report types by passing filters.

```
asct config save latency --config-file latency.json
```

You can override selected values while generating the file.

```
asct config save latency --config-file latency.json --update-config loaded-latency.duration=15
```

If the output file already exists, use `--force` to overwrite it.

```
asct config save --config-file my-config.json --force
```

#### Check a configuration file

Use `asct config check` to validate a user configuration file.

```
asct config check --config-file my-config.json
```

If no file is specified, ASCT checks `config.json`.

#### Save command options

- `filter`

  Optional list of benchmark or report filters to include in the generated file.

- `--config-file`

  Output path for `save` and input path for `check` (default: `config.json`).

- `--update-config`

  One or more setting overrides in `key=value` format.

- `--force`

  Overwrite an existing output file when using `save`.