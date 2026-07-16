#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# Helper functions to be used by release.sh. split out for more interractive development and debug

# See Development.md for details on the release process, including branching strategy and CI integration
# In short, this script shall:
#   1a. Create a new branch from main like `release/0.3` or `release/1.0` for a minor or major update,
#   1b. OR check out an existing given release branch in the case of a patch update
#   2.  update VERSION with the release version
#   3.  Create a new `release-candidate/0.3.0` or `release-candidate/1.0.0` for a minor or major update,
#   3b. OR create `release-candidate/0.2.1` for a patch
#   4.  Create a `release-candidate` tagged  pull request with a changelog description

SCRIPT_DIR="$(dirname -- "$(realpath -- "${BASH_SOURCE[0]}")")"

# --- Configuration ---
VERSION_FILE="$SCRIPT_DIR/../VERSION"
RELEASE_NOTES_OUTPUT_FILE="$SCRIPT_DIR/../tmp/release-notes.txt"
PYPROJECT_FILE="$SCRIPT_DIR/../pyproject.toml"

# --- Helper Functions ---

function usage() {
  echo "Usage: $0 [major | minor | patch <major.minor>]"
  exit 1
}

function show_releases() {
  git fetch --all --tags --prune

  echo $'\n'"-- Release Branches"
  git branch -r --list 'origin/release/*' \
    | sed 's|.*/release/||'

  echo $'\n'"-- Releases"
  git tag | grep -E "^v[0-9]+\.[0-9]+\.[0-9]$" || true

  echo $'\n'"-- Release Candidates"
  git branch -r --list 'origin/release-candidate/*'

  echo $'\n'"-- Branches to increment VERSION after a release (should be short-lived)"
  git branch -r --list 'increment-version*'

 
  echo $'\n'
}

function get_pyproject_version() {
  if [[ -f $VERSION_FILE ]]; then
    cat "$VERSION_FILE"
  else
    # legacy support for patching releases where version was directly in pyproject.toml 
    grep -m1 '^version' "$PYPROJECT_FILE" | cut -d '"' -f2
  fi

}

function update_pyproject_version() {
  local new_version="$1"
  if [[ -f $VERSION_FILE ]]; then
    echo "$new_version" > "$VERSION_FILE"
  else
    # legacy support for patching releases where version was directly in pyproject.toml
    echo "🔧 Updating pyproject.toml version to $new_version..."
    sed -i.bak -E "s/^version *= *\"[^\"]+\"/version = \"$new_version\"/" "$PYPROJECT_FILE"
    rm -f "${PYPROJECT_FILE}.bak"
  fi
}

# get the name of the current latest release tag,
# including 'v' prefix and patch.
# e.g. `v0.2.0`
# param 1: base branch, e.g. release/0.2
function get_latest_git_tag() {
  local base_branch="$1"
  git fetch origin "$base_branch" --quiet --tags || true
  git tag --merged "origin/$base_branch" -- list 'v[0-9]*.[0-9]*.[0-9]*' \
    | sort -V \
    | tail -n1
}

# get the name of the current latest minor release, sans patch.
# e.g. `0.2`
function get_latest_release() {
  git fetch origin   # make sure branch list is current

  git branch -r --list 'origin/release/*' \
    | sed 's|.*/release/||' \
    | sort -V \
    | tail -n1
}


function version_to_numbers() {
  echo "$1" | sed -E 's/^v?//'  # strip leading "v"
}

function bump_version() {
  local v="$1"
  local part="$2"
  IFS='.' read -r major minor patch <<< "$(version_to_numbers "$v")"
  case $part in
    major) echo "$((major + 1)).0.0" ;;
    minor) echo "$major.$((minor + 1)).0" ;;
    patch) echo "$major.$minor.$((patch + 1))" ;;
    *)     echo "Invalid bump part: $part" && exit 1 ;;
  esac
}

# create a release notes as a file to use as commit message.
# will collect git log diffs since the last minor release
# args:
# 1. version - release version number, (e.g. 0.3.0)
# example uses:
#   version==0.3.0 will diff against 0.2.0
#   version==1.0.0 will diff against 0.2.0
#   version==0.3.1 will diff against 0.3.0
#
function create_release_notes() {
  if [[ $# -ne 2 ]]; then
    echo "usage create_release_notes release/<CURRENT_MAJOR.CURRENT_MINOR> <MAJOR.MINOR.PATCH>" >&2
    return 2
  fi
  local current_release="$1"
  local version="$2"

  # Basic SemVer branch parse: release/MAJOR.MINOR
  if [[ ! "$current_release" =~ ^([0-9]+)\.([0-9]+)$ ]]; then
    echo "error: release branch must be MAJOR.MINOR (e.g., 1.2) not '$current_release'" >&2
    return 2
  fi
  local CURRENT_MAJOR="${BASH_REMATCH[1]}"
  local CURRENT_MINOR="${BASH_REMATCH[2]}"
  
  # Basic SemVer parse: MAJOR.MINOR.PATCH (numbers only)
  if [[ ! "$version" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
    echo "error: version must be MAJOR.MINOR.PATCH (e.g., 1.2.3)" >&2
    return 2
  fi
  local MAJOR="${BASH_REMATCH[1]}"
  local MINOR="${BASH_REMATCH[2]}"
  local PATCH="${BASH_REMATCH[3]}"

  # Make sure we have up-to-date tags/branches
  git fetch --tags --quiet || true
  git fetch origin --quiet || true

  local lower_ref range

  if [[ "$PATCH" == "0" ]]; then
    # Minor release (e.g., 1.1.0): compare from previous release branch release/1.0
    if git rev-parse -q --verify "refs/remotes/origin/release/${CURRENT_MAJOR}.${CURRENT_MINOR}" >/dev/null; then
      lower_ref="origin/release/${CURRENT_MAJOR}.${CURRENT_MINOR}"
    else
      echo "error: could not find remote branch release/${CURRENT_MAJOR}.${CURRENT_MINOR}" >&2
      return 4
    fi

    # Use merge-base so we count commits since the point we diverged from that line
    base=$(git merge-base HEAD "$lower_ref") || {
      echo "error: git merge-base failed against $lower_ref" >&2
      return 5
    }
    range="${base}..HEAD"
  else
    # Patch release (e.g., 0.3.1): compare from previous tag (v0.3.0)
    local prev_patch=$((PATCH - 1))
    local prev_tag="refs/tags/v${MAJOR}.${MINOR}.${prev_patch}"

    if git rev-parse -q --verify "$prev_tag" >/dev/null; then
      lower_ref="v${MAJOR}.${MINOR}.${prev_patch}"
    else
      echo "error: previous tag not found: ${MAJOR}.${MINOR}.${prev_patch}" >&2
      return 6
    fi

    range="${lower_ref}..HEAD"
  fi

  echo "range: $range"
  mkdir -p "$(dirname "$RELEASE_NOTES_OUTPUT_FILE")"
  git log --pretty=format:'- %s (%h)' --no-merges "$range" > "$RELEASE_NOTES_OUTPUT_FILE"
}

function tag_exists() {
  git rev-parse "$1" >/dev/null 2>&1
}
