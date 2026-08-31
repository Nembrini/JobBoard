"""Comandi della CLI, raggruppati per area."""

from .apply import apply_app
from .cv import cv_app
from .email import email_app
from .jobs import ingest_command, sources_app
from .matching import match_command, matches_app
from .profile import candidate_app, profile_app
from .worker import work_app

__all__ = [
    "apply_app",
    "candidate_app",
    "cv_app",
    "email_app",
    "ingest_command",
    "match_command",
    "matches_app",
    "profile_app",
    "sources_app",
    "work_app",
]
