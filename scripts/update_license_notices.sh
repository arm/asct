#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

### This script updates the THIRD-PARTY-LICENSES file with the latest notices from Black Duck for the current version.
### It will create a new version in Black Duck if it doesn't exist, and generate a new
### Notices report if needed.

#  export ITS_BLACKDUCK_KEY=<your_blackduck_api_token>
#  scripts/update_license_notices.sh --version-name X.Y.Z
 

### If this script isn't working, or needs to be updated, here is the manual flow that it's replacing
# Update Third-Party License file and perform BlackDuck scan
# 1. Create a new numbered release here: https://arm.app.blackduck.com/api/projects/396f0593-8024-45a6-9d84-0c237e65c66f/versions
# 1. Run the [BlackDuck](https://github.com/Arm-Debug/asct/actions/workflows/blackduck.yaml) workflow - select the branch of the release candidate
# 1. Once the scan is uploaded, on the release candidate's version, on the Reports tab, Create New Report, and select 'Notices File'. Select Plain Text output and check the boxes for Subprojects, License Data and License Text.
# 1. Download the plain text and use it to replace THIRD-PARTY-LICENSES in the `release-candidate/X.Y.Z` branch.

set -euo pipefail

BASE_URL="https://arm.app.blackduck.com"
PROJECT_ID="396f0593-8024-45a6-9d84-0c237e65c66f"
VERSION_NAME=""
API_TOKEN=""
OUTPUT_DIR="."
OUTPUT_FILE=""
OUTPUT_FILE_WAS_SET=0
DOWNLOAD_ZIP_PATH=""
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
POLL_INTERVAL_SECONDS=15
WAIT_TIMEOUT_SECONDS=1800
VERSION_PHASE="PLANNING"
VERSION_DISTRIBUTION="EXTERNAL"

TMP_DIR=""
BEARER_TOKEN=""
HTTP_CODE=""
HTTP_BODY_FILE=""
HTTP_HEADERS_FILE=""
VERSION_HREF=""
VERSION_ID=""
REPORT_STATUS_URL=""

usage() {
  cat <<'EOF'
Usage: scripts/update_license_notices.sh [options]

Create/reuse a Black Duck project version, create/reuse a Notices File report,
and download it when ready.

Options:
  --version-name <X.Y.Z>        Project version to manage.
                                Default: read from ./VERSION
  --api-token <token>           Black Duck API token.
                                Default: ITS_BLACKDUCK_KEY or BLACKDUCK_API_TOKEN env var
  --base-url <url>              Black Duck URL (default: https://arm.app.blackduck.com)
  --project-id <uuid>           Black Duck project UUID
                                (default: 396f0593-8024-45a6-9d84-0c237e65c66f)
  --output-dir <dir>            Output folder for downloaded report (default: .)
  --output-file <file>          Output path for extracted notices text
                                (default: <repo-root>/THIRD-PARTY-LICENSES)
  --phase <PHASE>               Version phase when creating a new version (default: PLANNING)
  --distribution <TYPE>         Version distribution when creating a new version (default: EXTERNAL)
  -h, --help                    Show this help

Examples:
  export ITS_BLACKDUCK_KEY="..."
  scripts/update_license_notices.sh --version-name "$(head -1 VERSION)"

  scripts/update_license_notices.sh \
    --api-token "$ITS_BLACKDUCK_KEY" \
    --version-name 1.2.3 \
    --output-file tmp/THIRD-PARTY-LICENSES-1.2.3.txt
EOF
}

log() {
  echo "[update-license-notices] $*"
}

die() {
  echo "[update-license-notices] ERROR: $*" >&2
  exit 1
}

cleanup() {
  if [[ -n "${TMP_DIR}" && -d "${TMP_DIR}" ]]; then
    rm -rf "${TMP_DIR}"
  fi
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

to_abs_url() {
  local maybe_url="$1"
  if [[ -z "$maybe_url" ]]; then
    echo ""
  elif [[ "$maybe_url" =~ ^https?:// ]]; then
    echo "$maybe_url"
  else
    echo "${BASE_URL%/}${maybe_url}"
  fi
}

http_request() {
  local method="$1"
  local url="$2"
  local body="${3:-}"
  local accept="${4:-application/json}"
  local content_type="${5:-application/json}"

  HTTP_HEADERS_FILE="$(mktemp "$TMP_DIR/headers.XXXXXX")"
  HTTP_BODY_FILE="$(mktemp "$TMP_DIR/body.XXXXXX")"

  local curl_args=(
    -sS
    -X "$method"
    -D "$HTTP_HEADERS_FILE"
    -o "$HTTP_BODY_FILE"
    -H "Accept: ${accept}"
    -H "Authorization: Bearer ${BEARER_TOKEN}"
  )

  if [[ -n "$body" && "$method" != "GET" ]]; then
    curl_args+=(
      -H "Content-Type: ${content_type}"
      --data "$body"
    )
  fi

  HTTP_CODE="$(curl "${curl_args[@]}" "$url" -w "%{http_code}")"
}

authenticate() {
  local auth_headers auth_body auth_code
  auth_headers="$(mktemp "$TMP_DIR/auth_headers.XXXXXX")"
  auth_body="$(mktemp "$TMP_DIR/auth_body.XXXXXX")"

  local curl_args=(
    -sS
    -X POST
    -D "$auth_headers"
    -o "$auth_body"
    -H "Accept: application/json"
    -H "Authorization: token ${API_TOKEN}"
  )

  auth_code="$(curl "${curl_args[@]}" "${BASE_URL%/}/api/tokens/authenticate" -w "%{http_code}")"
  if [[ "$auth_code" != "200" ]]; then
    die "Black Duck authentication failed (HTTP ${auth_code}): $(cat "$auth_body")"
  fi

  BEARER_TOKEN="$(jq -r '.bearerToken // empty' "$auth_body")"
  if [[ -z "$BEARER_TOKEN" ]]; then
    die "Could not extract bearerToken from authentication response"
  fi
}

fetch_version() {
  local q_enc versions_url
  q_enc="$(jq -nr --arg q "versionName:${VERSION_NAME}" '$q|@uri')"
  versions_url="${BASE_URL%/}/api/projects/${PROJECT_ID}/versions?q=${q_enc}&limit=200"

  http_request "GET" "$versions_url" "" "application/vnd.blackducksoftware.project-detail-4+json"
  if [[ "$HTTP_CODE" != "200" ]]; then
    die "Failed to query project versions (HTTP ${HTTP_CODE}): $(cat "$HTTP_BODY_FILE")"
  fi

  local version_obj
  version_obj="$(jq -c --arg v "$VERSION_NAME" '.items[]? | select(.versionName == $v)' "$HTTP_BODY_FILE" | head -n 1)"
  if [[ -z "$version_obj" ]]; then
    return 1
  fi

  VERSION_HREF="$(echo "$version_obj" | jq -r '._meta.href // empty')"
  VERSION_HREF="$(to_abs_url "$VERSION_HREF")"
  VERSION_ID="${VERSION_HREF##*/}"

  if [[ -z "$VERSION_ID" || -z "$VERSION_HREF" ]]; then
    die "Failed to resolve version href/id from API response"
  fi

  return 0
}

create_version_if_missing() {
  if fetch_version; then
    log "Version '${VERSION_NAME}' already exists: ${VERSION_HREF}"
    return 0
  fi

  local payload create_url
  payload="$(jq -cn --arg versionName "$VERSION_NAME" --arg phase "$VERSION_PHASE" --arg distribution "$VERSION_DISTRIBUTION" '{versionName:$versionName, phase:$phase, distribution:$distribution}')"
  create_url="${BASE_URL%/}/api/projects/${PROJECT_ID}/versions"

  log "Creating version '${VERSION_NAME}' in project '${PROJECT_ID}'"
  http_request "POST" "$create_url" "$payload" "application/json" "application/json"

  if [[ "$HTTP_CODE" != "201" && "$HTTP_CODE" != "200" && "$HTTP_CODE" != "409" ]]; then
    die "Failed to create version (HTTP ${HTTP_CODE}): $(cat "$HTTP_BODY_FILE")"
  fi

  if ! fetch_version; then
    die "Version creation response was received, but version '${VERSION_NAME}' could not be found afterwards"
  fi

  log "Using version: ${VERSION_HREF}"
}

list_license_reports() {
  local reports_url sep
  reports_url="${VERSION_HREF}/reports"
  sep="?"
  if [[ "$reports_url" == *\?* ]]; then
    sep="&"
  fi

  http_request "GET" "${reports_url}${sep}limit=200" "" "application/vnd.blackducksoftware.report-4+json"
  if [[ "$HTTP_CODE" != "200" ]]; then
    die "Failed to list reports (HTTP ${HTTP_CODE}): $(cat "$HTTP_BODY_FILE")"
  fi
}

choose_existing_report() {
  list_license_reports

  local completed_href in_progress_href
  completed_href="$(jq -r '
    [ .items[]?
      | select((.reportType // "") == "VERSION_LICENSE")
      | select((.reportFormat // "") == "TEXT")
      | select((.status // "") == "COMPLETED")
    ]
    | sort_by(.updatedAt // .createdAt // "")
    | last
    | ._meta.href // empty
  ' "$HTTP_BODY_FILE")"

  if [[ -n "$completed_href" ]]; then
    REPORT_STATUS_URL="$(to_abs_url "$completed_href")"
    log "Reusing existing completed Notices report"
    return 0
  fi

  in_progress_href="$(jq -r '
    [ .items[]?
      | select((.reportType // "") == "VERSION_LICENSE")
      | select((.reportFormat // "") == "TEXT")
      | select((.status // "") != "COMPLETED")
    ]
    | sort_by(.updatedAt // .createdAt // "")
    | last
    | ._meta.href // empty
  ' "$HTTP_BODY_FILE")"

  if [[ -n "$in_progress_href" ]]; then
    REPORT_STATUS_URL="$(to_abs_url "$in_progress_href")"
    log "Found existing in-progress Notices report"
    return 0
  fi

  return 1
}

create_notices_report() {
  local -a license_reports_url="${BASE_URL%/}/api/versions/${VERSION_ID}/license-reports"

  local -a payload="$(jq -cn \
    --arg versionId "$VERSION_ID" \
    '{
      versionId: $versionId,
      reportType: "VERSION_LICENSE",
      reportFormat: "TEXT",
      includeSubprojects: true,
      categories: ["LICENSE_DATA", "LICENSE_TEXT"]
    }'
  )"

  local -a media="application/vnd.blackducksoftware.report-4+json"
  local -a endpoint=${license_reports_url}

  http_request "POST" "${endpoint}" "$payload" "$media" "$media"
  local -a code="$HTTP_CODE"

  local location
  if [[ "$code" == "201" || "$code" == "202" ]]; then
    location="$(awk 'tolower($1)=="location:" {print $2}' "$HTTP_HEADERS_FILE" | tr -d '\r' | tail -n 1)"
    if [[ -z "$location" ]]; then
        location="$(jq -r '._meta.href // empty' "$HTTP_BODY_FILE")"
    fi

    REPORT_STATUS_URL="$(to_abs_url "$location")"
    if [[ -z "$REPORT_STATUS_URL" ]]; then
        die "Report created but no Location/report URL was returned"
    fi

    log "Created new Notices report: ${REPORT_STATUS_URL}"
    return 0
  fi

  if [[ "$code" != "400" && "$code" != "404" ]]; then
    log "Notices report attempt failed on ${endpoint} (HTTP ${code})"
  fi

  die "Failed to create Notices report (HTTP ${HTTP_CODE}): $(cat "$HTTP_BODY_FILE")"
}

wait_for_report_ready() {
  local deadline status
  deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))

  while true; do
    http_request "GET" "$REPORT_STATUS_URL" "" "application/vnd.blackducksoftware.report-5+json"
    if [[ "$HTTP_CODE" != "200" ]]; then
      die "Failed to poll report status (HTTP ${HTTP_CODE}): $(cat "$HTTP_BODY_FILE")"
    fi

    status="$(jq -r '.status // "UNKNOWN"' "$HTTP_BODY_FILE")"
    case "$status" in
      COMPLETED)
        log "Report status: COMPLETED"
        return 0
        ;;
      FAILED|CANCELED|CANCELLED)
        die "Report status: ${status}. Response: $(cat "$HTTP_BODY_FILE")"
        ;;
      *)
        if (( SECONDS >= deadline )); then
          die "Timed out waiting for report completion after ${WAIT_TIMEOUT_SECONDS}s (last status: ${status})"
        fi
        log "Report status: ${status} (waiting ${POLL_INTERVAL_SECONDS}s)"
        sleep "$POLL_INTERVAL_SECONDS"
        ;;
    esac
  done
}

download_report() {
  local report_json report_format download_link report_id fallback_with_json fallback_without_json
  report_json="$(cat "$HTTP_BODY_FILE")"
  report_format="$(echo "$report_json" | jq -r '.reportFormat // "TEXT"')"

  if [[ "$report_format" != "TEXT" ]]; then
    die "Expected TEXT notices report, got '${report_format}'"
  fi

  download_link="$(echo "$report_json" | jq -r '._meta.links[]? | select(.rel == "download") | .href // empty' | head -n 1)"
  download_link="$(to_abs_url "$download_link")"
  if [[ -n "$download_link" && "$download_link" != *.json ]]; then
    download_link="${download_link}.json"
  fi

  report_id="${REPORT_STATUS_URL##*/}"
  fallback_with_json="${BASE_URL%/}/api/projects/${PROJECT_ID}/versions/${VERSION_ID}/reports/${report_id}/download.json"
  fallback_without_json="${BASE_URL%/}/api/projects/${PROJECT_ID}/versions/${VERSION_ID}/reports/${report_id}/download"

  mkdir -p "$(dirname -- "$DOWNLOAD_ZIP_PATH")"

  local download_url code
  for download_url in "$download_link" "$fallback_with_json" "$fallback_without_json"; do
    if [[ -z "$download_url" ]]; then
      continue
    fi

    code="$(curl -sS -L \
      -H "Authorization: Bearer ${BEARER_TOKEN}" \
      -H "Accept: application/zip" \
      -o "$DOWNLOAD_ZIP_PATH" \
      -w "%{http_code}" \
      "$download_url")"

    if [[ "$code" == "200" ]]; then
      if [[ ! -s "$DOWNLOAD_ZIP_PATH" ]]; then
        die "Downloaded file is empty: ${DOWNLOAD_ZIP_PATH}"
      fi
      log "Downloaded Notices zip to: ${DOWNLOAD_ZIP_PATH}"
      return 0
    fi
  done

  die "Failed to download Notices report from all known endpoints"
}

extract_notice_text() {
  local txt_file_count txt_file_entry

  if [[ ! -s "$DOWNLOAD_ZIP_PATH" ]]; then
    die "Cannot extract notices text; zip is missing: ${DOWNLOAD_ZIP_PATH}"
  fi

  txt_file_count="$(unzip -Z1 "$DOWNLOAD_ZIP_PATH" | awk 'tolower($0) ~ /\.txt$/ && $0 !~ /\/$/ {count++} END {print count+0}')"
  if [[ "$txt_file_count" != "1" ]]; then
    die "Expected exactly one .txt file in notices zip, found ${txt_file_count}"
  fi

  txt_file_entry="$(unzip -Z1 "$DOWNLOAD_ZIP_PATH" | awk 'tolower($0) ~ /\.txt$/ && $0 !~ /\/$/ {print; exit}')"
  if [[ -z "$txt_file_entry" ]]; then
    die "Could not locate notices .txt file inside zip"
  fi

  mkdir -p "$(dirname -- "$OUTPUT_FILE")"

  local tmp_output
  tmp_output="$(mktemp "$TMP_DIR/notices_txt.XXXXXX")"

  if ! unzip -p "$DOWNLOAD_ZIP_PATH" "$txt_file_entry" > "$tmp_output"; then
    die "Failed to extract '${txt_file_entry}' from ${DOWNLOAD_ZIP_PATH}"
  fi

  if [[ ! -s "$tmp_output" ]]; then
    die "Extracted notices text is empty"
  fi
  # replace CRLF with LF
  sed -i.bak 's/\r$//' "$tmp_output"
  rm -f "$tmp_output.bak"

  mv "$tmp_output" "$OUTPUT_FILE"
  log "Wrote notices text to: ${OUTPUT_FILE}"
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --version-name)
        VERSION_NAME="$2"
        shift 2
        ;;
      --api-token)
        API_TOKEN="$2"
        shift 2
        ;;
      --base-url)
        BASE_URL="$2"
        shift 2
        ;;
      --project-id)
        PROJECT_ID="$2"
        shift 2
        ;;
      --output-dir)
        OUTPUT_DIR="$2"
        shift 2
        ;;
      --output-file)
        OUTPUT_FILE="$2"
        OUTPUT_FILE_WAS_SET=1
        shift 2
        ;;
      --phase)
        VERSION_PHASE="$2"
        shift 2
        ;;
      --distribution)
        VERSION_DISTRIBUTION="$2"
        shift 2
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "Unknown argument: $1"
        ;;
    esac
  done
}

main() {
  require_cmd curl
  require_cmd jq
  require_cmd unzip

  TMP_DIR="$(mktemp -d)"
  trap cleanup EXIT

  parse_args "$@"

  if [[ -z "$VERSION_NAME" ]]; then
    if [[ -f "${REPO_ROOT}/VERSION" ]]; then
      VERSION_NAME="$(head -n 1 "${REPO_ROOT}/VERSION" | tr -d '[:space:]')"
    fi
  fi

  if [[ -z "$VERSION_NAME" ]]; then
    die "Missing version name. Use --version-name or provide a VERSION file"
  fi

  if [[ -z "$API_TOKEN" ]]; then
    API_TOKEN="${ITS_BLACKDUCK_KEY:-${BLACKDUCK_API_TOKEN:-}}"
  fi

  if [[ -z "$API_TOKEN" ]]; then
    die "Missing API token. Use --api-token or set ITS_BLACKDUCK_KEY / BLACKDUCK_API_TOKEN"
  fi

  if [[ "$OUTPUT_FILE_WAS_SET" == "1" ]]; then
    DOWNLOAD_ZIP_PATH="${TMP_DIR}/notices-${VERSION_NAME}.zip"
  else
    OUTPUT_FILE="${REPO_ROOT}/THIRD-PARTY-LICENSES"
    DOWNLOAD_ZIP_PATH="${OUTPUT_DIR%/}/notices-${VERSION_NAME}.zip"
  fi

  log "Authenticating to Black Duck"
  authenticate

  create_version_if_missing

  if ! choose_existing_report; then
    create_notices_report
  fi

  wait_for_report_ready
  download_report
  extract_notice_text

  log "Done"
}

main "$@"
