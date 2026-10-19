"""redes en ingles: cuentas `*_en` en la cola de publicaciones (ADR 0033)

Revision ID: 0018
Revises: 0016
"""

from alembic import op

revision = "0018"
down_revision = "0016"
branch_labels = None
depends_on = None

BASE = "'x', 'bluesky', 'mastodon', 'telegram'"
WITH_EN = BASE + ", 'x_en', 'bluesky_en', 'mastodon_en', 'telegram_en'"


def _network_check(values: str) -> None:
    with op.batch_alter_table("social_post", schema=None) as batch_op:
        batch_op.drop_constraint("ck_social_post_network", type_="check")
        batch_op.create_check_constraint("ck_social_post_network", f"network IN ({values})")


def upgrade() -> None:
    _network_check(WITH_EN)


def downgrade() -> None:
    op.execute("DELETE FROM social_post WHERE network LIKE '%\\_en' ESCAPE '\\'")
    _network_check(BASE)
