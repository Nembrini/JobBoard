"""applicant_info: il pool libero di informazioni candidatura

Revision ID: 9c4a1e6f0b32
Revises: 146952d95766
Create Date: 2026-08-31 11:00:00.000000+00:00

Tabella nuova, singleton come ``profile`` e ``candidate_profile`` (vedi
``jobboard.schemas.applicant_info`` per il perche' e' un oggetto a se' e non
un'estensione di uno dei due). ``items`` nasce gia' con ``server_default``:
a differenza delle trentacinque colonne sistemate in ``d5b3e97c1a08`` questa
tabella e' scritta da subito con il contratto giusto, non c'e' debito da
ripagare.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9c4a1e6f0b32"
down_revision: Union[str, Sequence[str], None] = "146952d95766"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "applicant_info",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "items",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name=op.f("ck_applicant_info_singleton")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_applicant_info")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("applicant_info")
