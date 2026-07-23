"""create research phase tables

Revision ID: 20260722_0014
Revises: 20260630_0013
Create Date: 2026-07-22 00:14:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260722_0014"
down_revision: str | None = "20260630_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_phase_protocols",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'active'")),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('draft', 'active', 'archived')", name="ck_research_phase_protocols_status"),
        sa.CheckConstraint("version >= 1", name="ck_research_phase_protocols_version_positive"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version", name="uq_research_phase_protocols_name_version"),
    )
    op.create_index(op.f("ix_research_phase_protocols_id"), "research_phase_protocols", ["id"], unique=False)

    op.create_table(
        "research_phase_labels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("protocol_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("color", sa.String(length=16), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("shortcut", sa.String(length=32), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("display_order >= 0", name="ck_research_phase_labels_display_order_non_negative"),
        sa.CheckConstraint(
            "shortcut IS NULL OR length(trim(shortcut)) > 0",
            name="ck_research_phase_labels_shortcut_not_blank",
        ),
        sa.ForeignKeyConstraint(["protocol_id"], ["research_phase_protocols.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("protocol_id", "key", name="uq_research_phase_labels_protocol_key"),
        sa.UniqueConstraint("protocol_id", "name", name="uq_research_phase_labels_protocol_name"),
        sa.UniqueConstraint("protocol_id", "shortcut", name="uq_research_phase_labels_protocol_shortcut"),
    )
    op.create_index(
        "ix_research_phase_labels_protocol_display_order",
        "research_phase_labels",
        ["protocol_id", "display_order"],
        unique=False,
    )
    op.create_index(op.f("ix_research_phase_labels_id"), "research_phase_labels", ["id"], unique=False)

    op.create_table(
        "research_phase_annotation_sets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("protocol_id", sa.Integer(), nullable=False),
        sa.Column("annotator_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted', 'reviewed', 'locked')",
            name="ck_research_phase_annotation_sets_status",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_research_phase_annotation_sets_revision_positive"),
        sa.ForeignKeyConstraint(["annotator_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["protocol_id"], ["research_phase_protocols.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["video_id"], ["research_videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "video_id",
            "protocol_id",
            "annotator_id",
            name="uq_research_phase_annotation_sets_video_protocol_annotator",
        ),
    )
    op.create_index(op.f("ix_research_phase_annotation_sets_id"), "research_phase_annotation_sets", ["id"], unique=False)

    op.create_table(
        "research_phase_segments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("annotation_set_id", sa.Integer(), nullable=False),
        sa.Column("phase_label_id", sa.Integer(), nullable=False),
        sa.Column("start_frame", sa.Integer(), nullable=False),
        sa.Column("end_frame_exclusive", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("start_frame >= 0", name="ck_research_phase_segments_start_frame_non_negative"),
        sa.CheckConstraint(
            "end_frame_exclusive IS NULL OR end_frame_exclusive > start_frame",
            name="ck_research_phase_segments_end_after_start",
        ),
        sa.CheckConstraint(
            "source IN ('manual', 'model_suggestion', 'model_corrected', 'imported')",
            name="ck_research_phase_segments_source",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_research_phase_segments_confidence_range",
        ),
        sa.ForeignKeyConstraint(["annotation_set_id"], ["research_phase_annotation_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["phase_label_id"], ["research_phase_labels.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_research_phase_segments_annotation_set_start_frame",
        "research_phase_segments",
        ["annotation_set_id", "start_frame"],
        unique=False,
    )
    op.create_index(
        "ix_research_phase_segments_annotation_set_phase_label",
        "research_phase_segments",
        ["annotation_set_id", "phase_label_id"],
        unique=False,
    )

    bind = op.get_bind()
    protocols_table = sa.table(
        "research_phase_protocols",
        sa.column("id", sa.Integer()),
        sa.column("name", sa.String()),
        sa.column("version", sa.Integer()),
        sa.column("description", sa.Text()),
        sa.column("status", sa.String()),
        sa.column("is_default", sa.Boolean()),
        sa.column("created_by_id", sa.Integer()),
    )
    labels_table = sa.table(
        "research_phase_labels",
        sa.column("protocol_id", sa.Integer()),
        sa.column("key", sa.String()),
        sa.column("name", sa.String()),
        sa.column("color", sa.String()),
        sa.column("display_order", sa.Integer()),
        sa.column("shortcut", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("is_active", sa.Boolean()),
    )

    bind.execute(
        protocols_table.insert().values(
            name="Cataract Surgery Phases",
            version=1,
            description="Default cataract surgery phase protocol.",
            status="active",
            is_default=True,
            created_by_id=None,
        )
    )
    protocol_id = bind.execute(
        sa.select(protocols_table.c.id).where(
            protocols_table.c.name == "Cataract Surgery Phases",
            protocols_table.c.version == 1,
        )
    ).scalar_one()

    op.bulk_insert(
        labels_table,
        [
            {"protocol_id": protocol_id, "key": "idle", "name": "Idle", "color": "#64748b", "display_order": 0, "shortcut": None, "description": None, "is_active": True},
            {"protocol_id": protocol_id, "key": "incision", "name": "Incision", "color": "#ff7a1a", "display_order": 1, "shortcut": None, "description": None, "is_active": True},
            {"protocol_id": protocol_id, "key": "viscoelastic", "name": "Viscoelastic Injection", "color": "#1f9fe5", "display_order": 2, "shortcut": None, "description": None, "is_active": True},
            {"protocol_id": protocol_id, "key": "capsulorhexis", "name": "Capsulorhexis", "color": "#22c55e", "display_order": 3, "shortcut": None, "description": None, "is_active": True},
            {"protocol_id": protocol_id, "key": "hydrodissection", "name": "Hydrodissection", "color": "#8b5cf6", "display_order": 4, "shortcut": None, "description": None, "is_active": True},
            {"protocol_id": protocol_id, "key": "phacoemulsification", "name": "Phacoemulsification", "color": "#ef4444", "display_order": 5, "shortcut": None, "description": None, "is_active": True},
            {"protocol_id": protocol_id, "key": "irrigation_aspiration", "name": "Irrigation / Aspiration", "color": "#eab308", "display_order": 6, "shortcut": None, "description": None, "is_active": True},
            {"protocol_id": protocol_id, "key": "capsule_polishing", "name": "Capsule Polishing", "color": "#14b8a6", "display_order": 7, "shortcut": None, "description": None, "is_active": True},
            {"protocol_id": protocol_id, "key": "lens_implantation", "name": "Lens Implantation", "color": "#ec4899", "display_order": 8, "shortcut": None, "description": None, "is_active": True},
            {"protocol_id": protocol_id, "key": "lens_positioning", "name": "Lens Positioning", "color": "#6366f1", "display_order": 9, "shortcut": None, "description": None, "is_active": True},
            {"protocol_id": protocol_id, "key": "viscoelastic_suction", "name": "Viscoelastic Suction", "color": "#84cc16", "display_order": 10, "shortcut": None, "description": None, "is_active": True},
            {"protocol_id": protocol_id, "key": "anterior_chamber_flushing", "name": "Anterior Chamber Flushing", "color": "#06b6d4", "display_order": 11, "shortcut": None, "description": None, "is_active": True},
            {"protocol_id": protocol_id, "key": "tonifying_antibiotics", "name": "Tonifying / Antibiotics", "color": "#a16207", "display_order": 12, "shortcut": None, "description": None, "is_active": True},
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_research_phase_segments_annotation_set_phase_label",
        table_name="research_phase_segments",
    )
    op.drop_index(
        "ix_research_phase_segments_annotation_set_start_frame",
        table_name="research_phase_segments",
    )
    op.drop_table("research_phase_segments")

    op.drop_index(op.f("ix_research_phase_annotation_sets_id"), table_name="research_phase_annotation_sets")
    op.drop_table("research_phase_annotation_sets")

    op.drop_index(op.f("ix_research_phase_labels_id"), table_name="research_phase_labels")
    op.drop_index("ix_research_phase_labels_protocol_display_order", table_name="research_phase_labels")
    op.drop_table("research_phase_labels")

    op.drop_index(op.f("ix_research_phase_protocols_id"), table_name="research_phase_protocols")
    op.drop_table("research_phase_protocols")
