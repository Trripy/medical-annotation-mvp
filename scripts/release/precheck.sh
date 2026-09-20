#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

is_dry_run && info "DRY_RUN: precheck remains read-only."
[[ -d "${PROJECT_ROOT}/.git" ]] || die "Not a Git checkout: ${PROJECT_ROOT}"
read_version >/dev/null
git_commit >/dev/null
if [[ -n "$(git -C "${PROJECT_ROOT}" status --porcelain)" && "${ALLOW_DIRTY_RELEASE:-0}" != "1" ]]; then
    die "Production release aborted: dirty worktree. Set ALLOW_DIRTY_RELEASE=1 only with explicit approval."
fi
command -v docker >/dev/null || die "docker is unavailable."
compose config -q
compose ps --status running db | grep -q db || die "Compose database service is not running."
compose exec -T db pg_isready -U "$(database_user)" -d "$(database_name)" >/dev/null || die "PostgreSQL is not ready."
require_backend_python
local_storage="$(storage_root)"
[[ -d "${local_storage}" && -r "${local_storage}" ]] || die "LOCAL_STORAGE_ROOT is unavailable or unreadable."
ffmpeg_bin="${RESEARCH_VIDEO_FFMPEG_BINARY:-$(configured_ffmpeg)}"
[[ -n "${ffmpeg_bin}" ]] || ffmpeg_bin="$(command -v ffmpeg || true)"
[[ -n "${ffmpeg_bin}" ]] || ffmpeg_bin="$(dirname "$(backend_python)")/ffmpeg"
[[ -n "${ffmpeg_bin}" && -x "${ffmpeg_bin}" ]] || die "ffmpeg is unavailable."
head_revision="$(database_head)"
current_revision="$(database_current)"
info "App version: $(read_version)"
info "Git: $(git_describe)"
info "DB current: ${current_revision}"
info "DB head: ${head_revision}"
info "Storage: ${local_storage}"
info "Free space: $(df -h "${PROJECT_ROOT}" | awk 'NR == 2 { print $4 }')"
info "Frontend: compose configuration valid"
info "Backend: $(backend_python)"
