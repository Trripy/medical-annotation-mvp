#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

[[ "${1:-}" == "--check" ]] || die "Only safe inspection is implemented: rollback_code.sh --check <git-ref>"
target="${2:?Missing target Git ref.}"
target_version="$(git -C "${PROJECT_ROOT}" show "${target}:VERSION" 2>/dev/null)" || die "Target does not contain VERSION: ${target}"
info "Current version: $(read_version)"
info "Target version: ${target_version}"
info "Current database revision: $(database_current)"
info "Current database head: $(database_head)"
warn "No checkout, restart, migration, or rollback was performed. Verify schema compatibility before an operator performs a code rollback."
