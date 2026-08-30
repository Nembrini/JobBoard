"""Notifiche verso Filippo (Fase 8.3/8.4): il digest email a fine run.

Distinto da ``jobboard.apply``, che parla con i siti degli ATS: qui il
destinatario e' sempre e solo l'account Gmail configurato in
``worker/.env``. La Fase 9 (lettura IMAP delle risposte dei recruiter) vive
altrove perche' legge la stessa casella con uno scopo opposto — non scrive.
"""

from __future__ import annotations

from .digest import DigestEmail, build_digest, send_digest
from .mailer import MailError, send_html_email
from .settings import NOTIFICATION_SETTING_KEY, NotificationSettings, load_notification_settings

__all__ = [
    "NOTIFICATION_SETTING_KEY",
    "DigestEmail",
    "MailError",
    "NotificationSettings",
    "build_digest",
    "load_notification_settings",
    "send_digest",
    "send_html_email",
]
