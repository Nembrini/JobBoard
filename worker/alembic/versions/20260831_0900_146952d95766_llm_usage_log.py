"""llm_usage_log

Revision ID: 146952d95766
Revises: 7a3f5c9e2b41
Create Date: 2026-08-31 09:00:00.000000+00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "146952d95766"
down_revision: Union[str, Sequence[str], None] = "7a3f5c9e2b41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Fase 10.2: la tabella che alimenta ``jb costs show`` e la dashboard dei
    costi. Una riga per invocazione aggregata (una run di matching, una
    generazione CV, ...), non per singola chiamata — vedi il commento su
    ``jobboard.models.ops.LLMUsageLog``.
    """
    op.create_table(
        "llm_usage_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "purpose",
            sa.Enum(
                "match_scoring",
                "cv_structure",
                "cv_tailor",
                "email_classify",
                name="llm_usage_purpose",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("reference_id", sa.Integer(), nullable=True),
        sa.Column("batch_id", sa.String(length=36), nullable=True),
        sa.CheckConstraint(
            "purpose IN ('match_scoring', 'cv_structure', 'cv_tailor', 'email_classify')",
            name=op.f("ck_llm_usage_log_llm_usage_purpose"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_usage_log")),
    )
    op.create_index(
        "ix_llm_usage_log_occurred", "llm_usage_log", ["occurred_at"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_llm_usage_log_occurred", table_name="llm_usage_log")
    op.drop_table("llm_usage_log")
