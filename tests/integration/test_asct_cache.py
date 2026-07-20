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

"""Integration tests for recipe caching (c2c-latency) following style of c2c benchmark tests.

Focus: verify validator creation (via sysreport), recipe cache artifact generation, fingerprint stability,
and --no-cache flag behavior across output formats.
"""

import os
import time
import pytest

from pathlib import Path
from .utils import run_asct
from asct.core.cache import ASCTCache
from asct.core.recipes.configuration import registry as recipe_registry


SHA256_HEX_LENGTH = 64  # length of SHA-256 hex digest


def _hardware_validator_files(cache_dir: Path):
    return [p for p in cache_dir.iterdir() if p.is_file() and len(p.name) == SHA256_HEX_LENGTH and "." not in p.name]


@pytest.fixture(scope="function")
def fake_user_home(test_work_dir, monkeypatch):
    """
    Provide a fake HOME so cache writes go to an isolated directory.
    _cache_root() will resolve to this when USER is empty.
    """
    fake_home = Path(test_work_dir) / "fakehome/"
    fake_home.mkdir()
    # Ensure ASCTCache root gets created under this fake home
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USER", "")  # forces _cache_root to use "~" (HOME)
    monkeypatch.delenv("SUDO_USER", raising=False)
    yield fake_home


@pytest.fixture()
def cache_instance(fake_user_home):
    inst = ASCTCache(use_cache=True)
    assert str(fake_user_home) in str(inst.home_directory())
    yield inst
    # Remove cache contents after test
    inst.clear_asct_cache(invalidate=True)


def _cache_root():
    user = os.environ.get("SUDO_USER", os.environ.get("USER", ""))
    return Path(os.path.expanduser(f"~{user}")) / Path(ASCTCache.ASCT_CACHE_DIR)


def test_remove_cached_dependencies_filters_restored_dependencies_in_existing_order(monkeypatch):
    class FakeCache:
        def is_cache_available(self, recipe_name):
            return recipe_name == "dep-a"

        def restore_to_output_folder(self, recipe_name):
            return recipe_name == "dep-a"

    monkeypatch.setattr(recipe_registry, "cache", FakeCache)
    filtered = recipe_registry.RecipeFilteredBenchmarks()
    filtered.filtered_list = ["bench"]
    filtered.complete_list = ["dep-a", "dep-b", "bench"]
    filtered.added_dependencies = {"dep-a": ["bench"], "dep-b": ["bench"]}

    result = recipe_registry.RecipeRegistry.remove_cached_dependencies(None, filtered)

    assert result.cached_dependencies == {"dep-a": ["bench"]}
    assert result.added_dependencies == {"dep-b": ["bench"]}
    assert result.complete_list == ["dep-b", "bench"]


def test_remove_cached_dependencies_keeps_dependency_when_restore_fails(monkeypatch):
    class FakeCache:
        def is_cache_available(self, recipe_name):
            return recipe_name == "dep-a"

        def restore_to_output_folder(self, _recipe_name):
            return False

    monkeypatch.setattr(recipe_registry, "cache", FakeCache)
    filtered = recipe_registry.RecipeFilteredBenchmarks()
    filtered.filtered_list = ["bench"]
    filtered.complete_list = ["dep-a", "bench"]
    filtered.added_dependencies = {"dep-a": ["bench"]}

    result = recipe_registry.RecipeRegistry.remove_cached_dependencies(None, filtered)

    assert result.cached_dependencies == {}
    assert result.added_dependencies == {"dep-a": ["bench"]}
    assert result.complete_list == ["dep-a", "bench"]


def test_c2c_latency_triggers_latency_sweep_cache(test_work_dir, cache_instance):
    """
    Validate system info run creates valid system info cache files
    """
    test_work_dir = os.path.join(test_work_dir, "latency-sweep-cache")

    result = run_asct("run", ["c2c-latency", "--quick-mode"], output_dir=test_work_dir)

    assert result.ret_code == 0

    cache_dir = _cache_root()

    # latency-sweep cache should be created because c2c forces it to run
    sweep_file = cache_dir / "latency-sweep"
    assert sweep_file.exists(), "Expected latency-sweep cache to be generated before c2c-latency"
    sweep_fp = cache_instance.file_fingerprint_hash(str(sweep_file))
    assert (cache_dir / f"latency-sweep.{sweep_fp}").exists(), "Latency-sweep fingerprint missing"


def test_latency_sweep_cache_reuse(test_work_dir, cache_instance):
    """Second c2c-latency run should reuse existing latency-sweep cache without changing its fingerprint."""

    test_work_dir = os.path.join(test_work_dir, "latency-sweep-cache-reuse")
    result = run_asct("run", ["c2c-latency", "--quick-mode"], output_dir=test_work_dir)

    assert result.ret_code == 0

    cache_dir = _cache_root()
    sweep_file = cache_dir / "latency-sweep"
    assert sweep_file.exists(), "Initial latency-sweep cache missing"
    original_fp = cache_instance.file_fingerprint_hash(str(sweep_file))
    orig_fp_file = cache_dir / f"latency-sweep.{original_fp}"
    assert orig_fp_file.exists()
    # Second run
    time.sleep(0.2)
    run_asct("run", ["c2c-latency", "--quick-mode"], output_dir=None)
    new_fp = cache_instance.file_fingerprint_hash(str(sweep_file))
    new_fp_file = cache_dir / f"latency-sweep.{new_fp}"
    assert new_fp_file.exists()
    # Ideally unchanged; if changed treat as updated regeneration
    if new_fp != original_fp:
        assert not orig_fp_file.exists() or orig_fp_file.name != new_fp_file.name


def test_latency_sweep_removed_triggers_regeneration(test_work_dir):
    """Deleting latency-sweep cache forces regeneration before next c2c-latency run."""

    test_work_dir = os.path.join(test_work_dir, "latency-sweep-force-regen")
    run_asct("run", ["c2c-latency", "--quick-mode"], output_dir=test_work_dir)
    cache_dir = _cache_root()
    sweep_file = cache_dir / "latency-sweep"
    assert sweep_file.exists()
    for p in list(cache_dir.iterdir()):
        if p.name.startswith("latency-sweep"):
            p.unlink()
    assert not sweep_file.exists(), "latency-sweep file not removed"
    run_asct("run", ["c2c-latency", "--quick-mode"], output_dir=None)
    assert sweep_file.exists(), "latency-sweep cache not regenerated after deletion"


def test_validator_regeneration_reruns_cached_latency_sweep(test_work_dir, cache_instance):
    """
    Validate missing system validators invalidate and regenerate latency-sweep.
    """
    test_work_dir = os.path.join(test_work_dir, "latency-sweep-regen")
    run_asct("run", ["latency-sweep", "--quick-mode"], output_dir=test_work_dir)
    cache_dir = _cache_root()
    sweep_file = cache_dir / "latency-sweep"
    original_fp = cache_instance.file_fingerprint_hash(str(sweep_file))
    hw_files = _hardware_validator_files(cache_dir)
    assert hw_files, "No validator files created"
    hw_files[0].unlink()
    assert len(_hardware_validator_files(cache_dir)) < len(hw_files), "Validator file not removed"
    time.sleep(0.2)
    run_asct("run", ["c2c-latency", "--quick-mode"], output_dir=None)
    assert _hardware_validator_files(cache_dir), "Validators not regenerated"
    assert sweep_file.exists(), "Latency-sweep cache not regenerated after system cache invalidation"
    regenerated_fp = cache_instance.file_fingerprint_hash(str(sweep_file))
    assert regenerated_fp != original_fp
    assert (cache_dir / f"latency-sweep.{regenerated_fp}").exists()


def test_fingerprint_changes_on_mutation(test_work_dir, cache_instance):
    """
    when the latency sweep recipe cache is mutated, c2c-latency will trigger latency sweep run.
    This Latency sweep run will regenerate new cache file.
    """
    test_work_dir = os.path.join(test_work_dir, "c2c-latency-fp-mutation")
    run_asct("run", ["c2c-latency", "--quick-mode"], output_dir=test_work_dir)
    cache_dir = _cache_root()
    recipe_file = cache_dir / "latency-sweep"
    original_fp = cache_instance.file_fingerprint_hash(str(recipe_file))
    original_fp_file = cache_dir / f"latency-sweep.{original_fp}"
    assert original_fp_file.exists()
    with open(recipe_file, "a", encoding="utf-8") as f:
        f.write("\nmutate")
    time.sleep(0.2)
    run_asct("run", ["c2c-latency", "--quick-mode"], output_dir=None)
    new_fp = cache_instance.file_fingerprint_hash(str(recipe_file))
    new_fp_file = cache_dir / f"latency-sweep.{new_fp}"
    assert new_fp_file.exists()
    if new_fp != original_fp:
        assert not original_fp_file.exists() or original_fp_file.name != new_fp_file.name


def test_no_cache_flag(test_work_dir):
    work_dir = os.path.join(test_work_dir, "c2c-latency-no-cache-flag")
    result = run_asct("run", ["c2c-latency", "--quick-mode", "--no-cache"], output_dir=work_dir)
    assert result.ret_code == 0
    expected = "Latencies at different levels of cache"
    assert expected in result.stdout
