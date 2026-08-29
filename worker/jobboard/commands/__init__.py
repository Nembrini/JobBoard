"""Comandi della CLI, raggruppati per area."""

from .jobs import ingest_command, sources_app
from .matching import match_command, matches_app
from .profile import candidate_app, profile_app
from .worker import work_app

__all__ = [
    "candidate_app",
    "ingest_command",
    "match_command",
    "matches_app",
    "profile_app",
    "sources_app",
    "work_app",
]
