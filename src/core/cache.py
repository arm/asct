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

import os
import pwd
import grp
import json
import hashlib
import shutil
from dataclasses import asdict
import asct.core.logger as log
from asct.core.utility.files import read_json_file, write_to_file
from asct.core.datatypes import ASCTSingleton


class ASCTCache(metaclass=ASCTSingleton):
    ASCT_CACHE_DIR = os.path.join(".cache", "arm", "asct")

    def __init__(self, use_cache=False, output_folder="./"):
        self.use_cache = use_cache
        self.valid = True
        self.asct_output_folder = output_folder
        if self.use_cache:
            log.debug("ASCT cache is enabled and will be used where possible")
            self.create_asct_cache_dir()

    def home_directory(self):
        """
        Get the current (real) user's home directory, even if sudo.
        """
        user = os.environ.get("SUDO_USER", os.environ.get("USER", ""))
        if not user:
            log.debug("No SUDO_USER or USER environment variable set, using current home directory")
        return os.path.expanduser("~" + user)

    @property
    def cache_directory(self):
        """
        Get the ASCT cache directory, ensuring it exists
        """
        return os.path.join(self.home_directory(), ASCTCache.ASCT_CACHE_DIR)

    def change_to_real_user_if_sudo(self, directory):
        """
        Change the ownership of the given file/directory to the real user if running as sudo.
        If not running as sudo (i.e., SUDO_USER is not set), ownership change is not required.
        """
        user = os.environ.get("SUDO_USER")
        if not user:
            # Not running as sudo, so no ownership change is needed.
            log.debug("No SUDO_USER environment variable set; ownership change not required")
            return

        log.debug(f"changing {directory} permissions to {user}")
        user_info = pwd.getpwnam(user)
        primary_group = grp.getgrgid(user_info.pw_gid).gr_name
        shutil.chown(directory, user=user, group=primary_group)

    def create_asct_cache_dir(self):
        """
        Create the ASCT cache directory if it doesn't already exist
        """
        cache_dir = self.cache_directory
        try:
            os.makedirs(cache_dir, exist_ok=True)
            self.change_to_real_user_if_sudo(cache_dir)
        except (OSError, KeyError) as e:
            log.warning(f"Unable to create ASCT cache directory {cache_dir}: {e}")

    def clear_asct_cache(self, invalidate=False):
        """
        Invalidate the file cache for ASCT by removing the cache directory
        """
        cache_dir = self.cache_directory
        # Only invalidate if there are files in the cache directory
        if invalidate and os.path.exists(cache_dir) and os.listdir(cache_dir):
            log.info("Invalidating ASCT cache")
            # Remove the cache directory and its contents
            shutil.rmtree(cache_dir)
            # Re-create the cache directory
            self.create_asct_cache_dir()

    def refresh_cache(self, system_info):
        """
        Manage the ASCT cache, invalidating if required
        """
        if not self.use_cache:
            return

        if self.use_cache and not self.is_asct_cache_valid(system_info):
            log.debug("ASCT cache is invalidated due to system configuration change")
            self.clear_asct_cache(invalidate=True)

    def save_cache_validator(self, system_info):
        """
        Save the cache validator information for the current system
        The is stored as files named by the hash of the system information
        to allow easy validation
        """
        if self.valid:
            log.debug("ASCT cache is already valid, no need to save validator")
            return

        if self.use_cache:
            # use the hash as filename
            log.debug("Saving cache validator")
            memory_data = asdict(system_info.memory)
            hardware_data = asdict(system_info.sys_hw)
            # write the cache validator files separately,
            # memory info check may be skipped in is_asct_cache_valid
            # when not running as root as non-root users may not have access to memory info
            self.write_to_cache(memory_data, self._hash_dict(memory_data))
            self.write_to_cache(hardware_data, self._hash_dict(hardware_data))

    def file_fingerprint_hash(self, path):
        st = os.stat(path)
        return self._hash_dict({"mtime": st.st_mtime, "size": st.st_size})

    def save(self, recipe):
        """
        Save the given recipe data to the ASCT cache
        """
        if not self.use_cache:
            return

        if not recipe:
            log.debug(f"No cacheable results for recipe {getattr(recipe, 'name', 'unknown')}")
            return

        cache_data = recipe.cache_results()
        if not cache_data:
            log.debug(f"No cacheable results for recipe {recipe.name}")
            return

        log.debug(f"Clearing existing cache for recipe {recipe.name} before saving new cache")
        self.clear_recipe_cache(recipe.name)

        log.debug(f"Caching results for recipe {recipe.name}")
        self.write_to_cache(cache_data, recipe.name)
        # Also save the file fingerprint
        cache_file = os.path.join(self.cache_directory, recipe.name)
        file_finger_print = self.file_fingerprint_hash(cache_file)
        self.write_to_cache(file_finger_print, recipe.name + f".{file_finger_print}")

    def clear_recipe_cache(self, recipe_name: str):
        """
        Clear the cache for the recipe with the given name.
        """
        if not self.use_cache:
            log.debug(f"Cache usage disabled, cannot clear cache for {recipe_name}")
            return

        log.debug(f"Clearing cache for recipe {recipe_name}")
        cache_file = self.get_cache_file_path(recipe_name)
        try:
            if os.path.exists(cache_file):
                os.remove(cache_file)
            # remove any fingerprint files associated with this recipe
            for entry in os.listdir(self.cache_directory):
                if entry.startswith(f"{recipe_name}."):
                    fp = self.get_cache_file_path(entry)
                    try:
                        os.remove(fp)
                    except OSError as e:
                        log.warning(f"Unable to remove fingerprint file {fp}: {e}")
        except OSError as e:
            log.warning(f"Unable to clear cache for recipe {recipe_name}: {e}")

    def is_cache_available(self, recipe_name: str) -> bool:
        """
        Check if cached results are available for the recipe with the given name.
        and if the cache file has not been modified since it was cached.
        Returns:
            bool: True if cached results are available, False otherwise.
        """
        if not self.use_cache:
            log.debug(f"Cache usage disabled, cache not available for {recipe_name}")
            return False

        log.debug("Checking if cache file exists")
        cache_file = self.get_cache_file_path(recipe_name)

        if not os.path.exists(cache_file):
            return False

        log.debug("Checking if cache not modified")

        # check if the cache file has been modified since it was cached
        fingerprint_path = self.get_cache_file_path(recipe_name + f".{self.file_fingerprint_hash(cache_file)}")
        fingerprint_match = os.path.exists(fingerprint_path)
        if not fingerprint_match:
            log.debug(f"Cache file {cache_file} has been modified since last cached")
            self.clear_recipe_cache(recipe_name)
            return False

        return True

    def restore_to_output_folder(self, recipe_name: str):
        """
        Restore the cached results for the recipe with the given name to
        the current ASCT output folder, to be used by other recipes that need them.
        """
        if not self.use_cache:
            log.debug(f"Cache usage disabled, cannot restore cache for {recipe_name}")
            return

        log.debug(f"Restoring cached results for recipe {recipe_name}")
        cache_file = os.path.join(self.cache_directory, recipe_name)
        try:
            recipe_data = read_json_file(cache_file)
            recipe_dir = os.path.join(self.asct_output_folder, "raw", recipe_name)
            os.makedirs(recipe_dir, exist_ok=True)
            for output_file, content in recipe_data.items():
                output_file = os.path.join(recipe_dir, output_file)
                log.debug(f"Restoring cached file {output_file}")
                write_to_file(output_file, json.dumps(content), "w")
                self.change_to_real_user_if_sudo(output_file)
        except (OSError, ValueError, TypeError, AttributeError) as e:
            log.warning(f"Unable to restore cache for recipe {recipe_name}: {e}")

    def write_to_cache(self, recipe_data: dict, recipe_name: str):
        """
        Write the given recipe data to the ASCT cache
        """
        if not recipe_data:
            log.debug(f"No data to cache for {recipe_name}")
            return

        cache_file = os.path.join(self.cache_directory, recipe_name)
        try:
            log.debug(f"Writing cache file {cache_file}")
            write_to_file(cache_file, json.dumps(recipe_data), "w")
            self.change_to_real_user_if_sudo(cache_file)
        except (OSError, ValueError, TypeError) as e:
            log.warning(f"Unable to write cache file {cache_file}: {e}")

    def recipe_cache_exists(self, recipe_name: str) -> bool:
        """
        Check if the cache for the given recipe exists
        """
        cache_file = os.path.join(self.cache_directory, recipe_name)
        return os.path.exists(cache_file)

    def get_cache_file_path(self, recipe_filename: str) -> str:
        """
        Get the full path to the cache file for the given recipe
        """
        return os.path.join(self.cache_directory, recipe_filename)

    def read_from_cache(self, recipe_name: str) -> dict:
        """
        Read the cached data for the given recipe.
        Returns:
            dict: The cached data for the recipe, or an empty dictionary if not found or error.
        """
        data = {}
        if not self.use_cache or not self.recipe_cache_exists(recipe_name):
            log.debug(f"Cache usage disabled, cannot read cache for {recipe_name}")
            return data

        cache_file = os.path.join(self.cache_directory, recipe_name)
        try:
            log.debug(f"Reading cache file {cache_file}")
            data = read_json_file(cache_file)
        except (OSError, ValueError, TypeError) as e:
            log.warning(f"Unable to read cache file {cache_file}: {e}")

        return data or {}

    @staticmethod
    def _hash_dict(obj: dict) -> str:
        """
        Create a SHA256 hash of the given dictionary"""
        payload = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def is_asct_cache_valid(self, system_info) -> bool:
        """
        Check if the given path is the ASCT cache directory
        """
        log.debug("Validating ASCT cache")

        # create a hash of the current memory configuration
        memory_hash = self._hash_dict(asdict(system_info.memory))
        system_hardware_hash = self._hash_dict(asdict(system_info.sys_hw))

        # check if currently running sudo
        is_root = hasattr(os, "geteuid") and os.geteuid() == 0

        # non root users may not have memory info cached
        # note that a filename which is a hash of the memory info
        if is_root and not os.path.exists(self.get_cache_file_path(memory_hash)):
            log.debug("No cached memory hash found")
            self.valid = False
            return False

        if not os.path.exists(self.get_cache_file_path(system_hardware_hash)):
            log.debug("No cached system hardware hash found")
            self.valid = False
            return False

        return True
