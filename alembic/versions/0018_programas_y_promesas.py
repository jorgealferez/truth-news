"""programas y promesas: documentos de los partidos, compromisos citados y su cumplimiento (ADR 0037)

Revision ID: 0018
Revises: 0017
"""

import sqlalchemy as sa

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

KINDS = "('programa', 'investidura', 'acuerdo')"
STATUSES = "('enlazado', 'importado', 'bloqueado', 'error')"
EXTRACTORS = "('reglas', 'ia')"
CHECKS = "('cumplida', 'parcial', 'en-curso', 'no-cumplida', 'sin-datos')"


def upgrade() -> None:
    op.create_table(
        "program",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor", sa.String(length=40), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("kind", sa.String(length=12), server_default="programa", nullable=False),
        sa.Column("election_kind", sa.String(length=16), nullable=False),
        sa.Column("election_year", sa.Integer(), nullable=False),
        sa.Column("election", sa.String(length=60), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("url_hash", sa.String(length=64), nullable=False),
        sa.Column("found_on", sa.String(length=1000), nullable=False),
        sa.Column("status", sa.String(length=12), server_default="enlazado", nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("n_pages", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.Column("found_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"kind IN {KINDS}", name="ck_program_kind"),
        sa.CheckConstraint(f"status IN {STATUSES}", name="ck_program_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url_hash", name="uq_program_url_hash"),
    )
    op.create_index(
        "ix_program_actor_election", "program", ["country", "actor", "election_kind", "election_year"]
    )
    op.create_table(
        "promise",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("program_id", sa.Integer(), nullable=True),
        sa.Column("statement_id", sa.Integer(), nullable=True),
        sa.Column("actor", sa.String(length=40), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("election_kind", sa.String(length=16), nullable=True),
        sa.Column("election_year", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("topic", sa.String(length=40), nullable=True),
        sa.Column("extractor", sa.String(length=8), server_default="reglas", nullable=False),
        sa.Column("made_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"extractor IN {EXTRACTORS}", name="ck_promise_extractor"),
        sa.CheckConstraint("(program_id IS NULL) <> (statement_id IS NULL)", name="ck_promise_one_source"),
        sa.ForeignKeyConstraint(
            ["program_id"], ["program.id"], name="fk_promise_program_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["statement_id"],
            ["political_statement.id"],
            name="fk_promise_statement_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("actor", "text_hash", name="uq_promise_actor_text"),
    )
    op.create_index(
        "ix_promise_actor_election", "promise", ["country", "actor", "election_kind", "election_year"]
    )
    op.create_index("ix_promise_topic", "promise", ["topic"])
    op.create_table(
        "promise_check",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("promise_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("method", sa.String(length=40), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"status IN {CHECKS}", name="ck_promise_check_status"),
        sa.ForeignKeyConstraint(
            ["promise_id"], ["promise.id"], name="fk_promise_check_promise_id", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("promise_id", "method", name="uq_promise_check_method"),
    )


def downgrade() -> None:
    op.drop_table("promise_check")
    op.drop_index("ix_promise_topic", table_name="promise")
    op.drop_index("ix_promise_actor_election", table_name="promise")
    op.drop_table("promise")
    op.drop_index("ix_program_actor_election", table_name="program")
    op.drop_table("program")
