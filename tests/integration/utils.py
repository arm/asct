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
import csv
import json
import logging
import os
import subprocess

log = logging.getLogger(__name__)


class ASCTExecInfo:
    def __init__(self):
        # Complete command as a string
        self.cmd = ""
        # Maps a file name to file content as string
        self.raw_file_content = {}
        # Maps a file name to its content as a parsed JSON (dict)
        self.json_file_content = {}
        # Maps a file name to its conntent as a parsed CSV (list of lists)
        self.csv_file_content = {}
        # Maps a PNG file name to its first 8 bytes (for partial header validation)
        self.png_file_content = {}
        # stdout as a string
        self.stdout = None
        # stderr as a string
        self.stderr = None
        # Return code for the command
        self.ret_code = None
        # True if the command timed out
        self.timed_out = False


def get_file_ext(filename):
    return os.path.splitext(filename)[1]


def read_file_json(filepath):
    json_raw_content = None
    json_data = None
    try:
        with open(filepath, "rt") as json_file:
            json_raw_content = json_file.read()
            json_data = json.loads(json_raw_content)
    except (OSError, json.JSONDecodeError) as e:
        if json_raw_content:
            log.error("Unable to parse JSON file %s: %s\n--- content ---\n%s", filepath, e, json_raw_content)
        else:
            log.error("Unable to read JSON file %s: %s", filepath, e)
    assert json_data is not None, f"Unable to read JSON content from {filepath}"
    return json_raw_content, json_data


def read_file_csv(filepath):
    csv_raw_content = None
    csv_data = None
    try:
        with open(filepath, "rt") as csv_file:
            csv_raw_content = csv_file.read()
            csv_file.seek(0)
            reader = csv.reader(csv_file)
            csv_data = [row for row in reader]
    except (OSError, csv.Error) as e:
        if csv_raw_content:
            log.error("Unable to parse CSV file %s: %s\n--- content ---\n%s", filepath, e, csv_raw_content)
        else:
            log.error("Unable to read JSON file %s: %s", filepath, e)
    assert csv_data is not None, f"Unable to read CSV content from {filepath}"
    return csv_raw_content, csv_data


def read_version_file(filepath):
    """Reads a TOML file and returns the version string."""
    version = None
    with open(filepath, "rt") as f:
        version = f.read().strip()
    assert version, f"Failed to read version from file {filepath}"
    return version


def run_cmd(cmd, timeout=None, extra_env=None, use_shell=False):
    """Runs a given command provided as an array of cmd + parameters or as a string
        (depending on the 'shell' parameter, if False: array, if True: string)

    Parameters
    ----------
    cmd : str
        Array containing the command and each arg

    timeout : float or None
        Timeout for the command, if None - no timeout

    extra_env : dict or None
        Added environment variables for the command (in addition to os.environ)

    Returns
    -------
    stdout : str
        stdout content resulted from running the command

    stderr : str
        stderr content resulted from running the command

    retcode : int or None
        Return code from running the command, None if timed out

    timed_out: bool
        True if the command timed out
    """
    result = None

    environ = os.environ.copy() if extra_env else os.environ
    if extra_env:
        for key, val in extra_env.items():
            environ[key] = val

    try:
        result = subprocess.run(
            cmd, capture_output=True, check=False, timeout=timeout, text=True, env=environ, shell=use_shell
        )
    except subprocess.TimeoutExpired as t:
        return t.stdout.decode("utf-8"), t.stderr.decode("utf-8"), None, True
    return result.stdout, result.stderr, result.returncode, False


def run_asct(
    cmd,
    args=None,
    output_dir=None,
    extra_env=None,
    timeout=None,
    assert_on_failure=True,
    enable_progress_bar=False,
    print_output=True,
):
    """Runs the ASCT tool and returns the stdout, stderr, return code, and
        the content of all the files in the output directory in both raw format (text)
        and decoded format (dict for JSON, array of arrays for CSV)

    Parameters
    ----------
    cmd : str
        Array containing the command and each arg

    output_dir: str
        Path to the existing output directory

    timeout : float or None
        Timeout for the command, if None - no timeout

    extra_env : dict or None
        Added environment variables for the command (in addition to os.environ)

    assert_on_failure : bool
        Assert if the tool doesn't finish executing sucessfully

    Returns
    -------
    result: ASCTExecInfo
        Object containing stdout, stderr, return code, content of output files
    """

    command = ["asct", cmd]

    command += [] if not args else args
    if output_dir is not None:
        command += ["--output-dir", output_dir]
    if cmd == "run":
        command += [] if enable_progress_bar else ["--no-progress-bar"]

    result = ASCTExecInfo()
    result.cmd = " ".join(command)
    result.stdout, result.stderr, result.ret_code, result.timed_out = run_cmd(command, timeout, extra_env)

    if assert_on_failure:
        assert result.timed_out is False, f"ASCT timeout\n> stdout <\n{result.stdout}\n> stderr <\n{result.stderr}"
        assert result.ret_code == 0, (
            f"Failed to run ASCT (err: {result.ret_code})\n> "
            f"command: {result.cmd}\n> stdout <\n{result.stdout}\n> stderr <\n{result.stderr}"
        )

    if output_dir is None or result.ret_code != 0:
        return result

    assert os.path.exists(output_dir), (
        f"Output directory not created for: {result.cmd}\n> stdout <\n{result.stdout}\n> stderr <\n{result.stderr}"
    )

    for root, dirs, files in os.walk(output_dir):
        dirs.sort()
        files.sort()
        for filename in files:
            file_ext = get_file_ext(filename).lower()
            filepath = os.path.join(root, filename)

            if file_ext == ".json":
                result.raw_file_content[filename], result.json_file_content[filename] = read_file_json(filepath)
            elif file_ext == ".csv":
                result.raw_file_content[filename], result.csv_file_content[filename] = read_file_csv(filepath)
            elif file_ext == ".png":
                with open(filepath, "rb") as f:
                    result.png_file_content[filename] = f.read(8)
            else:
                log.warning("Skipping unrecognized output file %s", filename)
                continue

    # This will only get printed if a test fails (due to how pytest captures stdout by default)
    if print_output:
        print(f"Command execution report for: {result.cmd}")
        print(f"stdout:\n{result.stdout}")
        print(f"stderr:\n{result.stderr}")
        if result.raw_file_content:
            for item, content in result.raw_file_content.items():
                print(f"File content for '{item}':")
                print(f"{content}")
                print("-" * 25)
        else:
            print("No output file found")
    return result


def get_system_total_mem_bytes():
    stdout, stderr, errcode, _ = run_cmd("free -b | awk '/^Mem:/{print $2}'", use_shell=True)
    assert errcode == 0, f"Unable to get system memory:\n{stdout}\n{stderr}"
    return int(stdout)


def get_system_cpu_count():
    stdout, stderr, errcode, _ = run_cmd("nproc")
    assert errcode == 0, f"Unable to get number of CPUs:\n{stdout}\n{stderr}"
    return int(stdout)


def get_git_hash():
    stdout, stderr, errcode, _ = run_cmd(["git", "rev-parse", "--short", "HEAD"])
    assert errcode == 0, f"Failed to run get GIT hash (err: {errcode})\n> > stdout <\n{stdout}\n> stderr <\n{stderr}"
    return stdout.strip()


def get_asct_version_from_src():
    version = read_version_file("VERSION")
    # python versioning will add a '0' after .post versions if none is in the VERSION file, so we should do the same.
    if version.endswith("post"):
        version += "0"
    git_hash = get_git_hash()
    return f"{version}+{git_hash}"
