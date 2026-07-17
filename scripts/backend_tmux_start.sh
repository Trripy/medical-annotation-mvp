#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION_NAME="${BACKEND_TMUX_SESSION:-med_annotate_backend}"
LOG_DIR="${PROJECT_ROOT}/logs"
LOG_FILE="${LOG_DIR}/backend_tmux.log"
PID_FILE="${LOG_DIR}/backend_tmux.pid"
START_SCRIPT="${BACKEND_START_SCRIPT:-./scripts/start_backend_host.sh}"

mkdir -p "${LOG_DIR}"

if tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
  echo "Backend tmux session already exists: ${SESSION_NAME}"
  tmux list-panes -t "${SESSION_NAME}" -F '#{pane_pid}' | head -n 1 > "${PID_FILE}" || true
  exit 0
fi

tmux new-session -d -s "${SESSION_NAME}" "cd '${PROJECT_ROOT}' && ${START_SCRIPT} 2>&1 | tee -a '${LOG_FILE}'"

sleep 1
tmux list-panes -t "${SESSION_NAME}" -F '#{pane_pid}' | head -n 1 > "${PID_FILE}" || true

echo "Backend started in tmux session: ${SESSION_NAME}"
echo "Log: ${LOG_FILE}"
echo "Attach: tmux attach -t ${SESSION_NAME}"
echo "Start script: ${START_SCRIPT}"
