#!/usr/bin/env bash
# Disaster recovery only. This intentionally requires an exact production confirmation.
set -Eeuo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

target="${1:?Usage: CONFIRM_PRODUCTION_DB_RESTORE=RESTORE_PRODUCTION_DATABASE restore_database.sh <backup-directory|database.dump>}"
[[ "${CONFIRM_PRODUCTION_DB_RESTORE:-}" == "RESTORE_PRODUCTION_DATABASE" ]] || die "Production restore requires CONFIRM_PRODUCTION_DB_RESTORE=RESTORE_PRODUCTION_DATABASE."
[[ -d "${target}" ]] && dump_path="${target}/database.dump" || dump_path="${target}"
[[ -s "${dump_path}" ]] || die "Backup dump is missing or empty."
tmux has-session -t "${BACKEND_TMUX_SESSION:-med_annotate_backend}" && die "Stop the backend before restoring a production database."
is_dry_run && { info "DRY_RUN: would create an emergency backup then restore ${dump_path}; no action taken."; exit 0; }
"$(dirname "${BASH_SOURCE[0]}")/verify_backup.sh" "${dump_path}"
info "Creating an emergency backup of the current database before restore."
"$(dirname "${BASH_SOURCE[0]}")/backup.sh" --reason "emergency-before-restore"
db_name="$(database_name)"
compose exec -T db psql -U "$(database_user)" -d postgres -v ON_ERROR_STOP=1 -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${db_name}' AND pid <> pg_backend_pid();" >/dev/null
compose exec -T db psql -U "$(database_user)" -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE ${db_name}" >/dev/null
compose exec -T db psql -U "$(database_user)" -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE ${db_name}" >/dev/null
compose exec -T db pg_restore --no-owner --no-privileges -d "${db_name}" < "${dump_path}"
warn "Database restore completed. Storage was not restored and backend remains stopped; validate before restarting services."
