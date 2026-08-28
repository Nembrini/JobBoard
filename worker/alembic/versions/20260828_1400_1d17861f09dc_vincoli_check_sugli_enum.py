"""vincoli CHECK sugli enum

Revision ID: 1d17861f09dc
Revises: a49e5eab0b9b
Create Date: 2026-08-28 14:00:00.137379+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1d17861f09dc"
down_revision: Union[str, Sequence[str], None] = "a49e5eab0b9b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Scritti a mano: Alembic non autogenera i vincoli CHECK.
    # Generati dai modelli con uno script, non battuti a mano.
    op.create_check_constraint(
        "ats_type",
        "job",
        "job.ats_type IN ('greenhouse', 'lever', 'ashby', 'workable', 'recruitee', 'smartrecruiters', 'workday', 'taleo', 'other', 'unknown')",
    )
    op.create_check_constraint(
        "contract_type",
        "job",
        "job.contract_type IN ('permanent', 'fixed_term', 'contract', 'internship', 'apprenticeship', 'part_time', 'unknown')",
    )
    op.create_check_constraint(
        "salary_period",
        "job",
        "job.salary_period IN ('hourly', 'daily', 'monthly', 'yearly')",
    )
    op.create_check_constraint(
        "seniority",
        "job",
        "job.seniority IN ('intern', 'junior', 'mid', 'senior', 'lead', 'principal', 'unknown')",
    )
    op.create_check_constraint(
        "work_mode",
        "job",
        "job.work_mode IN ('on_site', 'hybrid', 'remote', 'unknown')",
    )
    op.create_check_constraint(
        "task_status",
        "task",
        "task.status IN ('pending', 'running', 'done', 'failed', 'cancelled')",
    )
    op.create_check_constraint(
        "task_type",
        "task",
        "task.task_type IN ('run_pipeline', 'generate_cv', 'apply', 'reparse_profile', 'check_email')",
    )
    op.create_check_constraint(
        "run_status",
        "worker_heartbeat",
        "worker_heartbeat.last_run_status IN ('running', 'ok', 'partial', 'failed')",
    )
    op.create_check_constraint(
        "match_status",
        "match",
        "match.status IN ('new', 'seen', 'shortlist', 'hidden', 'applied')",
    )
    op.create_check_constraint(
        "run_status",
        "run",
        "run.status IN ('running', 'ok', 'partial', 'failed')",
    )
    op.create_check_constraint(
        "application_status",
        "application",
        "application.status IN ('draft', 'cv_ready', 'approved', 'needs_human', 'submitted', 'failed', 'withdrawn', 'acknowledged', 'interview', 'rejected', 'offer')",
    )
    op.create_check_constraint(
        "application_tier",
        "application",
        "application.tier IN ('a_auto', 'b_assisted', 'c_manual')",
    )
    op.create_check_constraint(
        "application_event_type",
        "application_event",
        "application_event.event_type IN ('created', 'cv_generated', 'approved', 'submitted', 'submit_failed', 'email_received', 'status_changed', 'follow_up_due')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "ck_application_event_application_event_type", "application_event", type_="check"
    )
    op.drop_constraint("ck_application_application_tier", "application", type_="check")
    op.drop_constraint("ck_application_application_status", "application", type_="check")
    op.drop_constraint("ck_run_run_status", "run", type_="check")
    op.drop_constraint("ck_match_match_status", "match", type_="check")
    op.drop_constraint("ck_worker_heartbeat_run_status", "worker_heartbeat", type_="check")
    op.drop_constraint("ck_task_task_type", "task", type_="check")
    op.drop_constraint("ck_task_task_status", "task", type_="check")
    op.drop_constraint("ck_job_work_mode", "job", type_="check")
    op.drop_constraint("ck_job_seniority", "job", type_="check")
    op.drop_constraint("ck_job_salary_period", "job", type_="check")
    op.drop_constraint("ck_job_contract_type", "job", type_="check")
    op.drop_constraint("ck_job_ats_type", "job", type_="check")
