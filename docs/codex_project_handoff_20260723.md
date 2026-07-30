# Codex Project Handoff - 2026-07-23

This document records operational context that is useful when continuing this project in a new Codex window. It intentionally avoids secrets and does not contain database passwords, tokens, private URLs, or patient data.

## Project

- Path: `/data1/zhangyuzhu/code/autoannotate/medical-annotation-mvp-gpu`
- Branch at last handoff: `main`
- Current production-like services:
  - Backend: conda + tmux, Uvicorn on port `8000`
  - Frontend: Docker Compose, port `5173`
  - Database: Docker Compose Postgres service `db`, container `med-annotate-gpu-db`, host port `5433 -> 5432`
- Do not assume backend runs correctly in Docker with GPU. The user explicitly said backend should run through the original tmux + conda environment because Docker cannot use GPU in this environment.
- Frontend deployment through Docker Compose is allowed when frontend changes are tested.

## Hard Safety Boundaries

- Do not run `git reset`, `git clean`, `git checkout -- .`, or `git restore .`.
- Do not delete or clean `backups/`.
- Do not delete, move, rewrite, or re-encode real videos.
- Do not change permissions/RBAC unless explicitly requested.
- Do not restart database.
- Do not restart backend unless explicitly approved.
- Do not add migrations unless explicitly approved.
- Do not create Phase Annotation Sets, Phase Segments, Skill Assessments, Skill Scores, or Skill Evidence unless explicitly approved for the specific task.
- Git push is prohibited unless the user explicitly asks for GitHub upload.

## Git Context

- A local commit was created before the iCO rubric work:
  - `1eec949 Add research phase skill i18n and playback speed`
- That commit includes the Phase/Skill feature work, i18n, playback speed, release verifier/checklist, and tests.
- After that commit, current uncommitted work from the iCO rubric task includes:
  - `backend/scripts/data/ico_cataract_skill_rubric_zh_cn.py`
  - `backend/scripts/seed_ico_cataract_skill_rubric.py`
  - `backend/tests/test_seed_ico_cataract_skill_rubric.py`
  - `frontend/src/components/research/SkillScoreForm.vue`
  - `frontend/tests/skillScoreFormDescription.test.ts`
  - This handoff file
- Current untracked files/directories that should not be casually committed:
  - `backups/` contains database dump files
  - `ICO评分表格翻译版本.xlsx` is the user-provided source spreadsheet

## Database And Migrations

- Production DB was migrated to Alembic revision `20260722_0015`.
- `20260722_0014` created Phase tables.
- `20260722_0015` created Skill tables.
- Skill table count is 6, not 7:
  - `research_skill_rubrics`
  - `research_skill_criteria`
  - `research_skill_criterion_phase_labels`
  - `research_skill_assessments`
  - `research_skill_scores`
  - `research_skill_evidence`
- Phase table count is 4:
  - `research_phase_protocols`
  - `research_phase_labels`
  - `research_phase_annotation_sets`
  - `research_phase_segments`
- Default Phase Protocol/Labels already exist in DB from migration:
  - Protocol count expected: 1
  - Label count expected: 13

## Important Environment Detail

- Running Alembic from project root with `-c backend/alembic.ini` can fail because `script_location = alembic` is relative to the current directory.
- Correct host-style Alembic command usually needs `cd backend`, for example:

```bash
cd /data1/zhangyuzhu/code/autoannotate/medical-annotation-mvp-gpu/backend
POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5433 ../../conda_envs/sam/bin/python -m alembic -c alembic.ini current
```

- In this session, direct host SQLAlchemy/psycopg2 connection to `127.0.0.1:5433` failed with a bare `psycopg2.OperationalError`, even though:
  - Backend API could access DB normally.
  - `docker compose exec -T db psql ...` worked.
  - `curl http://127.0.0.1:8000/api/research/skill-rubrics` worked.
- For the iCO seed, the safe working path was to call the already-running backend API with `--api-base http://127.0.0.1:8000/api/research`.
- Python socket access may be blocked by sandbox; if a command using Python HTTP fails with `PermissionError: [Errno 1] Operation not permitted`, rerun with escalation.

## Backend Service

- Backend process observed:
  - `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`
- Backend start scripts:
  - `scripts/backend_tmux_start.sh`
  - default uses `scripts/start_backend_host.sh`
- `scripts/start_backend_host.sh` exports:
  - `POSTGRES_HOST=127.0.0.1`
  - `POSTGRES_PORT=5433`
  - `POSTGRES_DB=med_annotate`
  - `POSTGRES_USER=med_annotate`
  - `POSTGRES_PASSWORD` set internally, do not print it in reports
  - `PYTHONPATH=${PROJECT_ROOT}/backend:${SAM2_ROOT}:...`
- Backend API base in actual deployment is:
  - `http://127.0.0.1:8000/api/research`
  - Not `/api/v1/research`; `/api/v1/research/skill-rubrics` returned 404.

## Frontend Service

- Frontend Docker Compose service:
  - service name: `frontend`
  - container: `med-annotate-gpu-frontend`
  - URL: `http://127.0.0.1:5173`
- SPA routes checked successfully after latest deploy:
  - `/research`
  - `/research/videos/2/skills`
- Last frontend deploy only restarted/recreated the frontend container, not backend or db.

## iCO Cataract Skill Rubric

The user explicitly approved adding the iCO cataract surgery skill rubric to the real Skill Assessment system.

Rubric metadata:

- Name: `iCO 白内障手术技能评分量表（中文翻译版）`
- Version: `1`
- Status after import: `active`
- Rubric ID after import: `1`
- Creator: `zhangyuzhu`
- `phase_protocol_id`: `null`
- All criteria are `scope=overall`.

Why `single_choice`:

- Each criterion has fixed 0/2/3/4/5 levels with distinct Chinese scoring descriptions.
- `integer_scale` would lose the per-level descriptions.

Option value detail:

- `options_json` model type allows `Any`, but actual score validation in `research_skill_service._validate_score_value` requires `single_choice` submitted value to be a `str`.
- Therefore the seed uses string values: `"0"`, `"2"`, `"3"`, `"4"`, `"5"`.
- Do not change these to numeric values unless backend score validation is also intentionally changed.

0-point handling:

- `0 分` is a real rubric score meaning not applicable / done by instructor.
- It is not system N/A.
- `allow_na=false` for all 20 criteria.

Seed files:

- Data file: `backend/scripts/data/ico_cataract_skill_rubric_zh_cn.py`
- Seed script: `backend/scripts/seed_ico_cataract_skill_rubric.py`
- Test: `backend/tests/test_seed_ico_cataract_skill_rubric.py`

Seed script behavior:

- Default is dry-run unless `--apply` is provided.
- Supports SQLAlchemy/session mode and API mode.
- API mode was used for the real import:

```bash
PYTHONPATH=backend ../conda_envs/sam/bin/python \
  backend/scripts/seed_ico_cataract_skill_rubric.py \
  --api-base http://127.0.0.1:8000/api/research \
  --creator-username zhangyuzhu \
  --apply \
  --activate
```

Dry-run output before import:

- `action=would_create`
- `planned_criteria_count=20`
- `database_writes=0`

Apply output:

- `action=created`
- `rubric_id=1`
- `rubric_status=active`
- `database_writes=21`
- fingerprint matched:
  - `ae273842f48aadcb40b9ec2799f3dc1d520b4a2dd3c6699cbb1e9b2a0aafd15b`

Second execution:

- `action=already_exists`
- `database_writes=0`
- fingerprint matched

Confirmed DB counts after import:

- `research_skill_rubrics`: 1
- `research_skill_criteria`: 20
- `research_skill_assessments`: 0
- `research_skill_scores`: 0
- `research_skill_evidence`: 0

## iCO Criteria Keys

The 20 iCO criteria keys in display order are:

1. `sterile_draping`
2. `incision_and_side_port`
3. `viscoelastic_use_and_injection`
4. `capsulorhexis_flap_and_control`
5. `capsulorhexis_shape_and_integrity`
6. `hydrodissection_and_nucleus_rotation`
7. `phaco_and_second_instrument_insertion`
8. `instrument_use_and_globe_stability`
9. `nucleus_grooving`
10. `nucleus_rotation_and_fragmentation`
11. `fragment_phacoemulsification`
12. `cortex_irrigation_aspiration`
13. `iol_implantation_and_positioning`
14. `wound_closure_and_sealing`
15. `astigmatism_globe_rotation_and_corneal_folds`
16. `globe_centering_under_microscope`
17. `conjunctival_and_corneal_tissue_handling`
18. `intraocular_spatial_awareness`
19. `iris_protection`
20. `overall_surgical_flow`

## Frontend iCO Display Fix

- `SkillScoreForm.vue` originally rendered `criterion.description` in a normal `<p>`, so line breaks were collapsed.
- A minimal scoped CSS fix was added:
  - `.skill-criterion-description`
  - `white-space: pre-line`
  - `overflow-wrap: anywhere`
  - `line-height: 1.6`
  - `max-height: 18rem`
  - `overflow: auto`
- No `v-html` is used.
- Test added: `frontend/tests/skillScoreFormDescription.test.ts`

## Global i18n

- Vue i18n is already integrated.
- Locale storage key:
  - `medical-annotation-locale`
- Supported locales:
  - `zh-CN`
  - `en-US`
- Built-in Phase Protocol/Label names are translated in display helpers only.
- User-created data such as Rubric name, Criterion name, comments, video filenames should not be machine-translated.

## Video Playback Speed

- Global playback speed storage key:
  - `medical-annotation-video-playback-rate`
- Shared util:
  - `frontend/src/utils/videoPlaybackRate.ts`
- Shared composable:
  - `frontend/src/composables/useVideoPlaybackRate.ts`
- Shared component:
  - `frontend/src/components/VideoPlaybackRateControl.vue`
- Supported values:
  - `0.25`, `0.5`, `0.75`, `1`, `1.25`, `1.5`, `2`, `3`, `4`
- Real visible video players audited and covered:
  - Frame Annotation
  - Phase Annotation
  - Skill Assessment
- Changing speed must not alter `currentTime`, paused state, URL query, selected segment, selected criterion/evidence, or backend data.

## Useful Validation Commands

Backend seed tests:

```bash
../conda_envs/sam/bin/python -m pytest backend/tests/test_seed_ico_cataract_skill_rubric.py -q
```

Skill regression:

```bash
../conda_envs/sam/bin/python -m pytest \
  backend/tests/test_research_skill_rubrics.py \
  backend/tests/test_research_skill_assessments.py \
  backend/tests/test_research_skill_scores.py \
  backend/tests/test_research_skill_validation.py \
  backend/tests/test_research_skill_api.py \
  -q
```

Frontend tests:

```bash
docker compose run --rm --no-deps frontend \
  sh -lc 'node --test tests/*.test.ts'
```

Vue type check:

```bash
docker compose run --rm --no-deps frontend \
  npx vue-tsc -b --pretty false
```

Frontend build:

```bash
docker compose build frontend
```

Frontend deploy only:

```bash
docker compose up -d frontend
```

Do not restart backend/db unless explicitly approved.

## Last Known Passing Tests

After iCO seed and frontend display fix:

- `backend/tests/test_seed_ico_cataract_skill_rubric.py`: 10 passed
- Skill regression subset: 42 passed
- Frontend node tests: 92 passed
- `vue-tsc`: passed
- `docker compose build frontend`: passed
- Known build warnings:
  - VueUse `/* #__PURE__ */` Rollup annotation warning
  - Vite large chunk warning over 500 KB

## Last Known Service Checks

- `docker compose ps` showed:
  - `med-annotate-gpu-db` up and healthy, port `5433`
  - `med-annotate-gpu-frontend` up, port `5173`
- Backend API check:
  - `GET http://127.0.0.1:8000/api/research/skill-rubrics` returned 200
- Frontend SPA checks:
  - `GET http://127.0.0.1:5173/research` returned 200
  - `GET http://127.0.0.1:5173/research/videos/2/skills` returned 200

## Manual Browser Checks Still Needed

No browser-based visual/interaction validation was claimed for the iCO rubric. The user should manually verify:

1. Open `http://<server-ip>:5173/research`.
2. Enter a video's Skill Assessment page.
3. Open Create Assessment dialog.
4. Confirm it no longer shows `No data`.
5. Confirm `iCO 白内障手术技能评分量表（中文翻译版） v1` is selectable.
6. Do not create an assessment unless intentionally testing real data creation.
7. Open Rubric Manager.
8. Confirm Rubric status is active.
9. Confirm criteria count is 20.
10. Open several criteria and verify long descriptions preserve line breaks and do not cause horizontal overflow.
11. Check Chinese/English locale switching does not translate the custom Rubric/Criteria names.

## Known Caveats

- The iCO seed script's API mode is what was used for production import because direct host psycopg2 connection failed in this environment.
- The seed script still has SQLAlchemy/session mode for tests and environments where direct DB access works.
- `database_writes=21` in API mode represents 1 rubric creation + 20 criteria creation. Activation changes status but is not counted separately in that value.
- There are existing real Phase records from earlier browser operations:
  - phase annotation sets count observed: 1
  - phase segments count observed: 3
- Do not assume the DB is empty except for Skill Assessment objects, which were 0 before iCO import.

## If Continuing Immediately

Recommended next steps:

1. Run `git status --short`.
2. Decide whether to commit the iCO seed/frontend display changes.
3. Exclude `backups/` from any commit unless the user explicitly asks otherwise.
4. Treat the Excel file as source material; ask before committing it.
5. If user wants browser validation, do not create Skill Assessment automatically unless they approve writing test assessment data.
