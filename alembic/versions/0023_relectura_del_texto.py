"""relectura del texto completo: cuantas veces se releyo y revisiones de cuerpo (ADR 0052)

Revision ID: 0023
Revises: 0021
"""

import sqlalchemy as sa

from alembic import op

revision = "0023"
down_revision = "0021"
branch_labels = None
depends_on = None

FIELDS = "('title', 'summary', 'content')"
OLD_FIELDS = "('title', 'summary')"


def upgrade() -> None:
    with op.batch_alter_table("article", schema=None) as batch_op:
        batch_op.add_column(sa.Column("content_checks", sa.Integer(), server_default="0", nullable=False))
    with op.batch_alter_table("article_revision", schema=None) as batch_op:
        batch_op.drop_constraint("ck_article_revision_field", type_="check")
        batch_op.create_check_constraint("ck_article_revision_field", f"field IN {FIELDS}")


def downgrade() -> None:
    op.execute("DELETE FROM article_revision WHERE field = 'content'")
    with op.batch_alter_table("article_revision", schema=None) as batch_op:
        batch_op.drop_constraint("ck_article_revision_field", type_="check")
        batch_op.create_check_constraint("ck_article_revision_field", f"field IN {OLD_FIELDS}")
    with op.batch_alter_table("article", schema=None) as batch_op:
        batch_op.drop_column("content_checks")
