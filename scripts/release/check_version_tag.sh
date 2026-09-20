#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

tag="${1:?Usage: check_version_tag.sh vMAJOR.MINOR.PATCH}"
[[ "${tag}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "Tag must use vMAJOR.MINOR.PATCH."
[[ "${tag#v}" == "$(read_version)" ]] || die "VERSION ($(read_version)) does not match ${tag}."
info "Tag ${tag} matches VERSION. This script does not create tags."
