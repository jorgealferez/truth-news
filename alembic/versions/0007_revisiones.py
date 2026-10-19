"""revisiones: cambios de titular y extracto detectados entre rastreos (ADR 0015)

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "article_revision",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("outlet_id", sa.Integer(), nullable=False),
        sa.Column("crawl_run_id", sa.Integer(), nullable=True),
        sa.Column("field", sa.String(length=16), nullable=False),
        sa.Column("before", sa.Text(), nullable=False),
        sa.Column("after", sa.Text(), nullable=False),
        sa.Column("before_hash", sa.String(length=64), nullable=False),
        sa.Column("after_hash", sa.String(length=64), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("field IN ('title', 'summary')", name="ck_article_revision_field"),
        sa.ForeignKeyConstraint(
            ["article_id"], ["article.id"], name="fk_article_revision_article_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["outlet_id"], ["outlet.id"], name="fk_article_revision_outlet_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["crawl_run_id"], ["crawl_run.id"], name="fk_article_revision_crawl_run_id", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("article_revision", schema=None) as batch_op:
        batch_op.create_index("ix_article_revision_article_detected", ["article_id", "detected_at"])
        batch_op.create_index("ix_article_revision_outlet_detected", ["outlet_id", "detected_at"])


def downgrade() -> None:
    with op.batch_alter_table("article_revision", schema=None) as batch_op:
        batch_op.drop_index("ix_article_revision_outlet_detected")
        batch_op.drop_index("ix_article_revision_article_detected")
    op.drop_table("article_revision")
