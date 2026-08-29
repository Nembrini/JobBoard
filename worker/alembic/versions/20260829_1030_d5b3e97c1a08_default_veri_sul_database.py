"""default veri sul database, non solo nell'ORM

Trentacinque colonne ``NOT NULL`` avevano un default dichiarato nei modelli e
**nessun default nel database**. Il ``default=`` di SQLAlchemy e' lato Python:
lo applica l'ORM al momento del flush, e nel DDL non finisce mai. Finche' a
scrivere era solo il worker la differenza non si vedeva; la prima ``INSERT``
arrivata da Vercel — un task accodato dalla pagina CV — e' morta cosi':

    null value in column "progress" of relation "task"
    violates not-null constraint

Non era un caso isolato ma la forma di tutto lo schema: un ``INSERT`` che non
passa dall'ORM fallisce su una qualsiasi di queste colonne. Riguarda l'intera
Fase 5, dove la dashboard accoda i task, e la Fase 7, dove crea le candidature.

Da qui in avanti i modelli dichiarano ``server_default`` accanto a ``default``:
il primo e' il contratto del database, il secondo resta perche' l'ORM possa
riempire l'oggetto in memoria senza rileggerlo.

Revision ID: d5b3e97c1a08
Revises: c2f1a83bd704
Create Date: 2026-08-29 10:30:00.000000+00:00

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d5b3e97c1a08"
down_revision: Union[str, Sequence[str], None] = "c2f1a83bd704"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: Generato dai modelli, non battuto a mano: i valori sono esattamente quelli
#: che l'ORM applicherebbe, quindi le due strade non possono divergere.
DEFAULTS: tuple[tuple[str, str, str], ...] = (
    ("candidate_profile", "work_authorization", "'{}'::jsonb"),
    ("candidate_profile", "willing_to_relocate", "false"),
    ("candidate_profile", "salary_currency", "'EUR'"),
    ("candidate_profile", "languages", "'{}'::jsonb"),
    ("candidate_profile", "ats_answers", "'{}'::jsonb"),
    ("job", "work_mode", "'unknown'"),
    ("job", "salary_is_stated", "false"),
    ("job", "contract_type", "'unknown'"),
    ("job", "seniority", "'unknown'"),
    ("job", "ats_type", "'unknown'"),
    ("job", "is_active", "true"),
    ("profile", "reviewed", "false"),
    ("source", "enabled", "true"),
    ("source", "config", "'{}'::jsonb"),
    ("source", "rate_limit_per_min", "30"),
    ("task", "status", "'pending'"),
    ("task", "payload", "'{}'::jsonb"),
    ("task", "progress", "0"),
    ("task", "attempts", "0"),
    ("task", "max_attempts", "3"),
    ("job_requirements", "must_have", "'{}'"),
    ("job_requirements", "nice_to_have", "'{}'"),
    ("job_requirements", "tech_stack", "'{}'"),
    ("job_requirements", "languages_required", "'{}'::jsonb"),
    ("job_requirements", "red_flags", "'{}'"),
    ("match", "gaps", "'{}'"),
    ("match", "reached_stage", "0"),
    ("match", "status", "'new'"),
    ("run", "jobs_fetched", "0"),
    ("run", "jobs_new", "0"),
    ("run", "jobs_duplicate", "0"),
    ("run", "api_calls", "0"),
    ("application", "status", "'draft'"),
    ("application", "was_dry_run", "false"),
    ("application", "screenshots", "'{}'"),
)


def upgrade() -> None:
    """Upgrade schema."""
    for tabella, colonna, valore in DEFAULTS:
        op.execute(f'ALTER TABLE "{tabella}" ALTER COLUMN "{colonna}" SET DEFAULT {valore}')


def downgrade() -> None:
    """Downgrade schema."""
    for tabella, colonna, _ in DEFAULTS:
        op.execute(f'ALTER TABLE "{tabella}" ALTER COLUMN "{colonna}" DROP DEFAULT')
