"""publisher su job_source_link

Il portale su cui l'annuncio e' davvero pubblicato, quando la fonte e' un
aggregatore. Senza, in dashboard un annuncio LinkedIn e uno Indeed compaiono
entrambi come "jsearch": il nome del tubo invece di quello della sorgente.

Il valore c'e' gia' dentro ``raw``, ma leggerlo di li' significherebbe far
decomprimere a Postgres un JSONB intero per estrarne una parola, su ogni riga di
ogni pagina della dashboard. Il backfill qui sotto lo fa una volta sola, per gli
annunci gia' in tabella.

Revision ID: c2f1a83bd704
Revises: 1d17861f09dc
Create Date: 2026-08-29 10:00:00.000000+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c2f1a83bd704"
down_revision: Union[str, Sequence[str], None] = "1d17861f09dc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("job_source_link", sa.Column("publisher", sa.String(length=120), nullable=True))

    # Backfill dai payload gia' salvati. `nullif` evita di scrivere stringhe
    # vuote, che in dashboard sarebbero un'etichetta invisibile invece di un
    # ritorno al nome dell'adapter.
    op.execute(
        """
        UPDATE job_source_link
           SET publisher = left(nullif(btrim(raw ->> 'job_publisher'), ''), 120)
         WHERE raw ? 'job_publisher'
        """
    )
    op.execute(
        """
        UPDATE job_source_link
           SET publisher = left(nullif(btrim(raw ->> 'source'), ''), 120)
         WHERE publisher IS NULL
           AND source_id IN (SELECT id FROM source WHERE adapter = 'jooble')
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("job_source_link", "publisher")
