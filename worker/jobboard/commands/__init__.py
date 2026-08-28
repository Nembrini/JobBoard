"""Comandi della CLI, raggruppati per area."""

from .jobs import ingest_command, sources_app
from .profile import candidate_app, profile_app

__all__ = ["candidate_app", "ingest_command", "profile_app", "sources_app"]
