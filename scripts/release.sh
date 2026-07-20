#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# See Development.md for details on the release process, including branching strategy and CI integration
# In short, this script shall:
#   1a. Create a new branch from main like `release/0.3` or `release/1.0` for a minor or major update,
#   1b. OR check out an existing given release branch in the case of a patch update
#   2.  update VERSION with the release version
#   3.  Create a new `release-candidate/0.3.0` or `release-candidate/1.0.0` for a minor or major update,
#   3b. OR create `release-candidate/0.2.1` for a patch
#   4.  Create a `release-candidate` tagged  pull request with a changelog description


# See Development.md for details on the release process, including branching strategy and CI integration
# In short, this script shall:
#   1a. Create a new branch from main like `release/0.3` or `release/1.0` for a minor or major update,
#   1b. OR check out an existing given release branch in the case of a patch update
#   2.  update VERSION with the release version
#   3.  Create a new `release-candidate/0.3.0` or `release-candidate/1.0.0` for a minor or major update,
#   3b. OR create `release-candidate/0.2.1` for a patch
#   4.  Create a `release-candidate` tagged  pull request with a changelog description

set -euo pipefail

SCRIPT_DIR="$(dirname -- "$(realpath -- "${BASH_SOURCE[0]}")")"

# check dependencies
command -v git >/dev/null 2>&1 || { echo "Error: git is required."; exit 1; }
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "This is not a git repository."; exit 1; }
command -v gh >/dev/null 2>&1 || { echo "Error: gh (GitHub CLI) is required."; exit 1; }
if ! gh auth status &>/dev/null; then
  echo "Please log in to GitHub CLI with \`gh auth login\` and try again."
  exit 1
fi

# ensure we're on a clean checkout of main before starting, to avoid accidentally including uncommitted changes
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "❌ Please commit or stash your changes before running this script. (Untracked files are OK)" > /dev/stderr
  exit 1
fi

# ensure we're on `main` branch before starting, to avoid accidentally branching off from the wrong place.
# We will return to the original branch at the end of the script.
ORIGINAL_BRANCH="$(git symbolic-ref --short -q HEAD 2>/dev/null || true)"
if [[ "$ORIGINAL_BRANCH" != "main" ]]; then
  echo "❌ Please run this script from the 'main' branch. Currently on: $ORIGINAL_BRANCH" > /dev/stderr
  exit 1
fi
ORIGINAL_COMMIT="$(git rev-parse HEAD)"

# Always return to the original commit on exit, even if the script fails
restore_original_head() {
  if [[ -n "${ORIGINAL_BRANCH:-}" ]]; then
    git checkout "$ORIGINAL_BRANCH" --quiet 2>/dev/null || true
  else
    git checkout --detach "$ORIGINAL_COMMIT" --quiet 2>/dev/null || true
  fi
}
trap 'restore_original_head' EXIT

# define helper functions for version parsing, changelog generation, etc.
source "$SCRIPT_DIR/helpers_release.sh"

# --- Parse Arguments ---

BUMP_TYPE=""  # 'major' | 'minor' | 'patch'
RELEASE_TO_PATCH=""

if [[ $# -eq 0 ]]; then
  BUMP_TYPE="minor"
else
  # look at the given argument - it should be one of major, minor, patch
  # that will set either BUMP_TYPE to major, minor, or patch
  # if either is set twice, or both are set, that's a usage error.
  # if neither is set, default to minor
  case $1 in
    major|minor|patch)
      if [[ -n "$BUMP_TYPE" ]]; then
        echo "❌ Error: Only one of major, minor, patch can be used." > /dev/stderr
        usage
      fi
      BUMP_TYPE="$1"
      ;;
    show)
      show_releases
      exit 0
      ;;
    *)
      echo "❌ Unknown argument: $1" > /dev/stderr
      usage
      ;;
  esac
fi

# --- Get Versions ---

CURRENT_MINOR_RELEASE=$(get_latest_release)
if [[ "$BUMP_TYPE" == "patch" ]]; then
  if [[ $# -lt 2 ]]; then
    usage
  fi
  RELEASE_TO_PATCH="$2"
  if [[ ! "$RELEASE_TO_PATCH" =~ ^([0-9]+)\.([0-9]+)$ ]]; then
    echo "❌ error: release branch to patch must be MAJOR.MINOR (e.g., 1.2) not '$RELEASE_TO_PATCH'" >&2
    exit 1
  fi
  CURRENT_MINOR_RELEASE="${RELEASE_TO_PATCH}"
  echo "Patching release/$CURRENT_MINOR_RELEASE"
fi

CURRENT_TAG=$(get_latest_git_tag "release/$CURRENT_MINOR_RELEASE")
if [[ "$BUMP_TYPE" != "patch" ]]; then
  # for major/minor releases, we want to compare against the latest x.y.0 tag,
  # not whatever the latest patch on that other branch is
  CURRENT_TAG="v${CURRENT_MINOR_RELEASE}.0"
fi
CURRENT_VERSION=$(version_to_numbers "$CURRENT_TAG")
CURRENT_PYPROJ_VERSION=$(get_pyproject_version)

# --- Determine new version ---
NEW_VERSION="$(bump_version "$CURRENT_VERSION" "$BUMP_TYPE")"
echo "Auto-bumped version: $NEW_VERSION"

TAG_NAME="v$NEW_VERSION"
RELEASE_BRANCH="release/${NEW_VERSION%.*}"  # drop the last '.'  and everything after it
RELEASE_CANDIDATE_BRANCH="release-candidate/${NEW_VERSION}" # include full version: release/1.2.3

#echo "Latest tag: $CURRENT_TAG"
#echo "Version in VERSION file: $CURRENT_PYPROJ_VERSION"
#echo "CURRENT_MINOR_RELEASE: $CURRENT_MINOR_RELEASE"
#echo "NEW_VERSION: $NEW_VERSION"
#echo "TAG_NAME: $TAG_NAME"
#echo "RELEASE_BRANCH: $RELEASE_BRANCH"
#echo "RELEASE_CANDIDATE_BRANCH: $RELEASE_CANDIDATE_BRANCH"
#exit 0


# --- Confirm tag doesn't exist ---

if tag_exists "$TAG_NAME"; then
  echo "❌ Tag $TAG_NAME already exists. Aborting." > /dev/stderr
  exit 1
fi

# --- Fetch remote release branches ---
git fetch --all --prune --quiet

# --- Check out (and create, if necessary) base release branch
if [[ "$BUMP_TYPE" == "patch" ]]; then
  # --- Check out release branch if creating a patch PR ---
  if [[ "$RELEASE_TO_PATCH" == "" ]]; then
    usage
  fi
  RELEASE_BRANCH="release/$RELEASE_TO_PATCH"
  echo "✅ Checking out existing release branch to patch: $RELEASE_BRANCH"
  git checkout "$RELEASE_BRANCH" --quiet
else
  # --- Create and checkout branch for minor/major releases ---
  if git ls-remote --exit-code --heads origin "$RELEASE_BRANCH" &>/dev/null; then
    echo "❌ Branch '$RELEASE_BRANCH' already exists on remote. You probably wanted to run scripts/release.sh patch <major.minor>"
    exit 1
  else
    echo "✅ Creating new release branch: $RELEASE_BRANCH"
    git switch -c "$RELEASE_BRANCH" --quiet
    git push origin "$RELEASE_BRANCH"
  fi
fi

# --- Update VERSION file
if [[ "$CURRENT_PYPROJ_VERSION" != "$NEW_VERSION" ]]; then
  echo "✅ Ready to set project version to: $NEW_VERSION"
  read -p "Proceed? [y/N] " CONFIRM
  [[ "$CONFIRM" =~ ^[Yy][eE]?[sS]?$ ]] || exit 1
  update_pyproject_version "$NEW_VERSION"
fi


# --- Create release candidate pull request on release branch ---
git switch -c "$RELEASE_CANDIDATE_BRANCH" --quiet

# --- Stage and commit changes ---
if ! git diff --quiet || ! git diff --cached --quiet; then
  git add -A
  create_release_notes "$CURRENT_MINOR_RELEASE" "$NEW_VERSION"  # creates tmp/release-notes.txt
  echo "created release notes for $CURRENT_MINOR_RELEASE -> $NEW_VERSION. $(cat tmp/release-notes.txt | wc -l) commits."
  git commit -m $'Release '"$TAG_NAME"$'\n\n'"$(cat tmp/release-notes.txt)" --quiet
else
  echo "No changes to commit."
fi

# --- Push to remote ---
git push -u origin "$RELEASE_CANDIDATE_BRANCH"  --quiet --no-progress >/dev/null 2>&1

# --- Create GitHub Pull Request ---

# --- Create release notes for pull request body
# It includes the version number, date, and a changelog section.
# All commits are lumped under "Miscellaneous" until a human release engineer edits it.
# Also includes a link to the full changelog, and badges to trigger the Artifactory publishing workflows
# placeholder tags like <!-- REPLACE_WITH_INTERNAL_RELEASE_URL --> are to be replaced by the publishing workflows
cat > tmp/pr_body.txt <<EOF
## [$NEW_VERSION] - $(date +%Y-%m-%d)

### Features

### Bug Fixes

### Improvements

### Performance

### Miscellaneous

$(cat tmp/release-notes.txt)

Full Changelog: https://github.com/Arm-Debug/asct/compare/$CURRENT_TAG...$TAG_NAME

EOF

# --- Create release-candidate pull request
gh pr create --title "[Release] $TAG_NAME" \
              --body-file tmp/pr_body.txt \
              --base "$RELEASE_BRANCH" \
              --head "$RELEASE_CANDIDATE_BRANCH" \
              --label "release-candidate"
echo ""
