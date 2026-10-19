"""entidades: personas y entidades con sus menciones, hablante de cada afirmacion y origen (ADR 0028)

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "entity",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=220), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("curated", sa.Boolean(), nullable=False),
        sa.Column("n_mentions", sa.Integer(), nullable=False),
        sa.Column("n_articles", sa.Integer(), nullable=False),
        sa.Column("n_outlets", sa.Integer(), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('persona', 'partido', 'institucion', 'organizacion', 'lugar')", name="ck_entity_kind"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key", name="uq_entity_key"),
    )
    op.create_index("ix_entity_kind_articles", "entity", ["kind", "n_articles"])
    op.create_index("ix_entity_last_seen", "entity", ["last_seen"])
    op.create_table(
        "mention",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("outlet_id", sa.Integer(), nullable=False),
        sa.Column("story_id", sa.Integer(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.CheckConstraint("role IN ('menciona', 'dice')", name="ck_mention_role"),
        sa.ForeignKeyConstraint(
            ["entity_id"], ["entity.id"], name="fk_mention_entity_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["article_id"], ["article.id"], name="fk_mention_article_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["outlet_id"], ["outlet.id"], name="fk_mention_outlet_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["story_id"], ["story.id"], name="fk_mention_story_id", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_id", "article_id", name="uq_mention_entity_article"),
    )
    op.create_index("ix_mention_entity_published", "mention", ["entity_id", "published_at"])
    op.create_index("ix_mention_article", "mention", ["article_id"])
    op.create_index("ix_mention_story", "mention", ["story_id"])
    with op.batch_alter_table("article", schema=None) as batch_op:
        batch_op.add_column(sa.Column("origin", sa.String(length=16), server_default="rss", nullable=False))
        batch_op.add_column(sa.Column("entities_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index("ix_article_entities_at", ["entities_at"])
        batch_op.create_check_constraint("ck_article_origin", "origin IN ('rss', 'archivo')")
    with op.batch_alter_table("claim", schema=None) as batch_op:
        batch_op.add_column(sa.Column("speaker_entity_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_claim_speaker_entity_id", ["speaker_entity_id"])
        batch_op.create_foreign_key(
            "fk_claim_speaker_entity_id", "entity", ["speaker_entity_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("claim", schema=None) as batch_op:
        batch_op.drop_constraint("fk_claim_speaker_entity_id", type_="foreignkey")
        batch_op.drop_index("ix_claim_speaker_entity_id")
        batch_op.drop_column("speaker_entity_id")
    with op.batch_alter_table("article", schema=None) as batch_op:
        batch_op.drop_constraint("ck_article_origin", type_="check")
        batch_op.drop_index("ix_article_entities_at")
        batch_op.drop_column("entities_at")
        batch_op.drop_column("origin")
    op.drop_index("ix_mention_story", table_name="mention")
    op.drop_index("ix_mention_article", table_name="mention")
    op.drop_index("ix_mention_entity_published", table_name="mention")
    op.drop_table("mention")
    op.drop_index("ix_entity_last_seen", table_name="entity")
    op.drop_index("ix_entity_kind_articles", table_name="entity")
    op.drop_table("entity")
