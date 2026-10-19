"""acciones de admin: registro de quien retira un veredicto a mano, cuando y por que (ADR 0049)

Revision ID: 0021
Revises: 0018
"""

import sqlalchemy as sa

from alembic import op

revision = "0021"
down_revision = "0018"
branch_labels = None
depends_on = None

ACTIONS = "('retirar-veredicto', 'restituir-veredicto')"


def upgrade() -> None:
    op.create_table(
        "admin_action",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user", sa.String(length=60), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("target", sa.String(length=60), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("before", sa.String(length=16), nullable=True),
        sa.CheckConstraint(f"action IN {ACTIONS}", name="ck_admin_action_action"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_admin_action_at", "admin_action", ["at"])


def downgrade() -> None:
    op.drop_index("ix_admin_action_at", table_name="admin_action")
    op.drop_table("admin_action")
