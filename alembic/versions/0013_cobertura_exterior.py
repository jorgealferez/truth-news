"""cobertura exterior: enlaces de cada historia con articulos de medios de otros paises (ADR 0022)

Revision ID: 0013
Revises: 0010
"""

import sqlalchemy as sa

from alembic import op

revision = "0013"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "story_abroad",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("story_id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("similarity", sa.Float(), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["story_id"], ["story.id"], name="fk_story_abroad_story_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["article_id"], ["article.id"], name="fk_story_abroad_article_id", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("story_id", "article_id", name="uq_story_abroad_story_article"),
    )


def downgrade() -> None:
    op.drop_table("story_abroad")
