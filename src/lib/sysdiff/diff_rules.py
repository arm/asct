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

from dataclasses import dataclass

from asct.core.sysdiff.comparators import Comparator


# Default ignores for all recipes
# These could be loaded from a config file or set per-recipe if needed
Comparator.add_ignore_key("cmd_arguments.func")
Comparator.add_ignore_key("cmd_arguments.output_dir")
Comparator.add_ignore_key("cmd_arguments.output_dir_path")
Comparator.add_ignore_key("run_id")
Comparator.add_ignore_key("system-info.result.sys_hw.numa_nodes.*")
Comparator.add_ignore_key("timestamp")
Comparator.add_ignore_key("collected_time")
Comparator.add_ignore_key("benchmark_binary")
Comparator.add_ignore_key("cmd_arguments.log_file")
Comparator.add_ignore_key("metadata.name")
Comparator.add_ignore_key("metadata.config")
Comparator.add_ignore_key("top_latencies.latencies.*")
Comparator.add_ignore_key("data.MEMBIND_NODE.*")
Comparator.add_ignore_key("data.LATENCY.*")
Comparator.add_ignore_key("data.CPUA.*")
Comparator.add_ignore_key("data.CPUB.*")
Comparator.add_ignore_key("data.CPUA_NODE.*")
Comparator.add_ignore_key("data.CPUB_NODE.*")


@dataclass
class Rule:
    path: str
    comparator: Comparator


class RuleBase:
    """Base class for defining a set of rules for a specific path prefix."""

    def __init__(self, rules: list[Rule]):
        self.rules = {rule.path: rule for rule in rules}

    def get_rule(self, path) -> Rule:
        rule = self.rules.get(path, None)
        if rule is None:
            # Check for wildcard matches
            for key, r in self.rules.items():
                if key.endswith(".*") and path.startswith(key[:-2]):
                    return r
            # Default rule: use base comparator
            rule = Rule(path, Comparator())
        return rule
