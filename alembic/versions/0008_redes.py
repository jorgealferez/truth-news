"""redes: cola y registro de publicaciones en redes sociales (ADR 0018)

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "social_post",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("network", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("ref_id", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("link", sa.String(length=1000), nullable=False),
        sa.Column("image_url", sa.String(length=1000), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=True),
        sa.Column("external_url", sa.String(length=1000), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "network IN ('x', 'bluesky', 'mastodon', 'telegram')", name="ck_social_post_network"
        ),
        sa.CheckConstraint("kind IN ('historia', 'hilo', 'verificacion')", name="ck_social_post_kind"),
        sa.CheckConstraint("status IN ('prueba', 'enviado', 'error')", name="ck_social_post_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("network", "kind", "ref_id", name="uq_social_post_network_ref"),
    )
    with op.batch_alter_table("social_post", schema=None) as batch_op:
        batch_op.create_index("ix_social_post_network_created", ["network", "created_at"])


def downgrade() -> None:
    with op.batch_alter_table("social_post", schema=None) as batch_op:
        batch_op.drop_index("ix_social_post_network_created")
    op.drop_table("social_post")
