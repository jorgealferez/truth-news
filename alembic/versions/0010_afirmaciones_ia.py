"""afirmaciones: extractor (reglas | ia) y periodo citado (ADR 0019)

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("claim", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("extractor", sa.String(length=8), nullable=False, server_default="reglas")
        )
        batch_op.add_column(sa.Column("period", sa.String(length=20), nullable=True))
        batch_op.create_check_constraint("ck_claim_extractor", "extractor IN ('reglas', 'ia')")


def downgrade() -> None:
    with op.batch_alter_table("claim", schema=None) as batch_op:
        batch_op.drop_constraint("ck_claim_extractor", type_="check")
        batch_op.drop_column("period")
        batch_op.drop_column("extractor")
