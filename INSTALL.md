<!--
SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>

SPDX-License-Identifier: Apache-2.0
-->

## Requirements

- ASCT is supported on Linux systems
- Python 3.10 or later. You need `pip` if you want to use a Python virtual environment (options 1 and 2).
- Build tools such as:
  - `gcc`
  - `make`
- If you want to install ASCT as a system-wide tool (option 3), you need: 
  - `uv`. Install `uv` from: [https://docs.astral.sh/uv/getting-started/installation/](https://docs.astral.sh/uv/getting-started/installation/).
  - `sudo` privileges
  - Permission to create:
    - `/opt/uv/tools`
    - `/usr/local/bin`

## Download ASCT

1. Download the latest ASCT release bundle from: [artifacts.tools.arm.com](https://artifacts.tools.arm.com/asct/dist/).

   For users within the Arm network, early-access versions might be available at: [artifacts.internal.tools.arm.com](https://artifacts.internal.tools.arm.com/asct/dist/).

1. Locate the downloaded file on your host machine. Move it to the target machine where you want to install and run the tool.

1. Extract the release bundle:

    ```
    tar -xvzf asct-<version>-release.tar.gz
    ```

    This process creates a directory:

    ```
    asct-<version>/
    ```

    The directory contains the following files:

    - `asct-<version>.tar.gz`: The Python source distribution (the package to install)
    - `asct_docs/`: Generated HTML documentation. Open `asct_docs/index.html` in a web browser.
    - `install.sh`: An optional installer helper (tested on Ubuntu 24.04)
    - `README.txt`: A release bundle summary and quick-start notes

## Install ASCT

You can install ASCT in one of the following ways:

- [Option 1 (recommended)](#option-1-install-asct-with-the-helper-script): Install into a Python virtual environment using the `install.sh` helper script.

- [Option 2](#option-2-install-asct-manually-using-pip): Install manually using `pip` into a Python environment.

- [Option 3](#option-3-install-asct-as-a-system-wide-tool-with-uv): Install system-wide using `uv` (for shared machines or CI systems).


### Option 1: Install ASCT with the helper script

This is the simplest installation method. It creates a dedicated Python virtual environment and installs ASCT into it.

#### Steps

From inside the extracted `asct-<version>/` directory: 

```
    ./install.sh --install-dir /path/to/install/directory
```

If `--install-dir` is not specified, the script installs into the directory containing `install.sh`.

The `install.sh` script performs the following tasks:

- Creates a Python virtual environment
- Installs ASCT into that environment using `pip`
- Optionally builds `fio` if required

By default, the virtual environment is created at `<install-dir>/asct_venv`.

After installation, follow the instructions printed by the script to activate the virtual environment before running ASCT.

### Option 2: Install ASCT manually using pip

Use this method in the following cases:

- You prefer to manage Python environments manually

- You are installing into an existing virtual environment

- You automate installation in your own scripts

You can install ASCT into any active Python environment.

#### Install into a new virtual environment

1. Create a virtual environment:

    ```
    python3 -m venv asct_venv
    ```

1. Activate it:

    ```
    source asct_venv/bin/activate
    ```

1. Install ASCT from the bundled source distribution:

    ```
    python3 -m pip install ./asct-<version>.tar.gz
    ```
    
    ASCT is now installed inside the virtual environment.

#### Install into an existing environment

```
python3 -m pip install ./asct-<version>.tar.gz
```

ASCT is installed into the currently active Python environment.

### Option 3: Install ASCT as a system-wide tool with uv

This method installs ASCT as a system-wide tool available on the system `PATH`.

Use this option only for shared systems, managed environments, or CI environments.

#### Steps

1. Create the required directories:

    ```
    sudo mkdir -p /opt/uv/tools /usr/local/bin
    ```

1. Install ASCT with `uv` and place the executable in `/usr/local/bin`:

    ```
    sudo UV_TOOL_DIR=/opt/uv/tools UV_TOOL_BIN_DIR=/usr/local/bin uv tool install ./asct-<version>.tar.gz
    ```

    After installation, ASCT is available on the system `PATH`.

## Runtime tools

Some workloads require additional system tools, such as:

- `numactl`
- `fio` 3.36 or later

If tools are missing, ASCT reports this at runtime.

## Run ASCT

- If you installed ASCT in a virtual environment, activate the environment first.
- If you installed ASCT with `uv`, no activation is required.

To verify the installation, run:

```
asct help
```

You can also open the offline documentation at: `asct_docs/index.html`.

## Uninstall ASCT

Uninstall ASCT as follows.

### Option 1: If you installed ASCT using the helper script

To uninstall ASCT, remove that virtual environment directory:

```
rm -rf <install-dir>/asct_venv
```

### Option 2: If you manually installed ASCT using pip

If you installed ASCT into a dedicated virtual environment, you can remove that environment directory.

Alternatively, activate the relevant Python environment and uninstall ASCT:

```
python3 -m pip uninstall asct
```

### Option 3: If you installed ASCT system-wide using uv

Remove ASCT using `uv`:

```
sudo UV_TOOL_DIR=/opt/uv/tools UV_TOOL_BIN_DIR=/usr/local/bin uv tool uninstall asct
```
