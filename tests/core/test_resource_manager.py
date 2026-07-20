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

import pytest
import asct.core.logger as asct_logger
from asct.core.managers.resource_manager import ResourceManager
from asct.core.resources.resource_base import MultiResourceContainer, Resource


# Dummy resource to simulate behavior of a Resource.
class DummyResource:
    """Dummy resource for tests. Attributes: name, applied."""

    def __init__(self, name="dummy"):
        self.name = name
        self.applied = False
        self.depends_on = []

    def setup(self):
        self.applied = True

    def teardown(self):
        self.applied = False

    def __hash__(self):
        # Use id for hashing so that each instance is unique.
        return id(self)

    def __eq__(self, other):
        return self is other

    def __repr__(self):
        return f"DummyResource({self.name})"


class FailingResource(DummyResource):
    def setup(self):
        raise RuntimeError(f"{self.name} failed")


@pytest.fixture(autouse=True)
def test_logger(monkeypatch):
    class TestLogger:
        def __init__(self):
            self.warnings = []

        def warning(self, msg):
            self.warnings.append(msg)

    logger = TestLogger()
    monkeypatch.setattr(asct_logger, "warning", logger.warning)
    return logger


# Fixture to ensure a clean ResourceManager state for every test.
@pytest.fixture(autouse=True)
def cleanup_resource_manager():
    """
    Set up and tear down the resource manager's resources.

    This context manager clears both the global and local resources of the resource manager
    before entering the context and again after exiting. It ensures that tests or operations
    execute with a clean state, preventing residual resource data from previous runs from affecting
    future outcomes.
    """
    rm = ResourceManager()
    rm.global_resources.clear()
    rm.local_resources.clear()
    yield
    rm.global_resources.clear()
    rm.local_resources.clear()


def test_singleton():
    """Test that ResourceManager implements the singleton pattern.

    Instantiates ResourceManager twice and verifies that both instances are the same,
    thereby enforcing that only one instance exists.
    """
    rm1 = ResourceManager()
    rm2 = ResourceManager()
    assert rm1 is rm2, "ResourceManager is not a singleton"


def test_register_and_apply_global_resource():
    """Test registration and application of a global resource."""
    rm = ResourceManager()
    resource = DummyResource("global1")
    # Register resource globally.
    rm.register(resource, global_scope=True)
    # Apply global resources.
    rm.apply_all(global_scope=True)
    assert resource.applied, "Global resource was not applied"

    # Restore global resources.
    rm.restore_all(global_scope=True)
    assert not resource.applied, "Global resource was not restored"


def test_register_and_apply_local_resource():
    """
    Test the registration, application, and restoration of a local resource with ResourceManager.
    """
    rm = ResourceManager()
    resource = DummyResource("local1")
    target_object = object()
    # Register resource locally.
    rm.register(resource, target_object=target_object, global_scope=False)
    # Applying local resources.
    rm.apply_all(target_object=target_object, global_scope=False)
    assert resource.applied, "Local resource was not applied"

    # Restore local resources.
    rm.restore_all(target_object=target_object, global_scope=False)
    assert not resource.applied, "Local resource was not restored"


def test_register_same_global_resource_twice_warning(test_logger):
    """
    Test that attempting to register the same global resource twice.
    Prints a warning message.
    """
    rm = ResourceManager()
    resource = DummyResource("global2")
    rm.register(resource, global_scope=True)
    rm.register(resource, global_scope=True)
    assert "is already registered in the global context" in test_logger.warnings[0]


def test_apply_all_without_target_object_raises_value_error():
    """
    Test that calling ResourceManager.apply_all without providing a target object
    (when global_scope is set to False) raises a ValueError.
    """
    rm = ResourceManager()
    with pytest.raises(ValueError):
        rm.apply_all(global_scope=False)


def test_apply_all_logs_and_reraises_setup_failure(monkeypatch):
    messages = []
    monkeypatch.setattr(asct_logger, "debug", messages.append)

    rm = ResourceManager()
    resource = FailingResource("failing-resource")
    rm.register(resource, global_scope=True)

    with pytest.raises(RuntimeError, match="failing-resource failed"):
        rm.apply_all(global_scope=True)

    assert messages[-1] == "Setting up resource DummyResource(failing-resource) failed: failing-resource failed"
    assert not resource.applied


def test_context_manager_applies_and_restores_global_resources():
    """
    Test that the ResourceManager context manager correctly applies and restores global resources.
    """
    rm = ResourceManager()
    resource = DummyResource("global_context")
    rm.register(resource, global_scope=True)
    # Before entering context, resource should not be applied.
    assert not resource.applied, "Resource should not be applied before context"
    with rm:
        # __enter__ applies global resources.
        assert resource.applied, "Resource was not applied in context"
    # __exit__ restores global resources.
    assert not resource.applied, "Resource was not restored after context"


def test_resource_base_file_helpers_wrap_os_errors(tmp_path):
    resource = Resource()
    target = tmp_path / "value"

    resource._set_sysfile_value(target, "42\n")
    assert resource._get_sysfile_value(target) == "42"

    with pytest.raises(NotImplementedError):
        resource.setup()

    with pytest.raises(NotImplementedError):
        resource.teardown()

    with pytest.raises(FileNotFoundError, match="Error reading from sysfs path"):
        resource._get_sysfile_value(tmp_path / "missing")


def test_multi_resource_container_handles_partial_and_total_failures():
    ok = DummyResource("ok")
    bad = FailingResource("bad")

    container = MultiResourceContainer(bad, ok, require_all=False)
    assert container.setup() is True
    assert ok.applied is True
    assert container.applied is True
    assert "MultiResourceContainer" in str(container)

    all_bad = MultiResourceContainer(FailingResource("one"), FailingResource("two"), require_all=False)
    with pytest.raises(RuntimeError, match="one failed OR two failed"):
        all_bad.setup()

    require_all = MultiResourceContainer(FailingResource("first"), ok, require_all=True)
    with pytest.raises(RuntimeError, match="first failed"):
        require_all.setup()


def test_cleanup_all_resources_restores_each_local_resource_list():
    rm = ResourceManager()
    target_a = object()
    target_b = object()
    resource_a = DummyResource("local_a")
    resource_b = DummyResource("local_b")

    rm.register(resource_a, target_object=target_a, global_scope=False)
    rm.register(resource_b, target_object=target_b, global_scope=False)
    rm.apply_all(target_object=target_a)
    rm.apply_all(target_object=target_b)

    rm._cleanup_all_resources()

    assert not resource_a.applied
    assert not resource_b.applied
    assert rm.local_resources == {}
