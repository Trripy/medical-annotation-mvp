#!/usr/bin/env bash
# Explicit production deployment entry point. It never changes Git checkout state.
set -Eeuo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

target_version=""
while (($#)); do
    case "$1" in
        --target-version) target_version="${2:?missing target version}"; shift 2 ;;
        *) die "Unknown deploy option: $1" ;;
    esac
done
[[ -z "${target_version}" || "${target_version}" == "$(read_version)" ]] || die "VERSION does not match --target-version."
if is_dry_run; then
    info "DRY_RUN deployment plan: precheck, verified backup, stop backend writes, dependencies, Alembic upgrade, frontend build/up, backend start, smoke test."
    DRY_RUN=1 "$(dirname "${BASH_SOURCE[0]}")/precheck.sh"
    exit 0
fi
mkdir -p "${RUNTIME_DIR}"
command -v flock >/dev/null || die "flock is required for release locking."
exec 9>"${RELEASE_LOCK}"
flock -n 9 || die "Production release already running."

before_version="$(read_version)"
before_commit="$(git_commit)"
before_db=""
backup_dir=""
step="precheck"
on_failure() {
    local status=$?
    if [[ -n "${backup_dir}" && -d "${backup_dir}" ]]; then
        write_deployment_result "${backup_dir}" "failed" "${step}" "${before_version}" "${before_commit}" "${before_db}" || true
    fi
    warn "Release failed during ${step}; no automatic database restore was attempted."
    warn "Backup path: ${backup_dir:-not-created}; previous DB revision: ${before_db:-unavailable}."
    exit "${status}"
}
trap on_failure ERR

"$(dirname "${BASH_SOURCE[0]}")/precheck.sh"
before_db="$(database_current)"
step="backup"
backup_output="$("$(dirname "${BASH_SOURCE[0]}")/backup.sh" --reason "pre-release v${before_version}")"
printf '%s\n' "${backup_output}"
backup_dir="$(printf '%s\n' "${backup_output}" | sed -n 's/^\[release\] BACKUP_DIR=//p' | tail -n 1)"
[[ -n "${backup_dir}" ]] || die "Backup did not report its release directory."
step="backup verification"
if [[ "${REQUIRE_DEEP_BACKUP_VERIFY:-1}" == "1" ]]; then
    "$(dirname "${BASH_SOURCE[0]}")/verify_backup.sh" --deep "${backup_dir}"
else
    "$(dirname "${BASH_SOURCE[0]}")/verify_backup.sh" "${backup_dir}"
fi
if [[ "${STORAGE_MIGRATION:-0}" == "1" ]]; then
    [[ -n "${VERIFIED_STORAGE_BACKUP_MANIFEST:-}" && -f "${VERIFIED_STORAGE_BACKUP_MANIFEST}" ]] || die "Storage migration requires VERIFIED_STORAGE_BACKUP_MANIFEST."
    grep -q '"storage_backup_mode": "full"' "${VERIFIED_STORAGE_BACKUP_MANIFEST}" || die "Storage migration requires a full storage backup manifest."
fi
step="stop backend"
"${PROJECT_ROOT}/scripts/backend_tmux_stop.sh"
step="database recheck"
database_current >/dev/null
database_head >/dev/null
step="dependencies"
"$(backend_python)" -m pip install -r "${BACKEND_DIR}/requirements.txt"
step="migration"
run_alembic upgrade head
step="frontend build"
compose build frontend
step="frontend deploy"
compose up -d frontend
step="backend start"
SKIP_ALEMBIC=true "${PROJECT_ROOT}/scripts/backend_tmux_start.sh"
step="backend readiness"
for _ in $(seq 1 90); do
    curl --fail --silent http://127.0.0.1:8000/api/v1/health >/dev/null && break
    sleep 1
done
curl --fail --silent http://127.0.0.1:8000/api/v1/health >/dev/null || die "Backend did not become ready."
step="smoke test"
"$(dirname "${BASH_SOURCE[0]}")/smoke_test.sh"
write_deployment_result "${backup_dir}" "success" "complete" "${before_version}" "${before_commit}" "${before_db}"
info "Release completed successfully. Backup: ${backup_dir}"
