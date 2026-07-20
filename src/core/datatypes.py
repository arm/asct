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

import threading
import copy
from collections import namedtuple

Result = namedtuple("Result", ["desc", "dataframe"])


class ASCTSingleton(type):
    """
    Metaclass for all singleton classes
    """

    def __new__(cls, name, bases, dct):
        new_class = super().__new__(cls, name, bases, dct)
        new_class._inst = None
        new_class._lock = threading.Lock()
        return new_class

    def __call__(cls, *args, **kwargs):
        if cls._inst:
            return cls._inst
        with cls._lock:
            if cls._inst is None:
                cls._inst = super().__call__(*args, **kwargs)
        return cls._inst


# Simple key:value store that can support 'inheritance' of values from another registry
class ASCTDataRegistry:
    def __init__(self, **fields):
        # bypass __setattr__ which would result in infinite recursion
        object.__setattr__(self, "_data", {})
        object.__setattr__(self, "_parent", None)
        if fields:
            self.update_with(**fields)

    @classmethod
    def new_from(cls, other, **updates):
        """
        Creates a new ASCTDataRegistry, 'inheriting' the values from 'other' and
        updating it with the values in **updates
        """
        new_reg = cls()
        object.__setattr__(new_reg, "_parent", other)  # ruff:ignore[unnecessary-dunder-call] PLC2801
        new_reg.update_with(**updates)
        return new_reg

    def _set(self, name, value):
        """
        Private single field setter
        """
        self._data[name] = copy.deepcopy(value)

    def update_with(self, **kwargs):
        """
        Sets a batch of key:value pairs from kwargs
        """
        for name, value in kwargs.items():
            self._set(name, value)
        return self

    def update_with_dict(self, other_dict):
        """
        Updates the registry with key:value pairs from another dict,
        creating new keys, updating existing one and creating nested
        ASCTDataRegistry-based objects as needed.
        """

        for name, value in other_dict.items():
            self._set(name, value)
        return self

    # Attribute-style access (config.value_1)
    def __getattr__(self, name):
        try:
            if name in self._data:
                return self._data[name]
            if self._parent is not None:
                return getattr(self._parent, name)
        except KeyError:
            raise AttributeError(f"{self.__class__.__name__} has no field {name} - {self._data}") from None

    def __setattr__(self, name, value):
        self._set(name, value)

    # Dict-style acces (config["value_1")
    def __getitem__(self, key):
        if key in self._data:
            return self._data[key]
        if self._parent is not None:
            return self._parent[key]
        raise KeyError(key)

    def __setitem__(self, key, value):
        self._set(key, value)

    def __contains__(self, key):
        return key in self._data or (self._parent is not None and key in self._parent)

    def __repr__(self):
        return f"{self.get_dict()}"

    def get_dict(self):
        """
        Returns a dict with all the key:value pairs in this registry,
        including those 'inherited' from the parent registry (if any)
        """
        result = {}
        if self._parent is not None:
            result.update(self._parent.get_dict())
        result.update(self._data)
        return result
