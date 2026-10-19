"""declaraciones juzgadas: afirmaciones de los partidos con su veredicto, aparte de las noticias (ADR 0030)

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

VERDICTS = "('verdadero', 'impreciso', 'falso', 'enganoso', 'sin-datos')"


def upgrade() -> None:
    op.create_table(
        "statement_check",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("statement_id", sa.Integer(), nullable=False),
        sa.Column("speaker_entity_id", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("indicator", sa.String(length=60), nullable=False),
        sa.Column("geo", sa.String(length=8), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=True),
        sa.Column("period", sa.String(length=20), nullable=True),
        sa.Column("extractor", sa.String(length=8), server_default="reglas", nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("method", sa.String(length=40), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"verdict IN {VERDICTS}", name="ck_statement_check_verdict"),
        sa.ForeignKeyConstraint(
            ["statement_id"],
            ["political_statement.id"],
            name="fk_statement_check_statement_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["speaker_entity_id"],
            ["entity.id"],
            name="fk_statement_check_speaker_entity_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("statement_id", "indicator", "geo", "value", name="uq_statement_check_claim"),
    )
    op.create_index("ix_statement_check_speaker", "statement_check", ["speaker_entity_id"])
    op.create_index("ix_statement_check_method", "statement_check", ["method"])


def downgrade() -> None:
    op.drop_index("ix_statement_check_method", table_name="statement_check")
    op.drop_index("ix_statement_check_speaker", table_name="statement_check")
    op.drop_table("statement_check")
