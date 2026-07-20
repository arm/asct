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

import atexit
from graphlib import TopologicalSorter
from collections import defaultdict
from asct.core.resources.resource_base import Resource
from asct.core.datatypes import ASCTSingleton
import asct.core.logger as log


class ResourceManager(metaclass=ASCTSingleton):
    def __init__(self):
        if hasattr(self, "global_resources"):
            return
        self.global_resources = []
        self.local_resources = defaultdict(list)
        # Register a cleanup function to be called at exit of the program.
        atexit.register(self._cleanup_all_resources)

    def register(self, resource: Resource, target_object=None, global_scope=False):
        """
        Register a resource.

        Args:
            resource (Resource): The resource to register.
            object (optional): Associated object (to identify the caller). Defaults to None.
            global_scope (bool): Register globally if True. Defaults to False.

        Notes:
            - Global resources are accessible globally.
            - Local resources are tied to the caller object's ID.
        """
        log.debug(f"Registering resource: {resource}")

        if global_scope:
            if resource in self.global_resources:
                # Skip a global resource if it has already been registered.
                # Note: Ensure that the resource class implements __eq__ and __hash__
                # to define how instances are compared and hashed appropriately.
                log.warning(f"Skipping: resource {resource} is already registered in the global context")
                return
            self.global_resources.append(resource)
        else:
            self.local_resources[id(target_object)].append(resource)

    def _topological_sort(self, resources):
        """
        Perform a topological sort on a list of Resource objects based on their dependencies.
        Args:
            resources (Iterable[Resource]): A resource object.
        Returns:
            List[Resource]: The Resource objects sorted in topological order of dependencies.
        Raises:
            CycleError: If a cycle is detected in the dependency graph.
        """

        # Map resource name → Resource object
        name_to_resource = {r.name: r for r in resources}

        # Create dependency graph: name → list of dependencies (by name)
        dep_graph = {r.name: r.depends_on for r in resources}

        # Perform topological sort PYTHON 3.9+
        sorter = TopologicalSorter(dep_graph)
        sorted_names = list(sorter.static_order())

        # Return the Resource objects in order
        return [name_to_resource[name] for name in sorted_names]

    def apply_all(self, target_object=None, global_scope=False):
        """
        Applies resources globally or for a specific object.

        Args:
            object (optional): Target object for local resources (required if `global_scope` is False).
            global_scope (bool): Apply global resources if True, else local. Defaults to False.

        Raises:
            ValueError: If `global_scope` is False and `object` is not provided.
            RuntimeError: If setting up a resource fails
        """
        log.debug(f"Applying all resources with global_scope={global_scope}")

        resource_objects = []
        if global_scope:
            # sorting the resources here in order of priorities
            self.global_resources = self._topological_sort(self.global_resources)
            resource_objects = self.global_resources
        elif target_object is None:
            raise ValueError("Object must be provided for local resources")
        else:
            resource_objects = self.local_resources.get(id(target_object), [])
            if resource_objects:
                resource_objects = self._topological_sort(resource_objects)
                self.local_resources[id(target_object)] = resource_objects

        self._apply_all(resource_objects)

    def _apply_all(self, resources):
        """
        Applies all resources.

        Args:
            resources: List of resources to apply.

        Raises:
            RuntimeError: If setting up a resource fails
        """
        for res in resources:
            if not res.applied:
                log.debug(f"Setting up resource: {res}")
                try:
                    res.setup()
                except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as exc:
                    log.debug(f"Setting up resource {res} failed: {exc}")
                    # required resource not available, skip benchmark
                    raise
                else:
                    res.applied = True
            else:
                log.debug(f"Resource already applied: {res}")

    def _cleanup_all_resources(self):
        """
        Cleans up all global and local resources.

        This method is called at the end of the program to ensure that all
        leftover resources are restored to their original state.
        """
        log.debug("Cleaning up global and local resources")
        self._restore_all_global()
        # make a `list` copy of the keys to avoid modifying the dictionary while iterating
        for object_id in list(self.local_resources):
            log.debug(f"Cleaning up local resources for object ID: {object_id}")
            self._restore_all_local_from_id(object_id)

    def restore_all(self, target_object=None, global_scope=False):
        """
        Restores resources for the given object or global scope.

        Args:
            object (optional): Object whose local resources to restore.
            global_scope (bool): If True, restores all global resources.

        Behavior:
            - Global: Teardown and clear all global resources.
            - Local: Teardown resources for the object and remove its list.
        """
        log.debug(f"Restoring all resources with global_scope={global_scope}")
        if global_scope:
            self._restore_all_global()
        else:
            self._restore_all_local(target_object)

    def _restore_all_local_from_id(self, object_id):
        for res in reversed(self.local_resources[object_id]):
            if res.applied:
                log.debug(f"Restoring local resource: {res}")
                res.teardown()

        del self.local_resources[object_id]

    def _restore_all_local(self, target_object):
        """
        Restores all local resources for the given object.

        Args:
            target_object: The object whose local resources to restore.
        """
        log.debug(f"Restoring all local resources for {target_object}")

        object_id = id(target_object)
        if object_id not in self.local_resources:
            log.debug(f"No local resources found for {target_object}")
            return

        self._restore_all_local_from_id(object_id)

    def _restore_all_global(self):
        """
        Restores all global resources.

        This method is called when exiting the context of the resource manager.
        It ensures that all global resources are restored to their original state.
        """
        log.debug("Restoring all global resources")
        for res in self.global_resources:
            log.debug(f"Restoring global resource: {res}")
            if res.applied:
                res.teardown()
        self.global_resources.clear()

    def __enter__(self):
        """
        Enter the resource manager context.

        This method is called when entering a `with` statement context.
        It applies all resources with a global scope.

        Returns:
            self: The resource manager instance.
        """
        log.debug("Entering resource manager context And applying resources")
        self.apply_all(global_scope=True)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """
        Handles the cleanup process when exiting the context of the resource manager.

        This method is automatically invoked when the context manager exits,
        regardless of whether an exception occurred or not. It ensures that all
        resources are restored to their original state.

        Args:
            exc_type (type): The class of the exception raised, if any. None if no exception occurred.
            exc_value (Exception): The instance of the exception raised, if any. None if no exception occurred.
            traceback (traceback): A traceback object representing the call stack at the point where
            the exception occurred. None if no exception occurred.
        """
        log.debug("Exiting resource manager context And restoring resources")
        self.restore_all(global_scope=True)

    def __str__(self):
        """
        String representation of the ResourceManager instance.

        Returns:
            str: A string representation of the ResourceManager instance.
        """
        return f"ResourceManager(global_resources={self.global_resources}, local_resources={self.local_resources})"

    def __repr__(self):
        """
        String representation of the ResourceManager instance.

        Returns:
            str: A string representation of the ResourceManager instance.
        """
        return self.__str__()
