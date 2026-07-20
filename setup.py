#!/usr/bin/env python3
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

import os
import shutil
import sys
import json
import subprocess
from pathlib import Path
from setuptools import setup
from setuptools.command.build import build
from setuptools.command.sdist import sdist

VERSION_TAG_ENV_VAR = "ASCT_VERSION_TAG"
BUILD_TAG_ENV_VAR = "ASCT_BUILD_TAG"
VERSION_INFO_FILE = ".version_info"
SOURCE_TREE_VERSION_FILE = "VERSION"

# Maps a package name to a filepath
packages = {
    "asct": "src",
    "asct.core": "src/core",
    "asct.core.config": "src/core/config",
    "asct.core.config.sysreg": "src/core/config/sysreg",
    "asct.core.resources": "src/core/resources",
    "asct.core.managers": "src/core/managers",
    "asct.core.benchspec": "src/core/benchspec",
    "asct.core.recipes": "src/core/recipes",
    "asct.core.recipes.configuration": "src/core/recipes/configuration",
    "asct.core.recipes.impl": "src/core/recipes/impl",
    "asct.core.cmd": "src/core/cmd",
    "asct.core.cmd.helpers": "src/core/cmd/helpers",
    "asct.core.cmn": "src/lib/cmn-tools",
    "asct.core.sysdiff": "src/lib/sysdiff",
    "asct.core.term_ui": "src/lib/term_ui",
    "asct.core.utility": "src/lib/utility",
    "asct.lib.output_metadata": "src/lib/output_metadata",
    "asct.lib.ip_registers": "src/lib/ip_registers",
    "asct.lib.networking": "src/lib/networking",
    "asct.sysreport": "src/lib/sysreport",
    "asct.lib.dietperf": "extern/dietperf",
    "asct.lib.c2c_latency": "src/lib/c2c_latency",
    "asct.lib.run": "src/lib/run",
    "cmntools": "extern/cmn-tools/src",
}

# Maps a package name to a list of non-.py files to pack
package_data = {
    "asct": ["asct"],
    "asct.core.config": ["ubench.json", "sysreg"],
    "asct.core.config.sysreg": ["N1.json", "N2.json", "V2.json", "arm_registers.json"],
    "asct.lib.output_metadata": ["fields.json"],
    "asct.lib.dietperf": ["dietperf.h"],
}

# Executables copied to /bin and accessible via $PATH
scripts = ["src/asct"]


# Returns all files from target_dir that end with the given extension
def get_files_with_extension(target_dir, file_ext, prepend_dir, recursive=False):
    files = []

    if os.path.exists(target_dir):
        if not recursive:
            file_list = [(target_dir, [], os.listdir(target_dir))]
        else:
            file_list = os.walk(target_dir)

        for root, _, filenames in file_list:
            for f in filenames:
                if f.endswith(file_ext):
                    path = os.path.join(root, f)
                    files.append(path if prepend_dir else os.path.relpath(path, target_dir))
    return files


# Updates the packages and package_data dicts with info about the cmntools library
def add_cmn_data(packages, package_data):
    data_dir = [("regdefs", "regdefs"), ("events", "csv"), ("schemas", "json")]
    for folder, ext in data_dir:
        lib_dir = str(Path("extern/cmn-tools/data") / folder)
        name = f"data/{folder}"
        packages[name] = lib_dir
        package_data[name] = get_files_with_extension(lib_dir, ext, False, recursive=True)


# Loads the micro benchmark config file
def get_ubench_config(prefix=None):
    base_path = "core/config/ubench.json"
    path = os.path.join(prefix, base_path) if prefix else base_path
    with open(path, "r") as f:
        return json.load(f)


# Updates the packages and package_data dicts with info about a support library (on which
# a benchmark binary depends)
def add_support_lib(packages, package_data, lib_name):
    package_name = f"asct.helper_lib.{lib_name}"
    lib_dir = os.path.join("src/helper_lib", lib_name)
    packages[package_name] = lib_dir
    package_data[package_name] = get_files_with_extension(lib_dir, "", False)


# Updates the packages, package_data dicts as well as the scripts array with info from the microbench config
def add_ubench_data(packages, package_data):
    ubench_config = get_ubench_config("src")
    support_libraries = set()
    for name, info in ubench_config["benchmarks"].items():
        bench_directory = info["folder"]
        package_name = f"asct.{name}"
        packages[package_name] = bench_directory
        package_data[package_name] = get_files_with_extension(bench_directory, "", False, True)
        for bin_variant, bin_info in info.items():
            if bin_variant == "folder" or "depends_on" not in bin_info:
                continue
            support_libraries.update(bin_info["depends_on"])
    for library in support_libraries:
        add_support_lib(packages, package_data, library)


class ASCTSetupFatalError(Exception):
    def __init__(self, step, message, cmd=None, stdout=None, stderr=None):
        super().__init__(message)
        self.step = step
        self.message = message
        self.cmd = cmd
        self.stdout = stdout
        self.stderr = stderr

    def __str__(self):
        msg = f"Fatal setup error during step [{self.step}]: {self.message}"
        if self.cmd:
            msg += f"\nAttempted command: '{self.cmd}'"
            msg += f"\n - stdout -\n{self.stdout}"
            msg += f"\n - stderr -\n{self.stderr}"
        return msg


class ASCTVersionInfo:
    def __init__(self):
        self.git_sha = None
        self.extra_version_tag = None
        self.extra_build_tag = None
        self.version = None

    def _get_git_commit_sha(self):
        cmd_line = ["git", "rev-parse", "--short", "HEAD"]
        try:
            result = subprocess.run(cmd_line, capture_output=True, check=True, text=True)
        except subprocess.CalledProcessError as exc:
            raise ASCTSetupFatalError(
                "getting git sha", "Failed to run a git command", " ".join(cmd_line), exc.stdout, exc.stderr
            ) from exc
        self.git_sha = result.stdout.strip()

    def _get_source_tree_version(self):
        try:
            with open(SOURCE_TREE_VERSION_FILE, "rt") as f:
                self.version = f.readlines()[0].strip()
        except Exception as exc:
            raise ASCTSetupFatalError("getting version", f"Unable to read version file: {exc}") from exc

    def _get_extra_tags(self):
        self.extra_version_tag = os.getenv(VERSION_TAG_ENV_VAR, "")
        self.extra_build_tag = os.getenv(BUILD_TAG_ENV_VAR, "")

    def load_from_source_tree(self):
        self._get_git_commit_sha()
        self._get_source_tree_version()
        self._get_extra_tags()

    def save_to_file(self, file_path):
        try:
            with open(file_path, "wt") as f:
                json.dump(
                    {
                        "git_sha": self.git_sha,
                        "extra_version_tag": self.extra_version_tag,
                        "extra_build_tag": self.extra_build_tag,
                        "version": self.version,
                    },
                    f,
                )
        except Exception as exc:
            raise ASCTSetupFatalError(
                "writing version info", f"Unable to write version info file {file_path}: {exc}"
            ) from exc

    def load_from_file(self, file_path):
        try:
            with open(file_path, "rt") as f:
                data = json.load(f)
            self.git_sha = data["git_sha"]
            self.extra_version_tag = data["extra_version_tag"]
            self.extra_build_tag = data["extra_build_tag"]
            self.version = data["version"]
        except Exception as exc:
            raise ASCTSetupFatalError(
                "reading version info", f"Unable to read version info file {file_path}: {exc}"
            ) from exc

    def auto_load_settings(self):
        if os.path.isfile(VERSION_INFO_FILE):
            self.load_from_file(VERSION_INFO_FILE)
        else:
            self.load_from_source_tree()

    def __str__(self):
        version = f"{self.version}"
        if self.extra_version_tag:
            version += f".{self.extra_version_tag}"
        build_info = []
        if self.extra_build_tag:
            build_info.append(self.extra_build_tag)
        if self.git_sha:
            build_info.append(self.git_sha)
        if build_info:
            version += f"+{'.'.join(build_info)}"
        return version


# Custom sdist: inject the GIT commit hash in the GIT_HASH file
class ASCTSourceDist(sdist):
    def run(self):
        super().run()

    def make_release_tree(self, base_dir, files):
        super().make_release_tree(base_dir, files)

        version_info = ASCTVersionInfo()
        version_info.load_from_source_tree()
        version_info_filepath = os.path.join(base_dir, VERSION_INFO_FILE)

        version_info.save_to_file(version_info_filepath)

        if VERSION_INFO_FILE not in files:
            files.append(VERSION_INFO_FILE)


def get_version():
    version_info = ASCTVersionInfo()
    version_info.auto_load_settings()
    return f"{version_info}"


# Custom builder: after the default build step, it builds the support libs and the micro benchmarks
# which use the support libs and copies them to the 'scripts' directory which is where all executables
# are placed before being copied to /bin which is part of PATH env variable when a virtual env is activated
class ASCTBuilder(build):
    def run(self):
        build.run(self)
        self.ubench_config = get_ubench_config(os.path.join(self.build_lib, "asct"))
        self.build_micro_benchmarks()

    def replace_bash_vars(self, string, var_dict):
        for key, value in var_dict.items():
            string = string.replace(f"${{{key}}}", value)
        return string

    def build_micro_benchmarks(self):
        for name, info in self.ubench_config["benchmarks"].items():
            ubench_dir = os.path.join(self.build_lib, "asct", name)
            for binary_info in info.values():
                if "binary" not in binary_info:
                    continue

                bash_vars = {
                    "DIETPERF_DIR": os.path.relpath(
                        os.path.join(self.build_lib, "asct", "lib", "dietperf"), start=ubench_dir
                    )
                }
                executable_name = binary_info["binary"]
                extra_make_flags = [f"EXE={executable_name}"]
                for flags_name in ["cflags", "ldflags"]:
                    flags = (
                        self.replace_bash_vars(binary_info[flags_name], bash_vars)
                        if flags_name in binary_info
                        else None
                    )
                    if flags:
                        extra_make_flags += [f"{flags_name.upper()}={flags}"]

                self.make_c_project(ubench_dir, ["clean", *extra_make_flags])
                self.make_c_project(ubench_dir, extra_make_flags)

                source_path = os.path.join(ubench_dir, executable_name)
                target_path = os.path.join(self.build_scripts, executable_name)
                shutil.copy(source_path, target_path)

            # after the binary gets copied, remove the source code for the ubenchmark
            # all the supporting libraries' source code used in this build step
            # will be removed by remove_support_lib_sourcecode
            shutil.rmtree(ubench_dir, ignore_errors=True)

    def make_c_project(self, directory, extra_make_args):
        try:
            subprocess.check_output(
                ["/usr/bin/make", *extra_make_args], cwd=directory, text=True, stderr=subprocess.STDOUT
            )
        except subprocess.CalledProcessError as e:
            print(f"Failure building C project in {directory}:\n{e.output}", file=sys.stderr)
            raise


add_ubench_data(packages, package_data)

add_cmn_data(packages, package_data)

setup(
    packages=packages.keys(),
    version=get_version(),
    package_dir=packages,
    package_data=package_data,
    include_package_data=True,
    scripts=scripts,
    cmdclass={"build": ASCTBuilder, "sdist": ASCTSourceDist},
)
