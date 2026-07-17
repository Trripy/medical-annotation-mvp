#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONDA_ENV="${CONDA_ENV:-${PROJECT_ROOT}/../conda_envs/sam}"
SAM2_ROOT="${SAM2_REPO_ROOT:-${PROJECT_ROOT}/../sam2}"

if [[ ! -x "${CONDA_ENV}/bin/python" ]]; then
  echo "Conda env python not found: ${CONDA_ENV}/bin/python" >&2
  echo "Set CONDA_ENV=/path/to/sam if the sam environment is elsewhere." >&2
  exit 1
fi

if [[ ! -d "${SAM2_ROOT}" ]]; then
  echo "SAM2 repo not found: ${SAM2_ROOT}" >&2
  exit 1
fi

export POSTGRES_HOST="${POSTGRES_HOST:-127.0.0.1}"
export POSTGRES_PORT="${POSTGRES_PORT:-5433}"
export POSTGRES_DB="${POSTGRES_DB:-med_annotate}"
export POSTGRES_USER="${POSTGRES_USER:-med_annotate}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-med_annotate}"
export LOCAL_STORAGE_ROOT="${LOCAL_STORAGE_ROOT:-${PROJECT_ROOT}/storage}"
export BACKEND_CORS_ORIGINS="${BACKEND_CORS_ORIGINS:-*}"
export SAM2_REPO_ROOT="${SAM2_ROOT}"
export SAM2_CHECKPOINT="${SAM2_CHECKPOINT:-${SAM2_ROOT}/checkpoints/sam2.1_hiera_large.pt}"
export SAM2_MODEL_CFG="${SAM2_MODEL_CFG:-configs/sam2.1/sam2.1_hiera_l.yaml}"
export SAM2_DEVICE="${SAM2_DEVICE:-cuda}"
export SAM2_LOAD_ON_STARTUP="${SAM2_LOAD_ON_STARTUP:-true}"
export SAM2_POLYGON_EPSILON_RATIO="${SAM2_POLYGON_EPSILON_RATIO:-0.002}"
export SAM2_MIN_MASK_AREA="${SAM2_MIN_MASK_AREA:-100}"
export SAM2_MASK_THRESHOLD="${SAM2_MASK_THRESHOLD:-0}"
export SAM2_MAX_HOLE_AREA="${SAM2_MAX_HOLE_AREA:-0}"
export SAM2_MAX_SPRINKLE_AREA="${SAM2_MAX_SPRINKLE_AREA:-0}"
export PYTHONPATH="${PROJECT_ROOT}/backend:${SAM2_ROOT}:${PYTHONPATH:-}"

mkdir -p "${LOCAL_STORAGE_ROOT}"

cd "${PROJECT_ROOT}/backend"

if [[ "${SKIP_ALEMBIC:-false}" != "true" ]]; then
  echo "Running Alembic migrations against ${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}..."
  "${CONDA_ENV}/bin/alembic" upgrade head
else
  echo "Skipping Alembic migrations because SKIP_ALEMBIC=true"
fi

echo "Starting backend on 0.0.0.0:${BACKEND_PORT:-8000}..."
exec "${CONDA_ENV}/bin/python" -m uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${BACKEND_PORT:-8000}"
