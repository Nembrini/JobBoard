"""prepared e prepare_failed negli eventi candidatura

Revision ID: 7a3f5c9e2b41
Revises: d5b3e97c1a08
Create Date: 2026-08-30 12:00:00.000000+00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7a3f5c9e2b41"
down_revision: Union[str, Sequence[str], None] = "d5b3e97c1a08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Fase 7: il router non fa piu' un invio via API per il Tier A (vedi
    ARCHITECTURE.md), quindi ne' il Tier A ne' il Tier B possono scrivere
    ``submitted`` da soli — si fermano entrambi dopo aver precompilato il
    form. ``prepared``/``prepare_failed`` sono i due nuovi esiti di quel
    passaggio, scritti a mano come tutti i CHECK degli enum: vedi la nota in
    ``1d17861f09dc``.

    ``op.drop_constraint`` passa il nome attraverso la stessa naming
    convention di ``Base.metadata`` (vedi ``env.py``): il nome **gia'**
    prefissato non e' quello che il vincolo ha davvero sul database, e' il
    "token" a cui la convenzione ``"ck": "ck_%(table_name)s_%(constraint_name)s"``
    riaggiunge il prefisso una seconda volta, superando i 63 caratteri e
    troncando con un hash — la migration non e' mai riuscita su nessun
    database reale per questo. Il nome giusto da passare e' quello **senza**
    ``ck_``/nome tabella davanti: lo stesso che ``1d17861f09dc`` ha passato a
    ``create_check_constraint`` quando ha creato il vincolo che qui si
    sostituisce.
    """
    op.drop_constraint("application_event_type", "application_event", type_="check")
    op.create_check_constraint(
        "application_event_type",
        "application_event",
        "application_event.event_type IN ('created', 'cv_generated', 'approved', 'prepared', "
        "'prepare_failed', 'submitted', 'submit_failed', 'email_received', 'status_changed', "
        "'follow_up_due')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("application_event_type", "application_event", type_="check")
    op.create_check_constraint(
        "application_event_type",
        "application_event",
        "application_event.event_type IN ('created', 'cv_generated', 'approved', 'submitted', "
        "'submit_failed', 'email_received', 'status_changed', 'follow_up_due')",
    )
