#!/usr/bin/env sh
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

# What this script does
# - Creates an isolated Python virtual environment at: <install-dir>/asct_venv
# - Installs ASCT from the local source distribution tarball: asct-*.tar.gz (next to this script)
# - Ensures fio 3.36+ is available: uses system fio if it matches, otherwise downloads/builds fio and installs it into the venv
# - Exits if <install-dir>/asct_venv already exists (avoids overwriting an existing environment)
#
# Side effects
# - Writes only under <install-dir>; may download fio sources from GitHub during installation
# - Does not install or modify system Python packages

# Main commands executed (high level)
# - python3 -m venv <install-dir>/asct_venv
# - source <install-dir>/asct_venv/bin/activate
# - python -m pip install asct-*.tar.gz
# - fio --version (to check system fio)
# - If fio needs to be built into the venv:
#   - wget/curl <fio tarball URL>
#   - tar -xf <fio tarball>
#   - ./configure --prefix=<install-dir>/asct_venv
#   - make && make install

set -eu

usage() {
	echo "Usage: $0 [--install-dir <folder>]" >&2
	echo "" >&2
	echo "Installs ASCT into a Python virtual environment and (if needed) builds fio 3.36 into the same environment." >&2
	echo "" >&2
	echo "Options:" >&2
	echo "  --install-dir <folder>  Parent folder for the virtual environment (default: next to this script)" >&2
	echo "  -h, --help              Show this help" >&2
}

die() {
	echo "ERROR: $*" >&2
	exit 1
}

have() {
	command -v "$1" >/dev/null 2>&1
}

init_paths() {
	# Run relative to this script so it works from any CWD.
	SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
	cd "$SCRIPT_DIR"
	INSTALL_DIR="$SCRIPT_DIR"
}

parse_args() {
	while [ "$#" -gt 0 ]; do
		case "$1" in
			--install-dir)
				[ "$#" -ge 2 ] || { usage; exit 1; }
				INSTALL_DIR="$2"
				shift 2
				;;
			-h|--help)
				usage
				exit 0
				;;
			*)
				usage
				die "Unknown argument: $1"
				;;
		esac
	done
}

resolve_install_dir() {
	case "$INSTALL_DIR" in
		/*) : ;;
		*) INSTALL_DIR="${SCRIPT_DIR}/${INSTALL_DIR}" ;;
	esac

	mkdir -p "$INSTALL_DIR"
	VENV_DIR="${INSTALL_DIR}/asct_venv"
	[ ! -e "$VENV_DIR" ] || die "Virtual environment already exists: $VENV_DIR (remove it to reinstall, or choose another --install-dir)"
}

create_and_activate_venv() {
	have python3 || die "python3 not found"

	python3 -m venv "$VENV_DIR" || {
		echo "Hint: if you see 'No module named venv', install python3-venv (or your distro equivalent)." >&2
		exit 1
	}
	. "$VENV_DIR/bin/activate"
	VENV_PY="$VENV_DIR/bin/python"
}

ensure_pip_in_venv() {
	# Some distros create venvs without pip if ensurepip is not installed/enabled.
	if ! "$VENV_PY" -m pip --version >/dev/null 2>&1; then
		if "$VENV_PY" -m ensurepip --version >/dev/null 2>&1; then
			"$VENV_PY" -m ensurepip >/dev/null 2>&1 || true
		fi
	fi
	"$VENV_PY" -m pip --version >/dev/null 2>&1 || die "pip is not available in the virtual environment (install python3-pip / python3-ensurepip or distro equivalent)"
	PIP="$VENV_PY -m pip"
}

fio_is_required_version() {
	# fio typically prints e.g. "fio-3.36".
	out="$($1 --version 2>/dev/null || true)"
	ver=$(printf '%s\n' "$out" | sed -n 's/.*fio-\([0-9][0-9.]*\).*/\1/p' | head -n 1)
	[ -n "$ver" ] || return 1
	FIO_SYSTEM_VERSION="$ver"
	[ "$(printf '%s\n%s\n' "$FIO_VERSION" "$ver" | sort -V | head -n 1)" = "$FIO_VERSION" ]
}

install_fio_if_needed() {
	if have fio && fio_is_required_version fio; then
		echo "Using system fio ${FIO_SYSTEM_VERSION}."
		return 0
	fi

	# Build fio into the venv to keep the install self-contained.
	have make || die "make not found (required to build fio)"
	if ! have gcc && ! have clang; then
		die "gcc/clang not found (required to build fio)"
	fi
	have tar || die "tar not found (required to extract fio sources)"

	DOWNLOADER=""
	if have wget; then
		DOWNLOADER="wget"
	elif have curl; then
		DOWNLOADER="curl"
	else
		die "wget or curl not found (required to download fio)"
	fi

	rm -rf "$FIO_DIR" "$FIO_TARBALL"
	echo "Downloading fio ${FIO_VERSION}..."
	if [ "$DOWNLOADER" = "wget" ]; then
		wget "$FIO_URL" -O "$FIO_TARBALL"
	else
		curl -fsSL "$FIO_URL" -o "$FIO_TARBALL"
	fi

	tar -xf "$FIO_TARBALL"
	(
		cd "$FIO_DIR"
		./configure --prefix="$VENV_DIR"
		echo "Building fio ${FIO_VERSION}..."
		make
		echo "Installing fio ${FIO_VERSION}..."
		make install
	)

	rm -rf "$FIO_TARBALL" "$FIO_DIR"
}

install_asct_sdist() {
	set -- asct-*.tar.gz
	[ "$1" != "asct-*.tar.gz" ] || die "No asct-*.tar.gz found in $SCRIPT_DIR"
	[ "$#" -eq 1 ] || die "Expected exactly one asct-*.tar.gz in $SCRIPT_DIR, found $#"

	ASCT_TARBALL="$1"
	echo "Installing ASCT from: $ASCT_TARBALL"
	$PIP install "$ASCT_TARBALL"
}

print_next_steps() {
	echo ""
	echo "Installed ASCT into: $VENV_DIR"
	echo "To use it in your current shell:"
	echo "  source $VENV_DIR/bin/activate"
	echo "Then run:"
	echo "  asct --help"
}

FIO_VERSION="3.36"
FIO_TARBALL="fio-${FIO_VERSION}.tar.gz"
FIO_URL="https://github.com/axboe/fio/archive/refs/tags/${FIO_TARBALL}"
FIO_DIR="fio-fio-${FIO_VERSION}"

init_paths
parse_args "$@"
resolve_install_dir
create_and_activate_venv
ensure_pip_in_venv
install_fio_if_needed
install_asct_sdist
print_next_steps