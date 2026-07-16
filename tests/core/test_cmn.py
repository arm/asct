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

import importlib
import csv
from io import StringIO

from asct.core.benchspec.benchspec import ASCTBenchmarkConfig
from asct.core.recipes.configuration.metadata import ASCT_RECIPE_METADATA, get_recipe

cmn_module = importlib.import_module("asct.core.recipes.impl.cmn")
CMN = cmn_module.CMN


class DummyCMNData:
    def __init__(self, system_type="sys", meshes=None):
        self.system_type = system_type
        self.CMNs = meshes or []


def patch_init(monkeypatch):
    def _init(self):
        self._cfg = ASCTBenchmarkConfig(detect=False, diagram=False, advice=False)
        self._ready = True

    monkeypatch.setattr(CMN, "initialize_config", _init)


def make_dummy_cmn(id_="cmn0", summary=None, registers=None, strings=None):
    summary = summary or {"num_nodes": 1, "version": "v1"}
    registers = registers or [{"registers": []}]
    strings = strings or {"str": f"CMN(id={id_})", "summary": "SUMMARY", "registers": "REGISTERS", "diagram": "DIAGRAM"}

    class DummyASCT_CMN:
        def __init__(self, mesh):
            self.id = mesh["id"] if isinstance(mesh, dict) else str(mesh)

        def summary_dict(self):
            return dict(summary)

        def get_registers(self):
            return list(registers)

        def registers_str(self):
            return strings["registers"]

        def diagram_summary_str(self):
            return strings["summary"]

        def diagram(self):
            return strings["diagram"]

        def __str__(self):
            return strings["str"]

    return DummyASCT_CMN


# Test for no CMN data found scenario in to_stdout
def test_to_stdout_no_data(monkeypatch, capsys):
    patch_init(monkeypatch)
    monkeypatch.setattr(cmn_module, "get_cmn_data", lambda: None)

    cmn = CMN(get_recipe("cmn", ASCT_RECIPE_METADATA)).run_function()
    cmn.to_stdout()
    out = capsys.readouterr().out
    assert "No CMN data found." in out


# test detect throws an error if cmn data is not found
def test_detect_no_cmn_data(monkeypatch, caplog):
    def _noop(*_args, **_kwargs):
        return None

    patch_init(monkeypatch)
    monkeypatch.setattr(cmn_module, "discover", _noop)
    monkeypatch.setattr(cmn_module, "detect_cpus", _noop)
    monkeypatch.setattr(cmn_module, "get_cmn_data", lambda: None)
    cmn = CMN(get_recipe("cmn", ASCT_RECIPE_METADATA))
    cmn._cfg.detect = True
    cmn.run_function()
    assert "No CMN data found after discovery" in caplog.text


def test_to_csv_str_no_data_emits_minimal_row(monkeypatch):
    patch_init(monkeypatch)
    monkeypatch.setattr(cmn_module, "get_cmn_data", lambda: None)

    cmn = CMN(get_recipe("cmn", ASCT_RECIPE_METADATA))
    cmn._cfg.detect = False
    cmn._cfg.diagram = False
    cmn.cmn_list = []
    cmn.run_function()
    csv_rows = list(csv.reader(StringIO(cmn.to_csv_str())))

    assert csv_rows == [["system_type", ""]]


def test_get_raw_results_includes_summary(monkeypatch):
    patch_init(monkeypatch)
    monkeypatch.setattr(cmn_module, "ASCT_CMN", make_dummy_cmn(id_=0))
    monkeypatch.setattr(cmn_module, "get_cmn_data", lambda: DummyCMNData(meshes=[{"id": 0}]))

    cmn = CMN(get_recipe("cmn", ASCT_RECIPE_METADATA)).run_function()

    assert cmn.to_dict() == {
        "system_type": "sys",
        "instances": [{"id": 0, "summary": {"num_nodes": 1, "version": "v1"}, "registers": []}],
    }
    assert cmn.get_raw_results() == {
        "system_type": "sys",
        "instances": [{"id": 0, "summary": {"num_nodes": 1, "version": "v1"}, "registers": []}],
        "summary": {
            "instances": [
                {
                    "id": 0,
                    "header": "CMN(id=0)",
                    "diagram_summary": "SUMMARY",
                }
            ]
        },
    }


def test_loaded_to_stdout_uses_summary(monkeypatch, capsys):
    patch_init(monkeypatch)

    cmn = CMN(get_recipe("cmn", ASCT_RECIPE_METADATA))
    cmn.deserialize({
        "raw_result": {
            "system_type": "sys",
            "instances": [{"id": 0, "summary": {"version": "v1"}, "registers": []}],
            "summary": {
                "instances": [
                    {
                        "id": 0,
                        "header": "    CMN Instance #0\n    ===============\n        CMN version : v1",
                        "diagram_summary": "        CPU Grid Layout:\n             [cpu]\n",
                    }
                ]
            },
        }
    })

    cmn.to_stdout()
    out = capsys.readouterr().out

    assert "System: sys" in out
    assert "        CMN version : v1" in out
    assert "        CPU Grid Layout:" in out
    assert "             [cpu]" in out
    assert "  ID: 0" not in out


def test_loaded_to_stdout_warns_when_summary_is_missing(monkeypatch, capsys, caplog):
    patch_init(monkeypatch)

    cmn = CMN(get_recipe("cmn", ASCT_RECIPE_METADATA))
    cmn.deserialize({
        "raw_result": {
            "system_type": "sys",
            "instances": [{"id": 0, "summary": {"version": "v1"}, "registers": []}],
        }
    })

    assert (
        "CPU topology/mesh info missing from result set; this is normal for results captured with older ASCT versions."
    ) in caplog.text

    cmn.to_stdout()
    out = capsys.readouterr().out

    assert "CMN Instance #0" in out
    assert "  ID: 0" in out


def test_loaded_to_csv_str_matches_live_format(monkeypatch):
    patch_init(monkeypatch)

    cmn = CMN(get_recipe("cmn", ASCT_RECIPE_METADATA))
    cmn.deserialize({
        "raw_result": {
            "system_type": "sys",
            "instances": [
                {
                    "id": 0,
                    "summary": {
                        "version": "CMN-600 r2p1",
                        "CHI version": "CHI-B",
                        "X/Y config": "8 x 8",
                        "hn_type": "F",
                        "hn_count": 32,
                        "CCG count": 8,
                    },
                    "registers": [
                        {
                            "node": "cfg",
                            "reg_name": "por_cfgm_node_info",
                            "fields": [
                                {
                                    "field_name": "node_type",
                                    "value": "0x2",
                                    "bit_range": "[15:0]",
                                    "description": "node type",
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    })

    csv_rows = list(csv.reader(StringIO(cmn.to_csv_str())))

    assert csv_rows == [
        [
            "system_type",
            "cmn_id",
            "version",
            "CHI version",
            "X/Y config",
            "hn_type",
            "hn_count",
            "CCG count",
            "node",
            "reg_name",
            "field_name",
            "value",
            "bit_range",
            "description",
        ],
        [
            "sys",
            "0",
            "CMN-600 r2p1",
            "CHI-B",
            "8 x 8",
            "F",
            "32",
            "8",
            "cfg",
            "por_cfgm_node_info",
            "node_type",
            "0x2",
            "[15:0]",
            "node type",
        ],
    ]


def test_deserialize_warns_when_summary_is_missing(monkeypatch, caplog):
    patch_init(monkeypatch)

    cmn = CMN(get_recipe("cmn", ASCT_RECIPE_METADATA))
    cmn.deserialize({
        "raw_result": {
            "system_type": "sys",
            "instances": [{"id": 0, "summary": {"version": "v1"}, "registers": []}],
        }
    })

    assert cmn.to_dict() == {
        "system_type": "sys",
        "instances": [{"id": 0, "summary": {"version": "v1"}, "registers": []}],
    }
    assert (
        "CPU topology/mesh info missing from result set; this is normal for results captured with older ASCT versions."
    ) in caplog.text


def test_deserialize_normalizes_non_dict_loaded_raw_result(monkeypatch, caplog):
    patch_init(monkeypatch)

    cmn = CMN(get_recipe("cmn", ASCT_RECIPE_METADATA))
    cmn.deserialize({"raw_result": "invalid"})

    assert cmn._loaded_raw_result == {}
    assert cmn.to_dict() == {}
    assert (
        "CPU topology/mesh info missing from result set; this is normal for results captured with older ASCT versions."
    ) in caplog.text


def test_to_dict_caches_live_register_snapshot(monkeypatch):
    patch_init(monkeypatch)
    register_reads = {"count": 0}

    class DummyASCT_CMN:
        def __init__(self, _mesh):
            self.id = 0

        @staticmethod
        def register_dict(register):
            return dict(register)

        def summary_dict(self):
            return {"version": "v1"}

        def get_registers(self):
            register_reads["count"] += 1
            return [
                {
                    "registers": [
                        {
                            "node": "cfg",
                            "reg_name": "reg",
                            "value": register_reads["count"],
                            "fields": [],
                        }
                    ]
                }
            ]

        def diagram_summary_str(self):
            return "SUMMARY"

        def __str__(self):
            return "CMN(id=0)"

    monkeypatch.setattr(cmn_module, "ASCT_CMN", DummyASCT_CMN)
    monkeypatch.setattr(cmn_module, "get_cmn_data", lambda: DummyCMNData(meshes=[{"id": 0}]))

    cmn = CMN(get_recipe("cmn", ASCT_RECIPE_METADATA))
    cmn.initialize_config()
    cmn.run_function()
    first = cmn.to_dict()
    second = cmn.to_dict()

    assert register_reads["count"] == 1
    assert first == second
    assert first["instances"][0]["registers"][0]["value"] == 1
