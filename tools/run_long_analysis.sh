#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

STATE_DIR="${PROJECT_ROOT}/.runtime/long_analysis"
LOG_DIR="${PROJECT_ROOT}/logs/long_analysis"
PID_FILE="${STATE_DIR}/supervisor.pid"
CMD_FILE="${STATE_DIR}/command.txt"
SUPERVISOR_LOG="${LOG_DIR}/supervisor.log"
WORKER_LOG="${LOG_DIR}/worker.log"

mkdir -p "${STATE_DIR}" "${LOG_DIR}"

MAX_LOG_BYTES="${MAX_LOG_BYTES:-104857600}"    # 100MB
MAX_LOG_FILES="${MAX_LOG_FILES:-8}"
CHECK_INTERVAL="${CHECK_INTERVAL:-30}"
RETRY_DELAY_SECONDS="${RETRY_DELAY_SECONDS:-20}"
MAX_RETRIES="${MAX_RETRIES:--1}"               # -1 = unlimited
MIN_TOTAL_RUNTIME_SECONDS="${MIN_TOTAL_RUNTIME_SECONDS:-21600}"  # 6h

usage() {
  cat <<USAGE
Usage:
  $(basename "$0") start -- <command>
  $(basename "$0") status
  $(basename "$0") stop
  $(basename "$0") tail

Behavior:
  - start: uses nohup to run a supervisor in background.
  - supervisor restarts command on failures (and on early success before min runtime).
  - defaults to keep running for >= 6 hours total runtime.
  - log rotation: copy-truncate when worker log exceeds MAX_LOG_BYTES.

Environment variables:
  MIN_TOTAL_RUNTIME_SECONDS (default: 21600)
  MAX_RETRIES              (default: -1 unlimited)
  RETRY_DELAY_SECONDS      (default: 20)
  CHECK_INTERVAL           (default: 30)
  MAX_LOG_BYTES            (default: 104857600)
  MAX_LOG_FILES            (default: 8)
USAGE
}

is_running() {
  if [[ ! -f "${PID_FILE}" ]]; then
    return 1
  fi
  local pid
  pid="$(cat "${PID_FILE}")"
  [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null
}

rotate_log_copytruncate() {
  local file="$1"
  local max_bytes="$2"
  local keep="$3"

  [[ -f "${file}" ]] || return 0

  local size
  size="$(wc -c < "${file}")"
  if (( size < max_bytes )); then
    return 0
  fi

  local i
  for ((i=keep; i>=2; i--)); do
    if [[ -f "${file}.$((i-1))" ]]; then
      mv -f "${file}.$((i-1))" "${file}.${i}"
    fi
  done

  cp "${file}" "${file}.1"
  : > "${file}"
}

supervisor() {
  local command
  if [[ ! -f "${CMD_FILE}" ]]; then
    echo "[ERROR] command file missing: ${CMD_FILE}"
    exit 1
  fi
  command="$(cat "${CMD_FILE}")"

  if [[ -z "${command}" ]]; then
    echo "[ERROR] empty command"
    exit 1
  fi

  local started_at
  started_at="$(date +%s)"
  local attempts=0
  local failures=0
  local child_pid=""

  term_handler() {
    echo "[INFO] supervisor received stop signal"
    if [[ -n "${child_pid}" ]] && kill -0 "${child_pid}" 2>/dev/null; then
      kill "${child_pid}" 2>/dev/null || true
      wait "${child_pid}" 2>/dev/null || true
    fi
    rm -f "${PID_FILE}"
    exit 0
  }

  trap term_handler SIGINT SIGTERM

  echo "[INFO] supervisor started at $(date -Is)"
  echo "[INFO] command=${command}"
  echo "[INFO] min_total_runtime_seconds=${MIN_TOTAL_RUNTIME_SECONDS}"
  echo "[INFO] max_retries=${MAX_RETRIES} retry_delay=${RETRY_DELAY_SECONDS}s"

  while true; do
    attempts=$((attempts + 1))
    rotate_log_copytruncate "${SUPERVISOR_LOG}" "${MAX_LOG_BYTES}" "${MAX_LOG_FILES}"
    rotate_log_copytruncate "${WORKER_LOG}" "${MAX_LOG_BYTES}" "${MAX_LOG_FILES}"

    echo "[INFO] attempt=${attempts} start=$(date -Is)"

    set +e
    bash -lc "${command}" >> "${WORKER_LOG}" 2>&1 &
    child_pid=$!

    while kill -0 "${child_pid}" 2>/dev/null; do
      rotate_log_copytruncate "${WORKER_LOG}" "${MAX_LOG_BYTES}" "${MAX_LOG_FILES}"
      sleep "${CHECK_INTERVAL}"
    done

    wait "${child_pid}"
    exit_code=$?
    set -e

    local now runtime
    now="$(date +%s)"
    runtime=$((now - started_at))

    echo "[INFO] attempt=${attempts} exit_code=${exit_code} runtime=${runtime}s"

    if [[ "${exit_code}" -eq 0 ]]; then
      if (( runtime >= MIN_TOTAL_RUNTIME_SECONDS )); then
        echo "[INFO] minimum runtime reached with success. exiting supervisor."
        rm -f "${PID_FILE}"
        exit 0
      fi

      echo "[INFO] command exited successfully before minimum runtime, restarting after delay"
      sleep "${RETRY_DELAY_SECONDS}"
      continue
    fi

    failures=$((failures + 1))
    if (( MAX_RETRIES >= 0 && failures > MAX_RETRIES )); then
      echo "[ERROR] max retries exceeded (failures=${failures})"
      rm -f "${PID_FILE}"
      exit 2
    fi

    echo "[WARN] command failed, retrying after ${RETRY_DELAY_SECONDS}s (failures=${failures})"
    sleep "${RETRY_DELAY_SECONDS}"
  done
}

start() {
  local cmd="$1"

  if is_running; then
    local running_pid
    running_pid="$(cat "${PID_FILE}")"
    echo "[INFO] already running, pid=${running_pid}"
    exit 0
  fi

  printf '%s\n' "${cmd}" > "${CMD_FILE}"

  nohup "$0" __supervise >> "${SUPERVISOR_LOG}" 2>&1 &
  local spid=$!
  printf '%s\n' "${spid}" > "${PID_FILE}"

  echo "[INFO] supervisor started in background pid=${spid}"
  echo "[INFO] supervisor_log=${SUPERVISOR_LOG}"
  echo "[INFO] worker_log=${WORKER_LOG}"
}

status() {
  if is_running; then
    echo "[INFO] running pid=$(cat "${PID_FILE}")"
    echo "[INFO] supervisor_log=${SUPERVISOR_LOG}"
    echo "[INFO] worker_log=${WORKER_LOG}"
  else
    echo "[INFO] not running"
    exit 1
  fi
}

stop() {
  if ! is_running; then
    echo "[INFO] not running"
    rm -f "${PID_FILE}"
    exit 0
  fi

  local pid
  pid="$(cat "${PID_FILE}")"
  kill "${pid}" 2>/dev/null || true

  for _ in {1..20}; do
    if kill -0 "${pid}" 2>/dev/null; then
      sleep 1
    else
      break
    fi
  done

  if kill -0 "${pid}" 2>/dev/null; then
    kill -9 "${pid}" 2>/dev/null || true
  fi

  rm -f "${PID_FILE}"
  echo "[INFO] stopped"
}

tail_logs() {
  touch "${SUPERVISOR_LOG}" "${WORKER_LOG}"
  tail -n 120 -f "${SUPERVISOR_LOG}" "${WORKER_LOG}"
}

subcmd="${1:-}"
case "${subcmd}" in
  start)
    shift
    if [[ "${1:-}" != "--" ]]; then
      usage
      exit 1
    fi
    shift
    if [[ $# -eq 0 ]]; then
      echo "[ERROR] missing command"
      usage
      exit 1
    fi
    cmd="$*"
    start "${cmd}"
    ;;
  status)
    status
    ;;
  stop)
    stop
    ;;
  tail)
    tail_logs
    ;;
  __supervise)
    supervisor
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage
    exit 1
    ;;
esac
