#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION_NAME="${BACKEND_TMUX_SESSION:-med_annotate_backend}"
LOG_FILE="${PROJECT_ROOT}/logs/backend_tmux.log"

if tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
  echo "tmux session: running (${SESSION_NAME})"
  tmux list-panes -t "${SESSION_NAME}" -F 'pane_pid=#{pane_pid} pane_dead=#{pane_dead} pane_start=#{pane_start_command}'
else
  echo "tmux session: not running (${SESSION_NAME})"
fi

ps -ef | grep "uvicorn app.main:app" | grep -v grep || true

if [[ -f "${LOG_FILE}" ]]; then
  echo "--- recent log ---"
  tail -n 20 "${LOG_FILE}" || true
fi
