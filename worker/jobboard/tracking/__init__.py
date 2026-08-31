"""Tracking post-candidatura (Fase 9): stati, lettura IMAP, classificazione, follow-up.

Legge la stessa casella Gmail di ``jobboard.notify`` ma con lo scopo opposto —
non scrive mai un'email verso un ATS, solo verso l'account di Filippo (il
promemoria di follow-up). Vedi il modulo ``imap_reader`` per lo scope
ristretto della lettura.
"""

from __future__ import annotations

from .classifier import STATUS_BY_CLASS, EmailClassification, classify, next_status
from .followup import (
    WAITING_STATUSES,
    DueApplication,
    FollowUpEmail,
    build_followup_email,
    find_due,
    send_followup_reminders,
)
from .imap_reader import (
    CandidateEmail,
    EmailHeader,
    ImapError,
    ImapMailbox,
    MailboxClient,
    fetch_candidate_emails,
    looks_related,
    select_related,
)
from .settings import TRACKING_SETTING_KEY, TrackingSettings, load_tracking_settings

__all__ = [
    "STATUS_BY_CLASS",
    "TRACKING_SETTING_KEY",
    "WAITING_STATUSES",
    "CandidateEmail",
    "DueApplication",
    "EmailClassification",
    "EmailHeader",
    "FollowUpEmail",
    "ImapError",
    "ImapMailbox",
    "MailboxClient",
    "TrackingSettings",
    "build_followup_email",
    "classify",
    "fetch_candidate_emails",
    "find_due",
    "load_tracking_settings",
    "looks_related",
    "next_status",
    "select_related",
    "send_followup_reminders",
]
