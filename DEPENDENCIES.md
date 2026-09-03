# Dependency Inventory

This file records the project dependencies that are actually used by the checked-in backend and frontend code.

## Backend Python

Install with:

```bash
cd backend
python -m pip install -r requirements.txt
```

The backend imports these external Python modules:

| Imported module | Package in `backend/requirements.txt` | Use |
| --- | --- | --- |
| `fastapi` | `fastapi` | API routing, dependency injection, upload handling, HTTP errors |
| `starlette` | `starlette` | request types and ASGI response primitives used directly by the app/tests |
| `sqlalchemy` | `SQLAlchemy` | ORM models, sessions, queries, migrations support |
| `alembic` | `alembic` | database migrations and migration tests |
| `pydantic` | `pydantic` | API schemas and validation |
| `pydantic_settings` | `pydantic-settings` | environment-backed application settings |
| `PIL` | `Pillow` | image validation, import/export rendering, SAM2 image loading |
| `cv2` | `opencv-python-headless` | research video metadata, frame extraction, thumbnails, mask processing |
| `numpy` | `numpy` | mask arrays and SAM2 post-processing |
| `torch` | `torch` | SAM2 image and video inference |
| `sam2` | external SAM2 source tree | SAM2 model builders and predictors loaded from `SAM2_REPO_ROOT` |
| `pytest` | `pytest` | backend tests |

`python-multipart` is required by FastAPI for the checked-in upload endpoints that use `File`, `Form`, and `UploadFile`.

The application database URL uses the SQLAlchemy `postgresql+psycopg2` driver, so `psycopg2-binary` is the active PostgreSQL adapter. `psycopg` is not required by the current backend code.

`hydra-core`, `iopath`, `tqdm`, and `torchvision` are required by the SAM2 runtime even though the application imports SAM2 through the external source tree.

## External Backend Runtime Tools

These are not Python packages and are therefore not listed in `backend/requirements.txt`:

| Tool | Use |
| --- | --- |
| PostgreSQL | application database |
| ffmpeg / ffprobe | research video trimming and H.264-compatible output validation |
| SAM2 source repository | configured by `SAM2_REPO_ROOT`; default is `../sam2` |
| SAM2 checkpoints | configured by `SAM2_CHECKPOINT` or selected model checkpoint paths |
| NVIDIA driver / CUDA runtime | GPU execution for PyTorch/SAM2 |

## Frontend Node

Install with:

```bash
cd frontend
npm install
```

The frontend imports these npm packages from `frontend/src` and `frontend/tests`:

| Imported package | Declared in `frontend/package.json` | Use |
| --- | --- | --- |
| `vue` | `dependencies` | application framework and composition API |
| `vue-router` | `dependencies` | SPA routing |
| `pinia` | `dependencies` | client-side stores |
| `vue-i18n` | `dependencies` | Chinese/English localization |
| `element-plus` | `dependencies` | UI components and messages/dialogs |
| `@element-plus/icons-vue` | `dependencies` | UI icons |
| `@vitejs/plugin-vue` | `devDependencies` | Vue support for Vite builds |
| `typescript` | `devDependencies` | Type checking |
| `vite` | `devDependencies` | development server and production build |
| `vue-tsc` | `devDependencies` | Vue TypeScript checking |

Frontend tests use Node built-in modules such as `node:test`, `node:assert/strict`, and `node:fs`; they do not require extra npm packages.

There is currently no npm lockfile in the repository. The frontend Dockerfile installs from `package.json` with `npm install`.
