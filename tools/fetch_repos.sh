#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DEFAULT_MANIFEST="${PROJECT_ROOT}/research/repo_manifest.txt"
DEFAULT_TARGET_ROOT="${PROJECT_ROOT}/third_party_repos"
LOG_DIR="${PROJECT_ROOT}/logs/fetch"
TS="$(date +"%Y%m%d_%H%M%S")"
LOG_FILE="${LOG_DIR}/fetch_${TS}.log"

mkdir -p "${LOG_DIR}"
exec > >(tee -a "${LOG_FILE}") 2>&1

trim() {
  local s="$1"
  s="${s#${s%%[![:space:]]*}}"
  s="${s%${s##*[![:space:]]}}"
  printf '%s' "$s"
}

normalize_repo_url() {
  local url="$1"
  url="${url%.git}"
  url="${url#https://}"
  url="${url#http://}"
  url="${url#git@}"
  url="${url/:/\/}"
  printf '%s' "${url}"
}

derive_dest_from_url() {
  local url="$1"
  local stripped
  stripped="$(normalize_repo_url "$url")"
  stripped="${stripped#github.com/}"
  stripped="${stripped#www.github.com/}"

  if [[ "${stripped}" == */* ]]; then
    printf '%s' "${stripped//\//__}"
  else
    printf '%s' "${stripped}"
  fi
}

retry_run() {
  local retries="$1"
  local delay="$2"
  shift 2

  local attempt=1
  while true; do
    if "$@"; then
      return 0
    fi

    if (( attempt > retries )); then
      return 1
    fi

    echo "[WARN] attempt=${attempt}/${retries} failed: $*"
    sleep "$delay"
    attempt=$((attempt + 1))
  done
}

clone_repo() {
  local url="$1"
  local dest="$2"
  local branch="$3"
  local depth="$4"

  mkdir -p "$(dirname "$dest")"

  if [[ -n "${branch}" ]]; then
    if [[ "${depth}" -gt 0 ]]; then
      git clone --branch "${branch}" --depth "${depth}" "${url}" "${dest}"
    else
      git clone --branch "${branch}" "${url}" "${dest}"
    fi
  else
    if [[ "${depth}" -gt 0 ]]; then
      git clone --depth "${depth}" "${url}" "${dest}"
    else
      git clone "${url}" "${dest}"
    fi
  fi
}

update_repo() {
  local dest="$1"
  local branch="$2"

  if [[ -n "${branch}" ]]; then
    git -C "${dest}" fetch --all --prune
    git -C "${dest}" checkout "${branch}"
    git -C "${dest}" pull --ff-only origin "${branch}"
  else
    local current_branch
    current_branch="$(git -C "${dest}" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"

    git -C "${dest}" fetch --all --prune
    if [[ -n "${current_branch}" && "${current_branch}" != "HEAD" ]]; then
      git -C "${dest}" pull --ff-only origin "${current_branch}"
    else
      git -C "${dest}" pull --ff-only || true
    fi
  fi
}

usage() {
  cat <<USAGE
Usage:
  $(basename "$0") [manifest_path] [target_root]

Manifest format (one repo per line):
  repo_url|relative_dir|branch

Rules:
  - Empty lines and lines starting with # are ignored.
  - relative_dir and branch are optional.
  - If relative_dir is empty, script derives a stable folder name from URL.

Environment variables:
  FETCH_RETRY_COUNT   (default: 3)
  FETCH_RETRY_DELAY   (default: 8)      # seconds
  CLONE_DEPTH         (default: 0)      # 0 means full clone
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

MANIFEST_PATH="${1:-${DEFAULT_MANIFEST}}"
TARGET_ROOT="${2:-${DEFAULT_TARGET_ROOT}}"
FETCH_RETRY_COUNT="${FETCH_RETRY_COUNT:-3}"
FETCH_RETRY_DELAY="${FETCH_RETRY_DELAY:-8}"
CLONE_DEPTH="${CLONE_DEPTH:-0}"

mkdir -p "${TARGET_ROOT}"

if [[ ! -f "${MANIFEST_PATH}" ]]; then
  echo "[ERROR] manifest not found: ${MANIFEST_PATH}"
  echo "[INFO] copy template first: ${PROJECT_ROOT}/research/repo_manifest.template.txt"
  exit 1
fi

echo "[INFO] fetch started at $(date -Is)"
echo "[INFO] manifest=${MANIFEST_PATH}"
echo "[INFO] target_root=${TARGET_ROOT}"
echo "[INFO] log_file=${LOG_FILE}"

processed=0
cloned=0
updated=0
skipped=0
failed=0

line_no=0
while IFS= read -r raw_line || [[ -n "${raw_line}" ]]; do
  line_no=$((line_no + 1))

  line="$(trim "${raw_line}")"
  [[ -z "${line}" ]] && continue
  [[ "${line}" == \#* ]] && continue

  IFS='|' read -r raw_url raw_rel_dir raw_branch _ <<< "${line}"

  repo_url="$(trim "${raw_url:-}")"
  rel_dir="$(trim "${raw_rel_dir:-}")"
  branch="$(trim "${raw_branch:-}")"

  if [[ -z "${repo_url}" ]]; then
    echo "[WARN] line ${line_no}: empty repo url, skipped"
    skipped=$((skipped + 1))
    continue
  fi

  if [[ -z "${rel_dir}" ]]; then
    rel_dir="$(derive_dest_from_url "${repo_url}")"
  fi

  dest_dir="${TARGET_ROOT}/${rel_dir}"
  processed=$((processed + 1))

  echo "[INFO] line=${line_no} repo=${repo_url} dest=${dest_dir} branch=${branch:-<default>}"

  if [[ -d "${dest_dir}" && ! -d "${dest_dir}/.git" ]]; then
    echo "[WARN] destination exists but is not a git repo, skipped: ${dest_dir}"
    skipped=$((skipped + 1))
    continue
  fi

  if [[ -d "${dest_dir}/.git" ]]; then
    current_origin="$(git -C "${dest_dir}" remote get-url origin 2>/dev/null || true)"
    if [[ -n "${current_origin}" ]]; then
      if [[ "$(normalize_repo_url "${current_origin}")" != "$(normalize_repo_url "${repo_url}")" ]]; then
        echo "[WARN] origin mismatch at ${dest_dir}"
        echo "[WARN] current=${current_origin}"
        echo "[WARN] target=${repo_url}"
        skipped=$((skipped + 1))
        continue
      fi
    fi

    if retry_run "${FETCH_RETRY_COUNT}" "${FETCH_RETRY_DELAY}" update_repo "${dest_dir}" "${branch}"; then
      updated=$((updated + 1))
    else
      echo "[ERROR] update failed: ${repo_url}"
      failed=$((failed + 1))
    fi
  else
    if retry_run "${FETCH_RETRY_COUNT}" "${FETCH_RETRY_DELAY}" clone_repo "${repo_url}" "${dest_dir}" "${branch}" "${CLONE_DEPTH}"; then
      cloned=$((cloned + 1))
    else
      echo "[ERROR] clone failed: ${repo_url}"
      failed=$((failed + 1))
    fi
  fi
done < "${MANIFEST_PATH}"

echo "[INFO] fetch finished at $(date -Is)"
echo "[INFO] summary processed=${processed} cloned=${cloned} updated=${updated} skipped=${skipped} failed=${failed}"

if (( failed > 0 )); then
  exit 2
fi
