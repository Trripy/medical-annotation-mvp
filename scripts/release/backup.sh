#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

reason="manual backup" storage_mode="not_requested"
while (($#)); do
    case "$1" in
        --reason) reason="${2:?missing reason}"; shift 2 ;;
        --storage-manifest) storage_mode="manifest"; shift ;;
        --storage-full) storage_mode="full"; shift ;;
        *) die "Unknown backup option: $1" ;;
    esac
done
if [[ "${storage_mode}" == "full" && "${CONFIRM_STORAGE_BACKUP:-}" != "YES" ]]; then
    die "--storage-full requires CONFIRM_STORAGE_BACKUP=YES."
fi
release_dir="${RELEASES_DIR}/$(timestamp)_v$(read_version)"
if is_dry_run; then
    info "DRY_RUN: would create ${release_dir}, write a PostgreSQL custom dump, and record ${storage_mode} storage metadata."
    exit 0
fi
mkdir -p "${release_dir}"
db_size="$(database_size_bytes)"
ensure_free_bytes "${RELEASES_DIR}" "$(( db_size * 12 / 10 + 134217728 ))"
dump_path="${release_dir}/database.dump"
info "Creating PostgreSQL logical backup at ${dump_path}"
compose exec -T db pg_dump -U "$(database_user)" -Fc -d "$(database_name)" > "${dump_path}"
[[ -s "${dump_path}" ]] || die "Database dump is empty."
if [[ "${storage_mode}" == "manifest" || "${storage_mode}" == "full" ]]; then
    root="$(storage_root)"
    [[ -d "${root}" ]] || die "Storage root does not exist."
    storage_bytes="$(du -sb "${root}" | awk '{print $1}')"
    file_count="$(find "${root}" -type f -print | wc -l | tr -d ' ')"
    printf '{\n  "path": "%s",\n  "total_bytes": %s,\n  "file_count": %s\n}\n' "${root}" "${storage_bytes}" "${file_count}" > "${release_dir}/storage-manifest.json"
fi
if [[ "${storage_mode}" == "full" ]]; then
    root="$(storage_root)"
    ensure_free_bytes "${RELEASES_DIR}" "$(( $(du -sb "${root}" | awk '{print $1}') + 134217728 ))"
    tar -cf "${release_dir}/storage.tar" -C "${root}" .
    [[ -s "${release_dir}/storage.tar" ]] || die "Storage backup is empty."
fi
write_manifest "${release_dir}" "${reason}" "${storage_mode}"
info "BACKUP_DIR=${release_dir}"
info "Run scripts/release/verify_backup.sh ${release_dir} before release use."
