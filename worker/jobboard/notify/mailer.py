"""Invio via SMTP Gmail (Fase 8.3).

Un client minimo apposta: un solo messaggio HTML con ripiego testuale, una
volta al giorno. Non serve una libreria di terze parti per questo.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from ..config import Settings

log = logging.getLogger(__name__)


class MailError(RuntimeError):
    """La mail non e' partita: credenziali mancanti o SMTP irraggiungibile.

    Non e' un :class:`~jobboard.queue.TaskError`: la decide chi chiama, perche'
    un digest mancato non deve far fallire una run che ha comunque raccolto e
    valutato gli annunci — sono gia' salvati quando questo viene sollevato.
    """


def send_html_email(
    settings: Settings, *, to_addr: str, subject: str, html: str, text: str
) -> None:
    """Spedisce un'email HTML, con ``text`` come alternativa per i client che non la rendono.

    Le credenziali sono ``GMAIL_ADDRESS``/``GMAIL_APP_PASSWORD`` — una App
    Password, non la password dell'account: con la verifica in due passaggi
    attiva (il prerequisito annotato in ``docs/ROADMAP.md``) Gmail rifiuta
    l'accesso SMTP con la password normale.
    """
    settings.require("gmail_address", "gmail_app_password")

    messaggio = EmailMessage()
    messaggio["Subject"] = subject
    messaggio["From"] = settings.gmail_address
    messaggio["To"] = to_addr
    messaggio.set_content(text)
    messaggio.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(settings.gmail_address, settings.gmail_app_password.get_secret_value())
            smtp.send_message(messaggio)
    except (OSError, smtplib.SMTPException) as exc:
        raise MailError(f"invio SMTP fallito: {type(exc).__name__}: {exc}") from exc

    log.info("mail inviata a %s: %s", to_addr, subject)
