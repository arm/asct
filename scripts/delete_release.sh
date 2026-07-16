#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# This script deletes a specified release version - handy for cleaning up mistaken releases,
# especially during testing of the release process
# TODO: delete associated Artifactory entries if they exist

set -euo pipefail

usage() {
  echo "Usage: $0 <version>"
  echo "  version: vX.Y.Z or X.Y.Z (e.g., v0.1.2 or 0.1.2)"
  exit 1
}

command -v gh >/dev/null 2>&1 || { echo "Error: gh (GitHub CLI) is required."; exit 1; }
command -v git >/dev/null 2>&1 || { echo "Error: git is required."; exit 1; }
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "This is not a git repository."; exit 1; }

confirm() {
  local msg="${1:-Proceed?}"
  read -r -p "$msg [y/N] " ans
  ans="$(printf '%s' "$ans" | tr '[:upper:]' '[:lower:]')"
  case "$ans" in
    y|yes) return 0 ;;
    *)     return 1 ;;
  esac
}

[[ $# -eq 1 ]] || usage

INPUT="$1"                # 0.1.2 or 0.1.2
VER="${INPUT#v}"          # 0.1.1
TAG="v${VER}"             # v0.1.1
MAJOR="${VER%%.*}"        # 0
REST="${VER#*.}"          # 1.1
MINOR="${REST%%.*}"       # 1
PATCH="${REST##*.}"       # 1

RC_BRANCH="release-candidate/${VER}"
REL_BRANCH="release/${MAJOR}.${MINOR}"
INC_VERSION_BRANCH="increment-version/${VER}.post"

echo "Repository: $(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null || echo '<detected by git remote>')"
echo "Tag:        ${TAG}"
echo "RC branch:  ${RC_BRANCH}"
echo "Rel branch: ${REL_BRANCH}"
echo

# Check if the GitHub Release exists
IS_GH_RELEASE_FOUND=false
if release_url="$(gh release view "${TAG}" --json url --jq .url 2>/dev/null)"; then
  IS_GH_RELEASE_FOUND=true
else
  echo "No GitHub Release found for ${TAG} (ok, continuing)."
fi
# Check if the tag exists locally or remotely
IS_LOCAL_TAG_FOUND=false
if git rev-parse -q --verify "refs/tags/${TAG}" >/dev/null; then
  IS_LOCAL_TAG_FOUND=true
else
  echo "No local git tag found for ${TAG} (ok, continuing)."
fi
IS_REMOTE_TAG_FOUND=false
if git ls-remote --tags origin "refs/tags/${TAG}" | grep -q .; then
  IS_REMOTE_TAG_FOUND=true
else
  echo "No remote git tag found for ${TAG} (ok, continuing)."
fi
# check for open release-candidate/X.Y.Z PRs
prs=()
# look up all the release-candidate/X.Y.Z PRs
while IFS=$'\t' read -r num url; do
  prs+=("$num"$'\t'"$url")
done < <(gh pr list --head "${RC_BRANCH}" --state open --json number,url \
        --jq '.[] | "\(.number)\t\(.url)"' 2>/dev/null || true)
# and append any increment-version/X.Y.Z.post PRs
while IFS=$'\t' read -r num url; do
  prs+=("$num"$'\t'"$url")
done < <(gh pr list --head "increment-version/${VER}.post" --state open --json number,url \
        --jq '.[] | "\(.number)\t\(.url)"' 2>/dev/null || true)

# --- Delete release-candidate/X.Y.Z branches and increment-version/X.Y.Z.post branches locally & remotely (with confirmation)
IS_LOCAL_RC_BRANCH_FOUND=false
if git show-ref --verify --quiet "refs/heads/${RC_BRANCH}"; then
  IS_LOCAL_RC_BRANCH_FOUND=true
fi
IS_REMOTE_RC_BRANCH_FOUND=false
if git ls-remote --heads origin "${RC_BRANCH}" | grep -q .; then
  IS_REMOTE_RC_BRANCH_FOUND=true
fi
IS_LOCAL_INC_VERSION_BRANCH_FOUND=false
if git show-ref --verify --quiet "refs/heads/${INC_VERSION_BRANCH}"; then
  IS_LOCAL_INC_VERSION_BRANCH_FOUND=true
fi
IS_REMOTE_INC_VERSION_BRANCH_FOUND=false
if git ls-remote --heads origin "${INC_VERSION_BRANCH}" | grep -q .; then
  IS_REMOTE_INC_VERSION_BRANCH_FOUND=true
fi
# --- If tag is *. *.0, offer to delete release/X.Y branch locally & remotely
SHOULD_DELETE_LOCAL_RELEASE_BRANCH=false
SHOULD_DELETE_REMOTE_RELEASE_BRANCH=false
if [[ "${PATCH}" == "0" ]]; then
  # Local
  if git show-ref --verify --quiet "refs/heads/${REL_BRANCH}"; then
    SHOULD_DELETE_LOCAL_RELEASE_BRANCH=true
  fi
  # Remote
  if git ls-remote --heads origin "${REL_BRANCH}" | grep -q .; then
    SHOULD_DELETE_REMOTE_RELEASE_BRANCH=true
  fi
fi



# --- print the summary of actions to be taken and get confirmation
echo "The following actions will be taken delete the release ${TAG}:"
if $IS_GH_RELEASE_FOUND; then
  echo "  gh release delete ${TAG} -y  # delete ${release_url}"
fi
if $IS_LOCAL_TAG_FOUND; then
  echo "  git tag -d ${TAG}"
fi
if $IS_REMOTE_TAG_FOUND; then
  echo "  git push origin \":refs/tags/${TAG}\""
fi
# print the PRs out to  close
if (( ${#prs[@]} > 0 )); then
  for line in "${prs[@]}"; do
    num="${line%%$'\t'*}"
    echo "  gh pr close \"${num}\" --comment \"Closing due to cleanup of ${RC_BRANCH} and tag ${TAG}.\""
  done
else
  echo "No open release-candidate or increment-version PRs found ${VER}."
fi
if $IS_LOCAL_RC_BRANCH_FOUND; then
  echo "  git branch -D \"${RC_BRANCH}\""
fi
if $IS_REMOTE_RC_BRANCH_FOUND; then
  echo "  git push origin --delete \"${RC_BRANCH}\" --force"
fi
if $IS_LOCAL_INC_VERSION_BRANCH_FOUND; then
  echo "  git branch -D \"${INC_VERSION_BRANCH}\""
fi
if $IS_REMOTE_INC_VERSION_BRANCH_FOUND; then
  echo "  git push origin --delete \"${INC_VERSION_BRANCH}\""
fi
if $SHOULD_DELETE_LOCAL_RELEASE_BRANCH; then
  echo "  git branch -D \"${REL_BRANCH}\""
fi
if $SHOULD_DELETE_REMOTE_RELEASE_BRANCH; then
  echo "  git push origin --delete \"${REL_BRANCH}\" --force"
fi 

# --- Confirm choice then proceed
if confirm "Continue?"; then
  if $IS_GH_RELEASE_FOUND; then
    gh release delete "${TAG}" -y
  fi
  if $IS_LOCAL_TAG_FOUND; then
    git tag -d "${TAG}"
  fi
  if $IS_REMOTE_TAG_FOUND; then
    git push origin ":refs/tags/${TAG}"
  fi
  # close the related release-candidate and increment-version PRs
  if (( ${#prs[@]} > 0 )); then
    for line in "${prs[@]}"; do
      num="${line%%$'\t'*}"
      gh pr close "${num}" --comment "Closing due to cleanup of ${RC_BRANCH} and tag ${TAG}."
    done
  fi
  # delete PR branches
  if $IS_LOCAL_RC_BRANCH_FOUND; then
    git branch -D "${RC_BRANCH}"
  fi
  if $IS_REMOTE_RC_BRANCH_FOUND; then
    git push origin --delete "${RC_BRANCH}"
  fi
  if $IS_LOCAL_INC_VERSION_BRANCH_FOUND; then
    git branch -D "${INC_VERSION_BRANCH}"
  fi
  if $IS_REMOTE_INC_VERSION_BRANCH_FOUND; then
    git push origin --delete "${INC_VERSION_BRANCH}"
  fi
  if $SHOULD_DELETE_LOCAL_RELEASE_BRANCH; then
    git branch -D "${REL_BRANCH}"
  fi
  if $SHOULD_DELETE_REMOTE_RELEASE_BRANCH; then
    # must force because release branches are typically protected in remote repo settings
    git push origin --delete "${REL_BRANCH}"
  fi 

  echo

  echo "Be sure to clean up any Artifactory entries manually if needed."
  echo "Check:"
  echo "  https://artifactory.internal.tools.arm.com/artifactory/asct/dist/${VER}/"
  echo "  https://artifactory.internal.tools.arm.com/artifactory/asct-local/dist/${VER}/"
  echo "  https://arm.jfrog.io/ui/repos/tree/General/its-asct/dist/${VER}/"

else
  echo "Cancelled"
fi
