#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

if is_dry_run; then
    info "DRY_RUN: would query backend health/version and frontend SPA endpoints."
    exit 0
fi
command -v curl >/dev/null || die "curl is unavailable."
curl --fail --silent --show-error http://127.0.0.1:8000/api/v1/health >/dev/null
version_payload="$(curl --fail --silent --show-error http://127.0.0.1:8000/api/v1/version)"
VERSION_PAYLOAD="${version_payload}" python3 - <<'PY'
import json
import os
payload = json.loads(os.environ["VERSION_PAYLOAD"])
for field in ("version", "git_commit", "database_revision", "database_head"):
    if field not in payload:
        raise SystemExit(f"Missing version field: {field}")
PY
curl --fail --silent --show-error http://127.0.0.1:5173/jobs >/dev/null
compose ps --status running frontend | grep -q frontend || die "Frontend service is not running."
tmux has-session -t "${BACKEND_TMUX_SESSION:-med_annotate_backend}" || die "Backend tmux session is not running."
info "Smoke test passed."
