"""pieza de hilo: piece.thread_id y topic_id nullable con check de padre (ADR 0020)

Revision ID: 0011
Revises: 0013
"""

import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("piece", schema=None) as batch_op:
        batch_op.add_column(sa.Column("thread_id", sa.Integer(), nullable=True))
        batch_op.alter_column("topic_id", existing_type=sa.Integer(), nullable=True)
        batch_op.create_foreign_key("fk_piece_thread_id", "thread", ["thread_id"], ["id"], ondelete="CASCADE")
        batch_op.create_index(batch_op.f("ix_piece_thread_id"), ["thread_id"], unique=False)
        batch_op.create_check_constraint("ck_piece_parent", "topic_id IS NOT NULL OR thread_id IS NOT NULL")


def downgrade() -> None:
    op.execute("DELETE FROM piece WHERE thread_id IS NOT NULL")
    with op.batch_alter_table("piece", schema=None) as batch_op:
        batch_op.drop_constraint("ck_piece_parent", type_="check")
        batch_op.drop_index(batch_op.f("ix_piece_thread_id"))
        batch_op.drop_constraint("fk_piece_thread_id", type_="foreignkey")
        batch_op.alter_column("topic_id", existing_type=sa.Integer(), nullable=False)
        batch_op.drop_column("thread_id")
