"""Comandi della CLI, raggruppati per area."""

from .apply import apply_app
from .backup import backup_app
from .costs import costs_app
from .cv import cv_app
from .email import email_app
from .jobs import ingest_command, sources_app
from .matching import match_command, matches_app
from .profile import candidate_app, info_app, profile_app
from .worker import work_app

__all__ = [
    "apply_app",
    "backup_app",
    "candidate_app",
    "costs_app",
    "cv_app",
    "email_app",
    "info_app",
    "ingest_command",
    "match_command",
    "matches_app",
    "profile_app",
    "sources_app",
    "work_app",
]
