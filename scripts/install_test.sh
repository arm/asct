#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

set -e

PY_COMMAND="/usr/bin/env python3"
PIP_COMMAND="$PY_COMMAND -m pip"
TEST_VENV="$(mktemp -d)"

FILE_PATH=$1

$PY_COMMAND -m venv $TEST_VENV

echo "Testing ASCT package $FILE_PATH installation"

source $TEST_VENV/bin/activate

echo "- Installation"
$PIP_COMMAND install $FILE_PATH

echo "- Basic check"
asct version
asct help
asct system-info

echo "Done"
deactivate

rm -rf $TEST_VENV
