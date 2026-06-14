"""rework projects jobs labels

Revision ID: 20260604_0004
Revises: 20260604_0003
Create Date: 2026-06-04 00:04:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260604_0004"
down_revision: str | None = "20260604_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))

    op.add_column("jobs", sa.Column("project_id", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("name", sa.String(length=255), nullable=True))
    op.add_column("jobs", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.create_foreign_key("fk_jobs_project_id_projects", "jobs", "projects", ["project_id"], ["id"], ondelete="CASCADE")
    op.execute(
        """
        UPDATE jobs
        SET
            project_id = tasks.project_id,
            name = tasks.name
        FROM tasks
        WHERE jobs.task_id = tasks.id
        """
    )
    op.execute("UPDATE jobs SET name = CONCAT('Job ', id) WHERE name IS NULL")
    op.alter_column("jobs", "name", nullable=False)

    op.add_column("images", sa.Column("job_id", sa.Integer(), nullable=True))
    op.add_column("images", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.create_foreign_key("fk_images_job_id_jobs", "images", "jobs", ["job_id"], ["id"], ondelete="CASCADE")
    op.execute(
        """
        UPDATE images
        SET job_id = ranked_jobs.job_id
        FROM (
            SELECT DISTINCT ON (task_id)
                task_id,
                id AS job_id
            FROM jobs
            WHERE task_id IS NOT NULL
            ORDER BY task_id, id
        ) AS ranked_jobs
        WHERE images.task_id = ranked_jobs.task_id
        """
    )

    op.add_column("labels", sa.Column("job_id", sa.Integer(), nullable=True))
    op.add_column("labels", sa.Column("shape_type", sa.String(length=32), server_default="polygon", nullable=False))
    op.add_column("labels", sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False))
    op.add_column("labels", sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.add_column("labels", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.alter_column("labels", "project_id", nullable=True)
    op.create_foreign_key("fk_labels_job_id_jobs", "labels", "jobs", ["job_id"], ["id"], ondelete="CASCADE")
    op.create_unique_constraint("uq_labels_job_name", "labels", ["job_id", "name"])
    op.execute(
        """
        INSERT INTO labels (project_id, job_id, name, color, shape_type, sort_order, created_at, updated_at)
        SELECT
            NULL,
            jobs.id,
            labels.name,
            labels.color,
            COALESCE(labels.shape_type, 'polygon'),
            ROW_NUMBER() OVER (PARTITION BY jobs.id ORDER BY labels.id) - 1,
            now(),
            now()
        FROM jobs
        JOIN labels ON labels.project_id = jobs.project_id AND labels.job_id IS NULL
        WHERE jobs.project_id IS NOT NULL
        """
    )
    op.execute(
        """
        WITH label_map AS (
            SELECT
                annotations.id AS annotation_id,
                new_labels.id AS new_label_id
            FROM annotations
            JOIN labels AS old_labels ON old_labels.id = annotations.label_id
            JOIN jobs ON jobs.id = annotations.job_id
            JOIN labels AS new_labels
                ON new_labels.job_id = jobs.id
                AND new_labels.name = old_labels.name
            WHERE old_labels.job_id IS NULL
        )
        UPDATE annotations
        SET label_id = label_map.new_label_id
        FROM label_map
        WHERE annotations.id = label_map.annotation_id
        """
    )

    op.add_column("annotations", sa.Column("attributes", sa.JSON(), nullable=True))
    op.add_column("annotations", sa.Column("z_order", sa.Integer(), server_default="0", nullable=False))
    op.add_column("annotations", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))


def downgrade() -> None:
    op.drop_column("annotations", "updated_at")
    op.drop_column("annotations", "z_order")
    op.drop_column("annotations", "attributes")

    op.drop_constraint("uq_labels_job_name", "labels", type_="unique")
    op.drop_constraint("fk_labels_job_id_jobs", "labels", type_="foreignkey")
    op.execute("DELETE FROM labels WHERE project_id IS NULL")
    op.alter_column("labels", "project_id", nullable=False)
    op.drop_column("labels", "updated_at")
    op.drop_column("labels", "created_at")
    op.drop_column("labels", "sort_order")
    op.drop_column("labels", "shape_type")
    op.drop_column("labels", "job_id")

    op.drop_constraint("fk_images_job_id_jobs", "images", type_="foreignkey")
    op.drop_column("images", "updated_at")
    op.drop_column("images", "job_id")

    op.drop_constraint("fk_jobs_project_id_projects", "jobs", type_="foreignkey")
    op.drop_column("jobs", "updated_at")
    op.drop_column("jobs", "name")
    op.drop_column("jobs", "project_id")

    op.drop_column("projects", "updated_at")
