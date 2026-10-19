"""traducciones: titulares traducidos con IA, una fila por articulo e idioma (ADR 0017)

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "article_translation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("lang", sa.String(length=8), nullable=False),
        sa.Column("title", sa.String(length=600), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["article_id"], ["article.id"], name="fk_article_translation_article_id", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("article_id", "lang", name="uq_article_translation_article_lang"),
    )


def downgrade() -> None:
    op.drop_table("article_translation")
