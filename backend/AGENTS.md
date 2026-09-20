# Backend And Database Instructions

PostgreSQL is the source of truth for real Annotation, Phase, Skill, and ResearchVideo data.

- Schema changes require Alembic; never mutate production schema or `alembic_version` manually.
- Prefer additive migrations. Do not run destructive or data-rewriting migrations against production without an explicit release request.
- For model or migration changes, inspect Alembic current and heads first, run the temporary-database migration matrix, and report schema, data, and storage impact.
- Do not automatically rewrite Annotation, Phase, Skill, or ResearchVideo data.
- Production rollback for data/destructive migrations prefers restoring a verified backup, not assuming downgrade is safe.
- Production migrations are only allowed as part of an explicitly requested production deployment.
