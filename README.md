# Medical Annotation MVP GPU

A GPU-ready medical image annotation platform with project/job management, frame-by-frame annotation, SAM2-assisted segmentation, export tools, and per-user annotation preferences.

This repository is the GPU deployment variant of the Medical Annotation MVP. The frontend and PostgreSQL run in Docker, while the FastAPI backend runs directly on the host so SAM2 can access the local CUDA environment.

## Features

- Project and job management for multi-image annotation workflows.
- Image upload, thumbnail generation, and local filesystem-backed storage.
- Annotation tools: cursor/edit, rectangle, polygon, and SAM2 prompt-based segmentation.
- SAM2 mask generation with prompt points, box prompts, candidate selection, polygon simplification, mask thresholding, mask area filtering, and hole filling.
- Per-user settings for default tool, frame resume behavior, zoom/pan behavior, shortcuts, SAM2 result edge snapping, and SAM2 default parameters.
- Label management per project/job.
- Frame navigation with URL frame query support and optional per-job last-frame persistence.
- Export support for LabelMe, overlay images, indexed masks, and color masks.
- FastAPI OpenAPI documentation at `/docs`.

## Tech Stack

- Backend: FastAPI, SQLAlchemy, Alembic, PostgreSQL, Pydantic
- Frontend: Vue 3, Vite, TypeScript, Element Plus, Pinia
- Segmentation: SAM2, PyTorch CUDA
- Storage: local filesystem
- Deployment: Docker Compose for PostgreSQL/frontend, host Python environment for GPU backend

## Repository Layout

```text
medical-annotation-mvp-gpu/
  backend/
    app/
      api/                 # FastAPI routes
      core/                # application settings
      db/                  # database session/base
      models/              # SQLAlchemy models
      schemas/             # Pydantic schemas
      services/            # image storage, export, SAM2 service
    alembic/               # database migrations
    requirements.txt
  frontend/
    src/
      components/          # sidebar, canvas, object panel
      stores/              # Pinia stores
      views/               # pages
      utils/
    package.json
  scripts/
    start_backend_gpu.sh   # host backend startup with Alembic migration
    start_frontend.sh      # Docker frontend startup helper
  storage/                 # runtime uploads and generated files, ignored by git
  docker-compose.yml       # PostgreSQL and frontend services
  .env.example
```

## Architecture

```text
Browser
  |
  | http://<host>:5173
  v
Vue frontend container
  |
  | http://<host>:8000/api/...
  v
FastAPI backend on host Python/Conda
  |
  | PostgreSQL on localhost:5433
  v
PostgreSQL container

FastAPI backend
  |
  | CUDA / PyTorch / SAM2 checkpoint
  v
Host GPU
```

The backend is intentionally not containerized in this GPU variant. This avoids CUDA and SAM2 checkpoint access issues inside Docker and lets the backend use the host Conda environment directly.

## Prerequisites

- Linux host with Docker and Docker Compose.
- NVIDIA driver and CUDA-capable GPU for SAM2 acceleration.
- Python/Conda environment with the dependencies in `backend/requirements.txt`.
- SAM2 source repository and checkpoint files available on the host.
- Node.js is only required for local frontend development; Docker can build and run the frontend without a host Node install.

## Configuration

Copy the example environment file if you want shell-based configuration:

```bash
cp .env.example .env
```

Important variables:

```text
POSTGRES_DB=med_annotate
POSTGRES_USER=med_annotate
POSTGRES_PASSWORD=med_annotate
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5433

LOCAL_STORAGE_ROOT=/path/to/medical-annotation-mvp-gpu/storage

CONDA_ENV=/path/to/conda/env
SAM2_REPO_ROOT=/path/to/sam2
SAM2_CHECKPOINT=/path/to/sam2/checkpoints/sam2.1_hiera_large.pt
SAM2_MODEL_CFG=configs/sam2.1/sam2.1_hiera_l.yaml
SAM2_DEVICE=cuda
SAM2_LOAD_ON_STARTUP=true

BACKEND_CORS_ORIGINS=*
```

The startup script provides local defaults, but production or shared deployments should pass explicit environment variables.

## Quick Start

Start the GPU backend:

```bash
cd medical-annotation-mvp-gpu
CONDA_ENV=/path/to/conda/env \
SAM2_REPO_ROOT=/path/to/sam2 \
SAM2_CHECKPOINT=/path/to/sam2/checkpoints/sam2.1_hiera_large.pt \
./scripts/start_backend_gpu.sh
```

The backend script:

- starts PostgreSQL with `docker compose up -d db`;
- waits for PostgreSQL readiness;
- runs `alembic upgrade head`;
- starts `uvicorn app.main:app --host 0.0.0.0 --port 8000`;
- loads SAM2 on startup when `SAM2_LOAD_ON_STARTUP=true`.

Start the frontend in another terminal:

```bash
cd medical-annotation-mvp-gpu
./scripts/start_frontend.sh
```

Or directly:

```bash
docker compose up -d frontend
```

Open:

- Frontend: `http://localhost:5173`
- Backend API root: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/api/v1/health`

For LAN access, replace `localhost` with the server IP.

## Backend Development

Install dependencies in a Python environment:

```bash
cd backend
python -m pip install -r requirements.txt
```

Run migrations:

```bash
cd backend
alembic upgrade head
```

Run the API:

```bash
cd backend
PYTHONPATH="$(pwd)" uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

For GPU usage, make sure `PYTHONPATH` includes the SAM2 repository and the relevant SAM2 environment variables are set.

## Frontend Development

```bash
cd frontend
npm install
npm run dev
```

Build:

```bash
cd frontend
npm run build
```

The frontend automatically resolves the API host from the browser host and port `8000` unless `VITE_API_BASE_URL` is set.

## Database Migrations

Create a migration after model changes:

```bash
cd backend
alembic revision --autogenerate -m "describe change"
```

Apply migrations:

```bash
cd backend
alembic upgrade head
```

The GPU backend startup script runs `alembic upgrade head` automatically.

## SAM2 Notes

The SAM2 prediction endpoint is:

```text
POST /api/sam2/predict
```

The Annotation page sends the current sidebar SAM2 settings with each request. User Settings only control the defaults applied when an annotation page is opened; temporary changes in the Annotation page are preserved within the current page session and are used for Generate Mask.

Useful validation command:

```bash
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.version.cuda)"
```

If `torch.cuda.is_available()` is `False`, verify the NVIDIA driver, CUDA-compatible PyTorch build, and `SAM2_DEVICE`.

## User Settings

Settings are stored per user in the `user_settings` table and exposed through:

```text
GET /api/users/me/settings?username=<username>
PUT /api/users/me/settings
```

Current personalized settings include:

- default annotation tool;
- edge snap threshold;
- polygon edit shortcuts;
- polygon confirm-point shortcut;
- pan shortcut;
- SAM2 Accept next-tool behavior;
- remember last frame per job;
- keep zoom and pan when switching frames;
- SAM2 result edge snapping;
- SAM2 default model, candidate, multimask output, prompt-point visibility, polygon simplification, mask threshold, minimum mask area, and maximum hole area.

Unauthenticated users use frontend defaults.

## Export Formats

Job export endpoints include:

```text
GET /api/jobs/{job_id}/export/labelme
GET /api/jobs/{job_id}/export/overlay
GET /api/jobs/{job_id}/export/indexed-mask
GET /api/jobs/{job_id}/export/color-mask
```

Exports are generated from the saved annotation data for the job.

## Runtime Data

Runtime data is intentionally excluded from git:

- uploaded images;
- thumbnails;
- generated export files;
- PostgreSQL volume data;
- backend/frontend logs;
- Python and Node build/cache artifacts.

Do not commit PHI, patient data, private checkpoints, or local environment files.

## Troubleshooting

Check whether services are running:

```bash
docker compose ps
curl http://localhost:8000/api/v1/health
curl http://localhost:5173/jobs
```

Check backend logs when using the startup script:

```bash
tail -f logs/backend_gpu.log
```

Common issues:

- `SAM2 model loaded ... device=cuda` is missing: verify `SAM2_REPO_ROOT`, `SAM2_CHECKPOINT`, PyTorch CUDA, and `SAM2_DEVICE`.
- Frontend cannot reach backend: verify backend port `8000`, CORS settings, and `VITE_API_BASE_URL`.
- Database errors after pulling new code: run `alembic upgrade head`.
- Old frontend UI after rebuild: hard-refresh the browser with `Ctrl + F5`.

## Publishing To GitHub

Initialize and commit locally:

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
```

Create an empty GitHub repository, then connect and push:

```bash
git remote add origin git@github.com:<owner>/<repo>.git
git push -u origin main
```

If using HTTPS:

```bash
git remote add origin https://github.com/<owner>/<repo>.git
git push -u origin main
```

## Security Notes

This project is an MVP. Before production use:

- replace username-based settings APIs with real authentication and authorization;
- restrict CORS instead of using `*`;
- protect uploaded medical data and exports;
- move secrets out of shell history and committed files;
- review administrator access behavior;
- add backup and retention policies for PostgreSQL and storage.

## License

No license file is included yet. Add a `LICENSE` file before public distribution if the repository should be open source.
