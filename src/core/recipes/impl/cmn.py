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

import pandas as pd
from asct.core.cmn.cmn_api import ASCT_CMN, CMNRegDumperWithJson, get_cmn_data, discover, detect_cpus
from asct.core.recipes.recipe_base import RecipeBase
from asct.core.datatypes import ASCTSingleton
from asct.core import logger as log
from asct.core.utility.misc import flatten_dict
from asct.core.resources.check_paranoid_level import CheckParanoidLevel
from asct.core.resources.check_sudo import CheckSudo
from asct.core.resources.cmn_secure_access import CMNSecureAccess


class CMN(RecipeBase, metaclass=ASCTSingleton):
    """
    RecipeBase-derived class for running and reporting sysreport results.
    """

    def __init__(self, metadata):
        RecipeBase.__init__(self, metadata=metadata)
        self.initialize_config()
        self.cmn_list = []
        self._raw_result = None
        self._loaded_summary = None
        self.cmn_registers = {}

    @property
    def ready(self):
        return self._ready

    def _create_resources(self):
        resources = []

        if self._cfg.detect:
            # Ensure we can access perf_event_paranoid for detection
            resources.append(CheckSudo())
            resources.append(CheckParanoidLevel(max_required=0))

        if self._cfg.secure_access:
            resources.append(CMNSecureAccess())

        return resources

    def _dump_registers(self, cmn):
        """
        Dump registers for the given CMN instance and
        store them in the cmn_registers dictionary.
        """
        self.cmn_registers[id(cmn)] = cmn.get_registers()

    def _get_registers(self, cmn):
        """Retrieve the dumped registers for the given CMN
        instance from the cmn_registers dictionary.
        """
        return self.cmn_registers[id(cmn)]

    def _registers_str(self, cmn):
        string_data = cmn.sub_indent * " " + "Registers:\n"

        for node in self._get_registers(cmn):
            string_data += CMNRegDumperWithJson.to_string(node["registers"], indent=cmn.sub_indent + 3)
            string_data += "\n"

        return string_data

    def run_function(self):
        """
        Run the sysreport and collect results.
        """
        self.cmn_list = []
        self._raw_result = None
        self._loaded_raw_result = None
        self._loaded_summary = None
        self.detect = self._cfg.detect  # or self.cfg.verbose
        self.diagram = self._cfg.diagram
        self.secure_access = self._cfg.secure_access

        # Ensure CMN data is available else perform discovery
        if self.detect:
            discover(overwrite=True)
            detect_cpus(update=True)

        # Get CMN data
        self.cmn_data = get_cmn_data()

        if not self.cmn_data:
            log.warning("No CMN data found after discovery")
        else:
            for mesh in self.cmn_data.CMNs:
                if self.secure_access:
                    cmn = ASCT_CMN(mesh, secure_access=True)
                else:
                    cmn = ASCT_CMN(mesh)
                self._dump_registers(cmn)
                self.cmn_list.append(cmn)
        return self

    def _build_raw_results(self):
        results = {"system_type": self.cmn_data.system_type if self.cmn_data else None, "instances": []}

        # Add CMN details if available
        for cmn in self.cmn_list:
            cmn_out = {"id": cmn.id, "summary": cmn.summary_dict(), "registers": []}

            # Go through each node and add its registers to the results
            for node in self._get_registers(cmn):
                for r in node.get("registers", []):
                    cmn_out["registers"].append(cmn.register_dict(r))

            results["instances"].append(cmn_out)
        return results

    def raw_result(self):
        if self._loaded_raw_result is not None:
            return self._loaded_raw_result
        if self._raw_result is None:
            self._raw_result = self._build_raw_results()
        return self._raw_result

    def to_dict(self):
        return self.raw_result()

    def get_raw_results(self):
        raw_results = self.raw_result()
        summary_instances = [
            {
                "id": cmn.id,
                "header": str(cmn),
                "diagram_summary": cmn.diagram_summary_str(),
            }
            for cmn in self.cmn_list
        ]

        if summary_instances:
            raw_results = {
                **raw_results,
                "summary": {
                    "instances": summary_instances,
                },
            }

        return raw_results

    def get_diff_data(self):
        raw_results = self.raw_result()
        if raw_results is None:
            raise RuntimeError(f"result data was not loaded for {self.name}")
        diff_data = {}
        for cmn in self._loaded_raw_result.get("instances", []):
            cmn_id = str(cmn.get("id"))
            cmn_dict = diff_data.setdefault(cmn_id, {})
            for reg in cmn.get("registers", []):
                node = reg.get("node")
                reg_name = reg.get("reg_name")
                reg_dict = cmn_dict.setdefault(node, {}).setdefault(reg_name, {})
                reg_dict["raw_value"] = reg.get("value")
                for field in reg.get("fields", []):
                    reg_dict[field.get("field_name")] = field.get("value")
        return diff_data

    def _loaded_instances(self):
        instances = self._loaded_raw_result.get("instances", [])
        return instances if isinstance(instances, list) else []

    def _loaded_system_type(self):
        return self._loaded_raw_result.get("system_type")

    def to_stdout(self):
        print()
        if self._loaded_raw_result is not None:
            if not self._loaded_instances():
                print("No CMN data found.")
                return
            print(f"System: {self._loaded_system_type()}")
            print()
            rendered_instances = {}
            if isinstance(self._loaded_summary, dict):
                for instance in self._loaded_summary.get("instances", []):
                    if isinstance(instance, dict) and instance.get("id") is not None:
                        rendered_instances[instance.get("id")] = instance

            for idx, instance in enumerate(self._loaded_instances()):
                rendered_instance = rendered_instances.get(instance.get("id"))
                if isinstance(rendered_instance, dict):
                    header = rendered_instance.get("header")
                    diagram_summary = rendered_instance.get("diagram_summary")
                    if header:
                        print(header)
                        print()
                        if diagram_summary:
                            print(diagram_summary, end="" if diagram_summary.endswith("\n") else "\n")
                        print()
                        continue

                print(f"CMN Instance #{idx}")
                print(f"  ID: {instance.get('id')}")
                summary = instance.get("summary", {})
                for key, value in summary.items():
                    print(f"  {key}: {value}")
                print()
            return

        cmn_data = getattr(self, "cmn_data", None)
        if not cmn_data:
            print("No CMN data found.")
            return

        print(f"System: {cmn_data.system_type}")
        print()
        # Iterate over each CMN mesh and print its details
        for cmn in self.cmn_list:
            print(cmn)
            print()

            if self.diagram:
                print(cmn.diagram())
            else:
                print(cmn.diagram_summary_str())

    def to_stdout_verbose(self):
        """
        Prints the recipe result to standard output in a verbose,
        which may include additional details
        """
        print()
        if self._loaded_raw_result is not None:
            self.to_stdout()
            return

        cmn_data = getattr(self, "cmn_data", None)
        if not cmn_data:
            print("No CMN data found.")
            return

        print(f"System: {cmn_data.system_type}")
        print()
        # Iterate over each CMN mesh and print its details
        for cmn in self.cmn_list:
            if cmn is None:
                continue

            # in verbose mode we print the diagram summary and registers for each CMN mesh
            print(cmn)
            print()
            print(cmn.diagram_summary_str())
            print()
            print(self._registers_str(cmn))

    def to_csv_str(self):
        """
        Save the sysreport results to a CSV file.
        """
        raw_results = self.raw_result()
        rows = []
        system_type = raw_results.get("system_type") if isinstance(raw_results, dict) else None
        instances = raw_results.get("instances", []) if isinstance(raw_results, dict) else []

        for instance in instances:
            cmn_id = instance.get("id")
            summary = instance.get("summary", {})

            for register in instance.get("registers", []):
                node_name = register.get("node")
                reg_name = register.get("reg_name")
                fields = register.get("fields") or []
                rows.extend(
                    {
                        "system_type": system_type,
                        "cmn_id": cmn_id,
                        **summary,
                        "node": node_name,
                        "reg_name": reg_name,
                        **field,
                    }
                    for field in fields
                )

        if rows:
            df = pd.DataFrame(rows)
            return df.to_csv(index=False, header=True)

        flat_dict = flatten_dict(self.to_dict())
        df = pd.DataFrame(list(flat_dict.items()))
        return df.to_csv(index=False, header=False)

    def deserialize(self, data):
        if not data:
            return
        _, self._loaded_raw_result = self._deserialize_payload(data)
        if not isinstance(self._loaded_raw_result, dict):
            self._loaded_raw_result = {}
        if "summary" in self._loaded_raw_result:
            self._loaded_summary = self._loaded_raw_result.pop("summary")
        else:
            self._loaded_summary = None
        if self._loaded_summary is None:
            log.warning(
                "CPU topology/mesh info missing from result set; "
                "this is normal for results captured with older ASCT versions."
            )
        self.result = self
