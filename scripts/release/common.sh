#!/usr/bin/env bash
# Shared helpers for explicit production release operations. Never enable xtrace here.
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_DIR="${PROJECT_ROOT}/backend"
RELEASES_DIR="${PROJECT_ROOT}/backups/releases"
RUNTIME_DIR="${PROJECT_ROOT}/.runtime"
RELEASE_LOCK="${RUNTIME_DIR}/release.lock"

# Keep Alembic and Settings aligned with scripts/start_backend_host.sh. Existing
# operator-provided environment values still take precedence.
export POSTGRES_HOST="${POSTGRES_HOST:-127.0.0.1}"
export POSTGRES_PORT="${POSTGRES_PORT:-5433}"
export POSTGRES_DB="${POSTGRES_DB:-med_annotate}"
export POSTGRES_USER="${POSTGRES_USER:-med_annotate}"
export LOCAL_STORAGE_ROOT="${LOCAL_STORAGE_ROOT:-${PROJECT_ROOT}/storage}"

info() { printf '[release] %s\n' "$*"; }
warn() { printf '[release] warning: %s\n' "$*" >&2; }
die() { printf '[release] error: %s\n' "$*" >&2; exit 1; }
is_dry_run() { [[ "${DRY_RUN:-0}" == "1" ]]; }

timestamp() { date -u +%Y%m%d_%H%M%S; }
read_version() {
    [[ -f "${PROJECT_ROOT}/VERSION" ]] || die "VERSION is missing."
    local value
    value="$(tr -d '[:space:]' < "${PROJECT_ROOT}/VERSION")"
    [[ "${value}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "VERSION must use MAJOR.MINOR.PATCH."
    printf '%s\n' "${value}"
}
git_commit() { git -C "${PROJECT_ROOT}" rev-parse HEAD; }
git_describe() { git -C "${PROJECT_ROOT}" describe --tags --always --dirty 2>/dev/null || git_commit; }
backend_python() { printf '%s/bin/python\n' "${CONDA_ENV:-${PROJECT_ROOT}/../conda_envs/sam}"; }
require_backend_python() { [[ -x "$(backend_python)" ]] || die "Backend Python is unavailable; set CONDA_ENV."; }
compose() { (cd "${PROJECT_ROOT}" && docker compose "$@"); }
run_alembic() { (cd "${BACKEND_DIR}" && "$(backend_python)" -m alembic -c alembic.ini "$@"); }

database_current() { run_alembic current; }
database_heads() { run_alembic heads; }
database_head() {
    local heads
    heads="$(database_heads)"
    [[ "$(printf '%s\n' "${heads}" | grep -c '(head)')" -eq 1 ]] || die "Release requires exactly one Alembic head."
    printf '%s\n' "${heads}" | awk '/\(head\)/ { print $1 }'
}

database_name() { printf '%s\n' "${POSTGRES_DB:-med_annotate}"; }
database_user() { printf '%s\n' "${POSTGRES_USER:-med_annotate}"; }
storage_root() {
    (cd "${BACKEND_DIR}" && "$(backend_python)" -c 'from app.core.config import settings; print(settings.local_storage_root)')
}
configured_ffmpeg() {
    (cd "${BACKEND_DIR}" && "$(backend_python)" -c 'from app.core.config import settings; print(settings.research_video_ffmpeg_binary)')
}
available_bytes() { df -Pk "$1" | awk 'NR == 2 { print $4 * 1024 }'; }
database_size_bytes() {
    compose exec -T db psql -U "$(database_user)" -d "$(database_name)" -Atqc 'SELECT pg_database_size(current_database())'
}
ensure_free_bytes() {
    local path="$1" required="$2" available
    available="$(available_bytes "${path}")"
    (( available >= required )) || die "Insufficient free space at ${path}: need ${required} bytes, have ${available}."
}

write_manifest() {
    local release_dir="$1" reason="$2" storage_mode="$3"
    RELEASE_DIR="${release_dir}" RELEASE_REASON="${reason}" STORAGE_MODE="${storage_mode}" \
    RELEASE_VERSION="$(read_version)" RELEASE_COMMIT="$(git_commit)" RELEASE_DESCRIBE="$(git_describe)" \
    RELEASE_DB_CURRENT="$(database_current)" RELEASE_DB_HEAD="$(database_head)" \
    RELEASE_DB_NAME="$(database_name)" RELEASE_STORAGE_ROOT="$(storage_root)" \
    python3 - <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path

payload = {
    "created_at": datetime.now(timezone.utc).isoformat(),
    "hostname": os.uname().nodename,
    "app_version": os.environ["RELEASE_VERSION"],
    "git_commit": os.environ["RELEASE_COMMIT"],
    "git_describe": os.environ["RELEASE_DESCRIBE"],
    "database_revision": os.environ["RELEASE_DB_CURRENT"],
    "database_head": os.environ["RELEASE_DB_HEAD"],
    "database_name": os.environ["RELEASE_DB_NAME"],
    "storage_root": os.environ["RELEASE_STORAGE_ROOT"],
    "storage_backup_mode": os.environ["STORAGE_MODE"],
    "reason": os.environ["RELEASE_REASON"],
}
Path(os.environ["RELEASE_DIR"], "manifest.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
PY
}

write_deployment_result() {
    local release_dir="$1" outcome="$2" step="$3" before_version="$4" before_commit="$5" before_db="$6"
    RELEASE_DIR="${release_dir}" RELEASE_OUTCOME="${outcome}" RELEASE_STEP="${step}" \
    RELEASE_BEFORE_VERSION="${before_version}" RELEASE_BEFORE_COMMIT="${before_commit}" RELEASE_BEFORE_DB="${before_db}" \
    RELEASE_AFTER_VERSION="$(read_version)" RELEASE_AFTER_COMMIT="$(git_commit)" RELEASE_AFTER_DB="$(database_current 2>/dev/null || true)" \
    python3 - <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path

payload = {
    "created_at": datetime.now(timezone.utc).isoformat(),
    "outcome": os.environ["RELEASE_OUTCOME"],
    "step": os.environ["RELEASE_STEP"],
    "before": {"version": os.environ["RELEASE_BEFORE_VERSION"], "git_commit": os.environ["RELEASE_BEFORE_COMMIT"], "database_revision": os.environ["RELEASE_BEFORE_DB"]},
    "after": {"version": os.environ["RELEASE_AFTER_VERSION"], "git_commit": os.environ["RELEASE_AFTER_COMMIT"], "database_revision": os.environ["RELEASE_AFTER_DB"]},
}
Path(os.environ["RELEASE_DIR"], "deployment.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
PY
}
