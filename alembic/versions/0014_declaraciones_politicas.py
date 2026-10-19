"""declaraciones politicas: lo que publican los partidos en sus canales oficiales (ADR 0024)

Revision ID: 0014
Revises: 0011
"""

import sqlalchemy as sa

from alembic import op

revision = "0014"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "political_statement",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor", sa.String(length=40), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("url_hash", sa.String(length=64), nullable=False),
        sa.Column("text", sa.String(length=600), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("story_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "channel IN ('web', 'bluesky', 'mastodon', 'telegram')", name="ck_political_statement_channel"
        ),
        sa.ForeignKeyConstraint(
            ["story_id"], ["story.id"], name="fk_political_statement_story_id", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url_hash", name="uq_political_statement_url_hash"),
    )
    with op.batch_alter_table("political_statement", schema=None) as batch_op:
        batch_op.create_index("ix_political_statement_country_published", ["country", "published_at"])
        batch_op.create_index("ix_political_statement_story_id", ["story_id"])


def downgrade() -> None:
    with op.batch_alter_table("political_statement", schema=None) as batch_op:
        batch_op.drop_index("ix_political_statement_story_id")
        batch_op.drop_index("ix_political_statement_country_published")
    op.drop_table("political_statement")
