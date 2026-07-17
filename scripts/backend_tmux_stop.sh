#!/usr/bin/env bash
set -euo pipefail

SESSION_NAME="${BACKEND_TMUX_SESSION:-med_annotate_backend}"

if ! tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
  echo "Backend tmux session not running: ${SESSION_NAME}"
  exit 0
fi

tmux kill-session -t "${SESSION_NAME}"
echo "Backend tmux session stopped: ${SESSION_NAME}"
