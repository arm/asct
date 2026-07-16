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

import json
from typing import final, Any
import pandas as pd
from dataclasses import asdict, dataclass

from asct.core.benchspec.benchspec import ASCTBenchmarkConfig
from asct.core.datatypes import Result
from asct.core.managers.resource_manager import ResourceManager


@dataclass
class RawResult:
    """Class to store raw results and associated metadata for a recipe."""

    raw_result: dict[str, Any]
    metadata: dict[str, Any]


class RecipeBase:
    """Base Class for all ASCT Recipes."""

    print_index: bool = True

    def __init__(self, metadata):
        self._resource_manager = ResourceManager()
        self._metadata = metadata
        self.result = None
        self.depends_on = set(metadata.depends_on)  # string set of other recipes this recipe depends on
        self.benchmark_binary = None
        self.result_metadata = {}
        self._loaded_raw_result = None

        # Main configuration object for the recipe - initialized and updated with
        # user specified config in initialize_config()
        self._cfg = None

        self._priority = 100  # default run priority

        self._name = metadata.name
        self._desc = metadata.description
        self._tags = metadata.tags
        self._category = metadata.category

    def __lt__(self, other):
        """
        Compare priorities in ascending order.

        Args:
            other: Object with a `priority` attribute.

        Returns:
            bool: True if this object's priority is higher.
        """

        return self.priority < other.priority  # ascending by priority

    @property
    def priority(self):
        """
        Get the priority of the recipe. The lower the number, the higher the priority.

        Returns:
            int: The priority value of the recipe.
        """
        return self._priority

    @property
    def name(self):
        """
        Gets the name of the recipe

        Returns:
            string: name of the recipe
        """
        return self._name

    @property
    def tags(self):
        """
        Gets the tags of the recipe

        Returns:
            set[str]: tags of the recipe
        """
        return self._tags

    @property
    def desc(self):
        """
        Gets the description of the recipe

        Returns:
            string: description of the recipe
        """
        return self._desc

    @priority.setter
    def priority(self, value: int):
        """Set priority as a non-negative integer."""
        if not isinstance(value, int):
            raise TypeError("Priority must be an integer")
        if value < 0:
            raise ValueError("Priority must be a non-negative integer")
        self._priority = value

    @final
    def _register_resources(self):
        """
        Register resources created by _create_resources with the resource manager.
        """
        for item in self._create_resources():
            self._resource_manager.register(item, self)

    def _create_resources(self):
        """
        Creates the resources object for this recipe - to be overridden in derived classes.

        Returns:
            list: List of ResourceBase-derived objects.
        """
        return []

    def set_config(self, config):
        """
        Set the configuration for the recipe.
        This is optional and can be used to pass additional parameters
        or override existing parameters after initialization.
        Args:
            config: Configuration dictionary to set.
        """

    def run_function(self):
        """
        Defines the execution the primary functionality of the recipe.

        This method should be implemented by subclasses to define the specific
        behavior of the recipe. Calling this method directly without overriding
        it will raise a NotImplementedError.

        Raises:
            NotImplementedError: If the method is not implemented in a subclass.
        """
        raise NotImplementedError

    @final
    def initialize_config(self, extra_user_config=None, **kwargs):
        # Effective config resolution precedence (later entries override earlier ones):
        # 1) Metadata static defaults from RecipeMetadata.default_config (`configuration/metadata.py`)
        # 2) Runtime defaults added by `_create_default_config()` overrides in recipe classes
        # 3) `--config-file` values (converted/validated by schema)
        # 4) `--update-config` inline values (applied after file values)
        # 5) Runtime kwargs passed to `initialize_config(...)` by the runner
        #    (currently `pmu_mode`, sourced from ASCT debug env settings)
        #
        # Notes:
        # - Steps 3 and 4 are combined as `extra_user_config` before setup.
        # - This method is the canonical merge point for effective recipe config.
        self._cfg = self._create_default_config()
        if extra_user_config:
            self._cfg.update_with_dict(extra_user_config)
        if kwargs:
            self._cfg.update_with_dict(kwargs)

    def _create_default_config(self):
        """
        Creates the default configuration for the recipe from metadata.

        Default values are defined in recipe metadata (`configuration/metadata.py`) and are
        the single source of truth for static defaults.

        Derived classes should only override this method when they need to add
        runtime-dependent defaults (for example values derived from detected
        topology or resource state).

        Returns:
            ASCTBenchmarkConfig: The default configuration for the recipe.
        """
        return ASCTBenchmarkConfig().update_with_dict(self._metadata.default_config or {})

    def _pre_setup(self):
        pass

    def _pre_run(self):
        pass

    def _setup(self):
        self._register_resources()

    @final
    def setup(self):
        self._pre_setup()
        self._setup()

    @final
    def allocate_resources(self):
        self._resource_manager.apply_all(self)

    @final
    def teardown(self):
        self._resource_manager.restore_all(self)

    @final
    def run(self):
        """
        Executes the recipe by applying resources, running the main function,
        and performing cleanup.

        Returns:
            Any: The result of the `run_function` method.
        """
        self._pre_run()
        self.result = self.run_function()

    def __str__(self):
        return str(self.name)

    def to_stdout(self):
        """
        Prints the recipe result to standard output, including description,
        a separator line, and the dataframe content.
        This displays the minimum information the recipe prints to the user.
        """
        print(self.result.desc)
        print("-" * len(self.result.desc))
        print(self.result.dataframe.to_string(index=self.print_index, float_format=lambda x: f"{x:.1f}", na_rep="-"))
        print()

    def to_stdout_verbose(self):
        """
        Prints the recipe result to standard output in a verbose,
        which may include additional details
        """
        self.to_stdout()

    def to_csv_str(self):
        """
        Converts the result to a CSV formatted string.

        Returns:
            str: A string representation of the dataframe in CSV format with the index included.
        """
        return self.result.dataframe.to_csv(index=True)

    def to_dict(self):
        """
        Used for JSON output. As we want to collate results under various group
        headings, we collate all results in single python nested dict, then we
        can dump that whole dict as a raw JSON string.
        """
        return self.result.dataframe.to_dict(orient="dict")

    def to_json_str(self):
        """
        Returns the recipe result as a JSON-encoded string.
        """
        return json.dumps(self.to_dict())

    def get_raw_results(self):
        """
        Returns the raw results of the recipe.
        Returns:
            dict: The raw results of the recipe in JSON-serializable dictionary format.
        """
        return self.to_dict()

    def get_diff_data(self):
        if self._loaded_raw_result is None:
            raise RuntimeError(f"result data was not loaded for {self.name}")
        return self._loaded_raw_result

    @final
    def serialize(self):
        """
        Save the results with metadata.
        """
        if self.result is None:
            return None

        raw_results = RawResult(
            raw_result=self.get_raw_results(),
            metadata={
                "name": self._name,
                "description": self._desc,
                "result_desc": self.result.desc,
                "benchmark_binary": self.benchmark_binary,
                "config": self._cfg.get_dict(),
            },
        )

        # update with any user-defined metadata to save with result
        raw_results.metadata.update(self.result_metadata)

        # Return a dict representing the raw results to save to a file
        return asdict(raw_results)

    def _deserialize_metadata(self, data):
        """Extract and apply metadata fields from a saved data dict.

        Sets self.benchmark_binary and self.result_metadata.
        Returns the metadata dict, or {} if data is falsy (also resets fields).
        """
        metadata = data.get("metadata", {}) if isinstance(data, dict) else {}
        if not metadata:
            self.benchmark_binary = None
            self.result_metadata = {}
            self._cfg = None
            return {}
        self.benchmark_binary = metadata.get("benchmark_binary")
        saved_config = metadata.get("config")
        if isinstance(saved_config, dict):
            self._cfg = ASCTBenchmarkConfig().update_with_dict(saved_config)
        else:
            self._cfg = None
        self.result_metadata = {
            k: v
            for k, v in metadata.items()
            if k not in ("name", "description", "result_desc", "benchmark_binary", "config")
        }
        return metadata

    def _deserialize_payload(self, data):
        """Return normalized metadata and raw_result for current and legacy save formats."""
        if not data:
            return self._deserialize_metadata({}), None

        if not isinstance(data, dict):
            return self._deserialize_metadata({}), data

        metadata = self._deserialize_metadata(data)
        raw_result = data.get("raw_result", data)
        if isinstance(raw_result, str):
            try:
                raw_result = json.loads(raw_result)
            except json.JSONDecodeError:
                pass
        return metadata, raw_result

    def _deserialized_result_desc(self, metadata):
        saved_result_desc = metadata.get("result_desc", "")
        if saved_result_desc:
            return saved_result_desc
        results_desc = getattr(self, "results_desc", "")
        return results_desc or metadata.get("description", "")

    def deserialize(self, data):
        """
        Restore recipe state from the dict produced by serialize().
        """
        metadata, raw_result = self._deserialize_payload(data)
        self._loaded_raw_result = raw_result
        if raw_result is not None:
            self.result = Result(
                desc=self._deserialized_result_desc(metadata),
                dataframe=pd.DataFrame.from_dict(raw_result),
            )

    def cache_results(self):
        """
        returns data to be cached for the recipe
        it is assumed that the data returned is JSON serializable
        and the filename keys correspond to the output files that
        would be generated by the recipe after a successful run.
        Returns:
            dict: Dictionary containing {"filename": data_to_cache_as_dict}
            example: {"latency-sweep-summary.ubench.json": self.bench_summary,
                      "latency-sweep-results.ubench.json": self.final_df.to_dict()}
        """
        return {}
