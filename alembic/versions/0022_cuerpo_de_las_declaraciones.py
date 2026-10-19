"""cuerpo de las declaraciones: texto del comunicado del canal web, descargado una vez (ADR 0051)

Revision ID: 0022
Revises: 0021
"""

import sqlalchemy as sa

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("political_statement") as batch:
        batch.add_column(sa.Column("body", sa.Text(), nullable=True))
        batch.add_column(sa.Column("body_status", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("body_fetched_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("political_statement") as batch:
        batch.drop_column("body_fetched_at")
        batch.drop_column("body_status")
        batch.drop_column("body")
