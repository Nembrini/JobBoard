"""Promemoria di follow-up dopo N giorni di silenzio (Fase 9.4).

**Il silenzio si misura da quando la candidatura è partita davvero**
(``application.submitted_at``), non da quando il worker ha controllato la
posta l'ultima volta. ``last_email_checked_at`` esiste per un motivo diverso —
è la finestra ``SINCE`` della prossima ricerca IMAP, in ``imap_reader`` — e
usarlo anche qui azzererebbe il conteggio a ogni controllo, che con un
controllo al giorno vorrebbe dire non superare mai la soglia.

**Un solo promemoria per silenzio, non uno al giorno.** Una volta che
``follow_up_due_at`` è scritto, la stessa candidatura non ricompare in
:func:`find_due` finché qualcosa non lo azzera — una risposta vera la sposta
fuori da :data:`WAITING_STATUSES`, o un intervento a mano dalla pagina
Candidature. Un promemoria ripetuto ogni giorno per la stessa attesa
insegnerebbe a ignorarlo, lo stesso principio del digest della Fase 8.3.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from html import escape

from ..config import Settings
from ..models import Application, Job
from ..models.enums import ApplicationStatus
from ..notify.mailer import send_html_email
from .settings import TrackingSettings

log = logging.getLogger(__name__)

#: Stati per cui un silenzio prolungato ha senso. ``NEEDS_HUMAN`` non compare:
#: a quello stadio la candidatura non è ancora stata spedita davvero — aspetta
#: un click in dashboard, non una risposta dell'azienda — e sollecitare
#: un'azienda che non ha ricevuto niente sarebbe un promemoria sul nulla.
WAITING_STATUSES = frozenset(
    {ApplicationStatus.SUBMITTED, ApplicationStatus.ACKNOWLEDGED, ApplicationStatus.INTERVIEW}
)


@dataclass(frozen=True)
class DueApplication:
    """Una candidatura silenziosa da abbastanza giorni da meritare un promemoria."""

    application_id: int
    job_id: int
    title: str
    company: str
    days_silent: int


def find_due(
    applications: list[tuple[Application, Job]], *, tracking: TrackingSettings, now: dt.datetime
) -> list[DueApplication]:
    """Le candidature da segnare oggi come ``follow_up_due_at``.

    Puro: non tocca il database, non spedisce niente. Il chiamante
    (``handlers.check_email``) scrive la colonna e l'evento sulle righe che
    tornano da qui, nella stessa transazione in cui ha già in mano gli
    oggetti — la stessa separazione fra calcolo e persistenza di
    ``notify.digest.build_digest``.
    """
    soglia = dt.timedelta(days=tracking.follow_up_after_days)
    dovute: list[DueApplication] = []
    for candidatura, job in applications:
        if candidatura.status not in WAITING_STATUSES:
            continue
        if candidatura.follow_up_due_at is not None:
            # Già segnalata per questo silenzio: aspetta che qualcosa la
            # sblocchi (una risposta vera, o un intervento a mano) prima di
            # segnalarla una seconda volta.
            continue
        if candidatura.submitted_at is None:  # pragma: no cover - lo stato lo implica gia'
            continue
        silenzio = now - candidatura.submitted_at
        if silenzio < soglia:
            continue
        dovute.append(
            DueApplication(
                application_id=candidatura.id,
                job_id=job.id,
                title=job.title,
                company=job.company,
                days_silent=silenzio.days,
            )
        )
    return dovute


@dataclass(frozen=True)
class FollowUpEmail:
    subject: str
    html: str
    text: str
    count: int


def build_followup_email(due: list[DueApplication], public_app_url: str) -> FollowUpEmail | None:
    """Nessuna mail vuota, stesso principio di ``notify.digest.build_digest``."""
    if not due:
        return None

    ordinate = sorted(due, key=lambda d: d.days_silent, reverse=True)
    plurale = "candidatura ferma" if len(ordinate) == 1 else "candidature ferme"
    oggetto = f"JobBoard — {len(ordinate)} {plurale} da un po'"

    righe_html = "\n".join(_riga_html(d, public_app_url) for d in ordinate)
    html = _TEMPLATE.format(
        oggetto=escape(oggetto), righe=righe_html, app_url=escape(public_app_url)
    )
    testo = "\n".join(_riga_testo(d, public_app_url) for d in ordinate)
    text = f"{oggetto}:\n\n{testo}\n\n{public_app_url}/candidature\n"

    return FollowUpEmail(subject=oggetto, html=html, text=text, count=len(ordinate))


def send_followup_reminders(
    tracking: TrackingSettings, due: list[DueApplication], settings: Settings
) -> FollowUpEmail | None:
    """Spedisce il promemoria se il tracciamento è attivo e c'è qualcosa da dire.

    Solleva :class:`~jobboard.notify.mailer.MailError` se l'invio fallisce —
    sta al chiamante decidere che un promemoria non partito non deve far
    fallire un ``check_email`` che ha comunque già scritto gli stati e gli
    eventi sul database.
    """
    if not tracking.enabled or not due:
        return None

    email = build_followup_email(due, settings.public_app_url)
    if email is None:
        return None

    send_html_email(
        settings,
        to_addr=settings.gmail_address,
        subject=email.subject,
        html=email.html,
        text=email.text,
    )
    log.info("promemoria di follow-up inviato: %d candidature", email.count)
    return email


def _riga_html(d: DueApplication, base_url: str) -> str:
    link = f"{base_url}/candidature"
    return (
        "<tr>"
        f'<td style="padding:10px 0;border-bottom:1px solid #e5e5e5">'
        f'<a href="{escape(link)}" style="font-weight:600;text-decoration:none;color:#111827">'
        f"{escape(d.title)}</a>"
        f'<br><span style="color:#6b7280;font-size:13px">{escape(d.company)}</span>'
        "</td>"
        f'<td style="padding:10px 0;border-bottom:1px solid #e5e5e5;text-align:right;'
        f'white-space:nowrap;color:#111827">{d.days_silent} giorni</td>'
        "</tr>"
    )


def _riga_testo(d: DueApplication, base_url: str) -> str:
    return f"- {d.title} @ {d.company} — {d.days_silent} giorni senza risposta"


#: Stesso template minimo del digest (``notify/digest.py``): colonna singola,
#: nessun CSS esterno, per lo stesso motivo — i client di posta lo bloccano.
_TEMPLATE = """<!doctype html>
<html lang="it">
<body style="margin:0;padding:24px;background:#f9fafb;font-family:-apple-system,
  BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#111827">
  <table role="presentation" width="100%" style="max-width:560px;margin:0 auto">
    <tr><td style="padding-bottom:16px">
      <h1 style="font-size:18px;margin:0">{oggetto}</h1>
      <p style="color:#6b7280;font-size:13px;margin:6px 0 0">Nessuna risposta da un po'.</p>
    </td></tr>
    {righe}
    <tr><td style="padding-top:20px">
      <a href="{app_url}/candidature" style="color:#2563eb;text-decoration:none;font-size:13px">
        Apri le candidature →</a>
    </td></tr>
  </table>
</body>
</html>
"""
