"""Il digest di fine run: i nuovi annunci sopra soglia (Fase 8.3).

"Nuovi" non e' "valutati oggi": e' ``report.new_job_ids``, cioe' annunci che
**prima di questo salvataggio non avevano ancora una riga** ``match``. Senza
questa distinzione un ``jb match --rescore`` — che ripassa dalla rubrica
anche gli annunci gia' visti — spedirebbe una seconda mail identica alla
prima per lo stesso annuncio.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from html import escape
from typing import TYPE_CHECKING

from ..config import Settings
from .mailer import send_html_email
from .settings import NotificationSettings

if TYPE_CHECKING:
    from ..pipeline.match import MatchReport, Scored

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DigestEmail:
    """Il messaggio pronto per essere spedito, o gia' spedito."""

    subject: str
    html: str
    text: str
    count: int


def build_digest(
    report: MatchReport, notification: NotificationSettings, public_app_url: str
) -> DigestEmail | None:
    """Il contenuto del digest, o ``None`` se non c'e' niente da segnalare.

    Nessuna mail vuota: se la run non ha trovato un solo annuncio nuovo sopra
    soglia, il silenzio e' l'informazione corretta, e mandarla lo stesso
    insegnerebbe a ignorare la casella.
    """
    candidati = sorted(
        (
            s
            for s in report.scored
            if s.job.id in report.new_job_ids and s.score >= notification.threshold
        ),
        key=lambda s: s.score,
        reverse=True,
    )
    if not candidati:
        return None

    oggetto_plurale = "nuovo annuncio" if len(candidati) == 1 else "nuovi annunci"
    oggetto = f"JobBoard — {len(candidati)} {oggetto_plurale} sopra soglia"

    righe_html = "\n".join(_riga_html(s, public_app_url) for s in candidati)
    html = _TEMPLATE.format(
        oggetto=escape(oggetto),
        soglia=notification.threshold,
        righe=righe_html,
        app_url=escape(public_app_url),
    )
    testo = "\n".join(_riga_testo(s, public_app_url) for s in candidati)
    text = f"{oggetto} (punteggio >= {notification.threshold}):\n\n{testo}\n\n{public_app_url}\n"

    return DigestEmail(subject=oggetto, html=html, text=text, count=len(candidati))


def send_digest(
    notification: NotificationSettings, report: MatchReport, settings: Settings
) -> DigestEmail | None:
    """Costruisce e spedisce il digest, se attivo e se c'e' qualcosa da dire.

    Solleva :class:`~jobboard.notify.mailer.MailError` se l'invio fallisce:
    sta al chiamante (``handlers.run_pipeline``) decidere che una mail non
    partita non deve far fallire una run che ha comunque salvato raccolta e
    punteggi.
    """
    if not notification.enabled:
        return None

    digest = build_digest(report, notification, settings.public_app_url)
    if digest is None:
        return None

    send_html_email(
        settings,
        to_addr=settings.gmail_address,
        subject=digest.subject,
        html=digest.html,
        text=digest.text,
    )
    log.info("digest inviato: %d annunci", digest.count)
    return digest


def _riga_html(s: Scored, base_url: str) -> str:
    job = s.job
    link = f"{base_url}/annuncio/{job.id}"
    luogo = ", ".join(x for x in (job.city, job.country) if x) or "n.d."
    return (
        "<tr>"
        f'<td style="padding:10px 0;border-bottom:1px solid #e5e5e5">'
        f'<a href="{escape(link)}" style="font-weight:600;text-decoration:none;color:#111827">'
        f"{escape(job.title)}</a>"
        f'<br><span style="color:#6b7280;font-size:13px">'
        f"{escape(job.company)} · {escape(luogo)}</span>"
        "</td>"
        f'<td style="padding:10px 0;border-bottom:1px solid #e5e5e5;text-align:right;'
        f'font-weight:700;color:#111827;white-space:nowrap">{s.score}%</td>'
        "</tr>"
    )


def _riga_testo(s: Scored, base_url: str) -> str:
    job = s.job
    return f"- {job.title} @ {job.company} — {s.score}% — {base_url}/annuncio/{job.id}"


#: Template minimo: colonna singola, nessun CSS esterno — le mail lo bloccano quasi
#: sempre. Stessa scelta ATS-safe del CV, per un motivo diverso: qui e' il client di
#: posta a non renderizzare quello che non capisce, non un parser di CV.
_TEMPLATE = """<!doctype html>
<html lang="it">
<body style="margin:0;padding:24px;background:#f9fafb;font-family:-apple-system,
  BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#111827">
  <table role="presentation" width="100%" style="max-width:560px;margin:0 auto">
    <tr><td style="padding-bottom:16px">
      <h1 style="font-size:18px;margin:0">{oggetto}</h1>
      <p style="color:#6b7280;font-size:13px;margin:6px 0 0">Punteggio minimo: {soglia}</p>
    </td></tr>
    {righe}
    <tr><td style="padding-top:20px">
      <a href="{app_url}" style="color:#2563eb;text-decoration:none;font-size:13px">
        Apri la dashboard →</a>
    </td></tr>
  </table>
</body>
</html>
"""
