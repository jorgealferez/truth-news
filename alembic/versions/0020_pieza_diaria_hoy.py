"""pieza diaria: kind `hoy` en la cola de publicaciones (ADR 0048)

Revision ID: 0020
Revises: 0021
"""

from alembic import op

revision = "0020"
down_revision = "0021"
branch_labels = None
depends_on = None

BASE = "'historia', 'hilo', 'verificacion'"


def _kind_check(values: str) -> None:
    with op.batch_alter_table("social_post", schema=None) as batch_op:
        batch_op.drop_constraint("ck_social_post_kind", type_="check")
        batch_op.create_check_constraint("ck_social_post_kind", f"kind IN ({values})")


def upgrade() -> None:
    _kind_check(BASE + ", 'hoy'")


def downgrade() -> None:
    op.execute("DELETE FROM social_post WHERE kind = 'hoy'")
    _kind_check(BASE)
