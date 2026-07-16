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

import asct.core.logger as log

from asct.core.cmd.helpers.run_helpers import output_diff
from asct.core.sysdiff.manager import RecipeRunLoader, RecipesDiffManager


def validate_args(args):
    """Validate the arguments provided to the diff command.
    Returns:
        bool: True if arguments are valid, False otherwise.
    """
    comparison_runs = [x.rstrip("/") for x in args.run_dirs]

    # Validate --baseline argument and number of run directories
    # When --baseline is provided, at least one run directory is required
    # When --baseline is not provided, at least two run directories are required
    if args.baseline:
        if len(comparison_runs) < 1:
            log.error("When --baseline is provided, supply at least one run directory to compare.")
            return False
        comparison_runs = [args.baseline.rstrip("/"), *comparison_runs]

    if len(set(comparison_runs)) < 2:
        log.error("Provide at least two unique run directories (or add --baseline to allow a single run directory).")
        return False

    # Validate --sort-by argument
    # When provided, it must be different from the baseline and must be one of the comparison runs
    if args.sort_by:
        sort_by = args.sort_by.rstrip("/")
        if sort_by == comparison_runs[0]:  # baseline is the first in comparison_runs
            log.error(f"--sort-by must be different from baseline {comparison_runs[0]}.")
            return False

        if sort_by not in comparison_runs:
            log.error("--sort-by must be one of the comparison run directories: %s", ", ".join(comparison_runs))
            return False

    return True


def run(args):
    """Run the diff command with the provided arguments."""

    if not validate_args(args):
        return

    # Set results directories for comparison
    compare_dirs = args.run_dirs

    # get the reference run if specified, otherwise use the first compare dir as reference
    reference = args.baseline.rstrip("/") if args.baseline else None

    # get the last part of the path for sorting
    sort_by = args.sort_by.rstrip("/") if args.sort_by else None

    # get the comparison dirs
    # remove slashes from the ends of the paths
    compare_dirs = [x.rstrip("/") for x in compare_dirs]

    # remove the reference dir from the comparison dirs if present
    compare = [x for x in compare_dirs if x != reference]

    # Parse benchmark inclusion/exclusion lists
    compare_benchmarks = [x for x in args.benchmarks if not x.startswith("^")]
    exclude_benchmarks = [x[1:] for x in args.benchmarks if x.startswith("^")]

    log.debug("Loading results")
    # load all the runs to compare
    run_list = [reference, *compare] if reference else compare

    try:
        run_loaders = [RecipeRunLoader(p, compare_benchmarks, exclude_benchmarks) for p in run_list]
        log.debug("creating diff manager")
        # Create the diff orchestrator to compare the runs
        diff_manager = RecipesDiffManager(args.output_dir, run_loaders, sort_by=sort_by)

        log.debug("outputting diff results")
        # Output the diff results
        output_diff(args, diff_manager)

    except FileNotFoundError as fnf_error:
        log.error(fnf_error)
    except (RuntimeError, ValueError, OSError, KeyError, TypeError) as e:
        log.error(f"Error occurred: {e}")
