#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

deep=0
[[ "${1:-}" == "--deep" ]] && { deep=1; shift; }
target="${1:?Usage: verify_backup.sh [--deep] <backup-directory|database.dump>}"
[[ -d "${target}" ]] && dump_path="${target}/database.dump" || dump_path="${target}"
[[ -s "${dump_path}" ]] || die "Backup dump is missing or empty: ${dump_path}"
if is_dry_run; then
    deep_description=""
    if (( deep )); then
        deep_description=" and restore it into a temporary database"
    fi
    info "DRY_RUN: would validate custom dump ${dump_path}${deep_description}."
    exit 0
fi
compose exec -T db pg_restore -l < "${dump_path}" >/dev/null || die "pg_restore cannot read the backup."
info "Backup format validation passed: ${dump_path}"
(( deep )) || exit 0

temporary_db="med_annotate_restore_test_$(timestamp)"
cleanup() {
    compose exec -T db psql -U "$(database_user)" -d postgres -v ON_ERROR_STOP=1 \
        -c "DROP DATABASE IF EXISTS ${temporary_db}" >/dev/null 2>&1 || true
}
trap cleanup EXIT
compose exec -T db psql -U "$(database_user)" -d postgres -v ON_ERROR_STOP=1 \
    -c "CREATE DATABASE ${temporary_db}" >/dev/null
compose exec -T db pg_restore --no-owner --no-privileges -d "${temporary_db}" < "${dump_path}"
compose exec -T db psql -U "$(database_user)" -d "${temporary_db}" -v ON_ERROR_STOP=1 -Atqc \
    "SELECT version_num FROM alembic_version LIMIT 1" >/dev/null
for table_name in jobs images annotations research_videos research_phase_annotation_sets research_skill_assessments; do
    compose exec -T db psql -U "$(database_user)" -d "${temporary_db}" -Atqc \
        "SELECT CASE WHEN to_regclass('${table_name}') IS NULL THEN NULL ELSE (SELECT count(*)::text FROM ${table_name}) END" >/dev/null
done
info "Deep restore verification passed in temporary database ${temporary_db}."
