#!/usr/bin/env bash
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

set -eu -o pipefail

PY_COMMAND="/usr/bin/env python3"
PIP_COMMAND="$PY_COMMAND -m pip"

SCRIPTS_DIR="$(pwd)/scripts"
DEVELOP_BUILD_DIR="$(pwd)/devel"
RELEASE_BUILD_DIR="$(pwd)/dist"

TEST_WORK_DIR="$DEVELOP_BUILD_DIR/test_work_dir"
DEVELOP_VENV_DIR="$DEVELOP_BUILD_DIR/venv"
BUILD_VENV_DIR="$DEVELOP_BUILD_DIR/build_venv"
UBENCH_CONFIG="$(pwd)/src/core/config/ubench.json"
PYPROJECT_FILE="pyproject.toml"
VERSION_TAG=""
BUILD_TAG=""

# Verify PIP packages are installed
REQUIRED_PIP_PACKAGES="setuptools build"

function print_help_and_exit() {
  err_code=$1

  echo "Usage: $0 <build_mode> [--quick-test]"
  echo "> build_mode can be:"
  echo ">   devel - creates a virtual env and installs asct in editable mode"
  echo ">   bin - rebuilds the binaries for the devel build"
  echo ">   release - creates a pip installable source package in ./dist"
  echo ">   --suffix <string>     append \"<string>\" to the version in pyproject.toml (release only)"
  echo ">   activate - activates the development virtual env"
  echo ">   clean - cleans up all build artifacts"
  echo ">   test - runs tests"
  echo "> --quick-test - enables running a quick sanity check for the release package"
  echo "> --test-params - string passed as parameters to pytest"

  exit $err_code
}

function create_and_source_venv() {
  local venv_dir=$1
  local always_delete=$2

  if [ ! -d $venv_dir ] || $always_delete; then
    rm -rf $venv_dir
    mkdir -p $venv_dir

    $PY_COMMAND -m venv $venv_dir
  fi

  source $venv_dir/bin/activate

  $PIP_COMMAND install pip --upgrade
  $PIP_COMMAND install $REQUIRED_PIP_PACKAGES --upgrade
}

function pre_release_setup() {
  # Remove intermediary directories
  rm -rf $RELEASE_BUILD_DIR asct.egg-info
  create_and_source_venv $BUILD_VENV_DIR true
  $PIP_COMMAND install twine pkginfo --upgrade
}

function get_asct_release() {
    local -n _filepath=$1
    local -n _ver=$2
    local release_build_dir=$3
    local count=0

    shopt -s nullglob
    for match in $release_build_dir/asct-*.tar.gz; do
        # increment count
        count=$((count + 1))

        # if more than one match, error out
        if [ "$count" -gt 1 ]; then
            echo "ERROR: multiple pip source packages found in $release_build_dir!" >&2
            shopt -u nullglob
            return 1
        fi

        _filepath=$match
        _ver=$(basename "$match")
        _ver=${_ver#asct-}
        _ver=${_ver%.tar.gz}
    done
    shopt -u nullglob

    # if none found, error out
    if [ $count -eq 0 ]; then
        echo "ERROR: no pip source packages found in $release_build_dir!" >&2
        return 1
    fi
}

function get_pyproject_version() {
  grep -m1 '^version' "$PYPROJECT_FILE" | cut -d '"' -f2
}

function stage_pip_package_to_bundle() {
  local package_file_path="$1"
  local bundle_dir="$2"

  if [ ! -f "$package_file_path" ]; then
    echo "Error: pip package not found: $package_file_path" >&2
    exit 1
  fi
  cp -a "$package_file_path" "$bundle_dir/"
}

function stage_html_docs_to_bundle() {
  # Builds HTML documentation from the markdown files in the repo and stages it in the bundle directory.
  # The HTML docs are built as a single page from the markdown files using pandoc, with some preprocessing
  # to remove sections that should be omitted from the published docs.
  local bundle_dir="$1"
  local output_dir="$bundle_dir/asct_docs"
  local output_file="$output_dir/index.html"
  local f

  command -v pandoc >/dev/null 2>&1 || {
    echo "Error: required command not found in PATH: pandoc" >&2
    echo "Hint: install pandoc and retry" >&2
    exit 1
  }
  command -v sed >/dev/null 2>&1 || {
    echo "Error: required command not found in PATH: sed" >&2
    echo "Hint: install sed and retry" >&2
    exit 1
  }

  rm -rf "$output_dir"
  mkdir -p "$output_dir/resources" "$output_dir/docs"
  cp -r docs/resources/* "$output_dir/resources"

  cp README.md INSTALL.md USAGE.md "$output_dir"
  cp docs/memory.md docs/storage.md docs/system_report.md docs/sysdiff.md "$output_dir/docs"

  for f in "$output_dir"/*.md "$output_dir"/docs/*.md; do
    [ -f "$f" ] || continue
    sed -i'' -e '/<!-- PUBLISH_OMIT:start -->/,/<!-- PUBLISH_OMIT:end -->/d' "$f"
  done

  pandoc "$output_dir/README.md" \
         "$output_dir/INSTALL.md" \
         "$output_dir/USAGE.md" \
         "$output_dir/docs/system_report.md" \
         "$output_dir/docs/memory.md" \
         "$output_dir/docs/storage.md" \
         "$output_dir/docs/sysdiff.md" \
         -s -o "$output_file"

  # Post-process the generated HTML to replace links to the
  # original markdown files with links to the corresponding
  # sections in the single-page HTML docs.
  sed -i'' -e 's/INSTALL.md/\#install-asct/g' "$output_file"
  sed -i'' -e 's/USAGE.md/\#getting-started/g' "$output_file"
  sed -i'' -e 's/docs\/system_report.md/\#system-report/g' "$output_file"
  sed -i'' -e 's/docs\/memory.md/\#memory-characterization/g' "$output_file"
  sed -i'' -e 's/docs\/storage.md/\#storage-characterization/g' "$output_file"
  sed -i'' -e 's/docs\/sysdiff.md/\#compare-run-results/g' "$output_file"

  rm "$output_dir"/*.md
  rm -r "$output_dir/docs"
}

function stage_install_sh_to_bundle() {
  # Stages the install.sh script into the bundle directory. This script is a convenience
  # for users installing from the release tarball, as it provides a simple way to install 
  # ASCT without needing to manually run pip install on the included source package.
  # The install.sh script will be copied from the scripts directory and made executable
  # in the bundle directory.
  local bundle_dir="$1"
  local install_sh="$SCRIPTS_DIR/install.sh"

  if [ ! -f "$install_sh" ]; then
    echo "Error: install script not found: $install_sh" >&2
    exit 1
  fi
  cp -a "$install_sh" "$bundle_dir/install.sh"
  chmod +x "$bundle_dir/install.sh"
}

function stage_readme_to_bundle() {

  # Builds a README.txt for the release bundle from INSTALL.md, excluding the "Download ASCT" section 
  # which is not relevant for end users installing from the release tarball. Also replaces the 
  # placeholder tarball name in INSTALL.md with the actual release tarball name.

  local bundle_dir="$1"
  local version="$2"
  local install_md="$(pwd)/INSTALL.md"
  local readme_md
  local release_tar

  if [ ! -f "$install_md" ]; then
    echo "Error: INSTALL.md not found: $install_md" >&2
    exit 1
  fi

  # Build README.txt from INSTALL.md, excluding the "Download ASCT" section.
  readme_md=$(mktemp)
  sed '/^##[[:space:]]\+Download ASCT[[:space:]]*$/,/^##[[:space:]]\+Install ASCT[[:space:]]*$/ { /^##[[:space:]]\+Install ASCT[[:space:]]*$/!d }' \
  "$install_md" > "$readme_md"

  pandoc "$readme_md" -t plain --wrap=none -o "$bundle_dir/README.txt"
  rm -f "$readme_md"

  # Replace the placeholder tarball name used in INSTALL.md with the actual release tarball.
  release_tar="asct-${version}-release.tar.gz"
  # Escape '&' for safe use in the sed replacement string.
  sed -i'' -e "s/asct-<version>-release\\.tar\\.gz/${release_tar//&/\\&}/g" "$bundle_dir/README.txt"
}

function cleanup_standalone_sdist() {
  local package_file_path="$1"
  rm -f "$package_file_path"
}

function cleanup_bundle_dir() {
  local bundle_dir="$1"
  rm -rf "$bundle_dir"
}

function create_release_bundle_tarball() {
  # Creates a tarball of the staged release bundle in the dist directory,
  # with a name that includes the ASCT version.
  local dist_dir="$1"
  local package_file_path="$2"
  local bundle_dir="$3"

  local base_name
  local tar_name

  base_name="$(basename "$package_file_path")"
  base_name="${base_name%.tar.gz}"
  tar_name="${base_name}-release.tar.gz"
  tar -C "$dist_dir" -czf "$dist_dir/$tar_name" "$(basename "$bundle_dir")"
  echo "Bundled release -> $dist_dir/$tar_name"
}

function create_release_bundle() {
  local dist_dir="$1"
  local version="$2"
  local package_file_path="$3"

  local bundle_dir="$dist_dir/asct-${version}"
  rm -rf "$bundle_dir"
  mkdir -p "$bundle_dir"

  # Stage the pip package, HTML docs, install script,
  # and README into the bundle directory, then create a tarball of the bundle.
  stage_pip_package_to_bundle "$package_file_path" "$bundle_dir"
  stage_html_docs_to_bundle "$bundle_dir"
  stage_install_sh_to_bundle "$bundle_dir"
  stage_readme_to_bundle "$bundle_dir" "$version"
  create_release_bundle_tarball "$dist_dir" "$package_file_path" "$bundle_dir"

  cleanup_bundle_dir "$bundle_dir"
}

function build_release() {
  local quick_tests_enabled=$1
  local package_file_path=""
  local version=""
  local result=0

  pre_release_setup
  $PY_COMMAND -m build --sdist

  get_asct_release package_file_path version $RELEASE_BUILD_DIR
  result=$?
  if [ $result -ne 0 ]; then
    exit $result
  fi
  echo "Built ASCT $version -> $package_file_path"

  echo "Verifying distribution package metadata"
  twine check $package_file_path || result=$?
  deactivate

  if [ $result -ne 0 ]; then
    echo "Metadata check failure" >&2
    exit 1
  fi
  echo "Metadata check completed"

  if $quick_tests_enabled; then
    $SCRIPTS_DIR/install_test.sh $package_file_path
  fi

  # Stage the release bundle and create a tarball of it in the dist directory,
  # then clean up the standalone sdist package.
  create_release_bundle "$RELEASE_BUILD_DIR" "$version" "$package_file_path"
  cleanup_standalone_sdist "$package_file_path"
}

function run_python_code() {
  local line_no="$1"
  local py_code="$2"
  local ret_code=0
  output=$($PY_COMMAND -c "$py_code") || ret_code=$?
  if [ $ret_code -ne 0 ]; then
    echo "Error running Python code at line $line_no ($ret_code)" >&2
    exit 1
  fi
  echo "$output"
}

function make_binaries() {
  local target="$1"
  local py_get_bench_data="import json; bms = json.load(open('$UBENCH_CONFIG', 'r'))['benchmarks']"
  local dietperf_dir=$(realpath extern/dietperf)
  local benchmarks

  # build the binaries and copy them to the develop virtual env/bin
  benchmarks=$(run_python_code $LINENO "$py_get_bench_data; names = bms.keys(); \
    print(' '.join(names))")
  for name in $benchmarks; do
    local bin_names
    local dir_name

    bin_names=$(run_python_code $LINENO "$py_get_bench_data; \
      names = [n for n in bms['$name'].keys() if n != 'folder']; print(' '.join(names))")
    dir_name=$(run_python_code $LINENO "$py_get_bench_data; print(bms['$name']['folder'])")
    for entry_name in $bin_names; do
      local bin_info

      pushd $dir_name
      echo -- Building $name:$entry_name --

      bin_info=$(run_python_code $LINENO "$py_get_bench_data; entry=bms['$name']['$entry_name']; \
        print('{}:{}:{}'.format(entry['cflags'], entry['ldflags'], entry['binary']))")

      IFS=":" read -r -a bin_info_arr <<< "$bin_info"
      exec_name="${bin_info_arr[2]}"

      make EXE="$exec_name" clean

      if [ "$target" = "clean" ]; then
        popd
        continue
      fi

      DIETPERF_DIR=$dietperf_dir make CFLAGS="${bin_info_arr[0]}" LDFLAGS="${bin_info_arr[1]}" EXE="$exec_name" $target

      rm -f $DEVELOP_VENV_DIR/bin/$exec_name
      ln -s $(pwd)/$exec_name $DEVELOP_VENV_DIR/bin/$exec_name
      popd
    done
  done
}

function build_binaries() {
  make_binaries ""
}

function clean_binaries() {
  make_binaries clean
}

function update_tags() {
  local build_mode=$1
  case $build_mode in
    release)
      if [ "$VERSION_TAG" != "" ]; then
        export ASCT_VERSION_TAG=$VERSION_TAG
      fi
      if [ "$BUILD_TAG" != "" ]; then
        export ASCT_BUILD_TAG=$BUILD_TAG
      fi
    ;;
    devel|activate)
      if [ "$BUILD_TAG" = "" ]; then
        BUILD_TAG="editable"
      fi
      export ASCT_VERSION_TAG=$VERSION_TAG
      export ASCT_BUILD_TAG=$BUILD_TAG
    ;;
  esac
}

function build_devel() {
  create_and_source_venv $DEVELOP_VENV_DIR true
  $PIP_COMMAND install -e .
  $PIP_COMMAND install -r requirements_dev.txt
  deactivate

  build_binaries

  rm -f $DEVELOP_VENV_DIR/bin/asct
  ln -s $(pwd)/src/asct $DEVELOP_VENV_DIR/bin/asct
}

function build_test() {
  local test_params="$1"

  rm -rf $TEST_WORK_DIR
  mkdir -p $TEST_WORK_DIR

  if [ ! -d $DEVELOP_VENV_DIR ]; then
    echo "Warning: Development virtual env not found, creating ..."
    build_devel
  fi

  sudo_param=""
  if [ $(id -u) -ne 0 ] && [ ${TEST_DISABLE_SUDO:-0} -ne 1 ]; then
    sudo_param=sudo
  fi

  $sudo_param $SHELL -c "source $DEVELOP_VENV_DIR/bin/activate ; LD_LIBRARY_PATH=${LD_LIBRARY_PATH:-} \
    python -m pytest --cov --cov-report term $test_params --work-dir $TEST_WORK_DIR"
}

function build_activate() {
  if [ ! -z ${VIRTUAL_ENV+x} ] && [ "$VIRTUAL_ENV" == "$DEVELOP_VENV_DIR" ]; then
    echo "Warning: the development virtual env is already active, ignoring command!"
    return
  fi

  if [ ! -d $DEVELOP_VENV_DIR ]; then
    echo "Warning: Development virtual env not found, creating ..."
    build_devel
  fi

  if [ "$BASH_VERSINFO" != "" ]; then
    local tmp_init_file=$(mktemp)
    echo "source $DEVELOP_VENV_DIR/bin/activate" > $tmp_init_file
    exec sudo /usr/bin/env bash --init-file $tmp_init_file
  else
    exec sudo $SHELL -c "source $DEVELOP_VENV_DIR/bin/activate ; exec $SHELL"
  fi
}

function clean() {
  if [ ! -z ${VIRTUAL_ENV+x} ] && [ "$VIRTUAL_ENV" == "$DEVELOP_VENV_DIR" ]; then
    echo "Error: the development virtual env is active, please deactivate it first!"
    exit 1
  fi

  rm -rf $RELEASE_BUILD_DIR $DEVELOP_BUILD_DIR build asct.egg-info src/asct.egg-info
  find . -name '*.so' -delete
  clean_binaries
}

enable_quick_test=false
test_params=""
test_cov_file=""
build_mode=release

while [[ $# -gt 0 ]]; do
  case $1 in
    -t|--quick-test)
      enable_quick_test=true
      shift
    ;;
    --test-params)
      test_params="$2"
      shift; shift
    ;;
    --version-tag)
      if [[ -z "${2:-}" ]]; then
        echo "❌ Error: --version-tag requires an argument" >&2
        print_help_and_exit 1
      fi
      VERSION_TAG="$2"
      shift 2
    ;;
    --build-tag)
      if [[ -z "${2:-}" ]]; then
        echo "❌ Error: --build-tag requires an argument" >&2
        print_help_and_exit 1
      fi
      BUILD_TAG="$2"
      shift 2
    ;;
    activate|devel|release|bin|test|clean)
      build_mode=$1
      shift
    ;;
    -h|--help)
      print_help_and_exit 0
    ;;
    *)
      print_help_and_exit 1
    ;;
  esac
done

echo "> ASCT: $build_mode <"

update_tags $build_mode

case $build_mode in
  activate)
    build_activate
  ;;
  release)
    build_release $enable_quick_test
  ;;
  devel)
    build_devel
  ;;
  bin)
    build_binaries
  ;;
  test)
    build_test "$test_params"
  ;;
  clean)
    clean
  ;;
esac
