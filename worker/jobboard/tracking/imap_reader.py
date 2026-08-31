"""Lettura IMAP a scope ristretto delle risposte dei recruiter (Fase 9.2).

**Non scansiona la casella intera.** Ogni ricerca parte da ``SINCE`` la data
della candidatura (o dell'ultimo controllo, se successiva): una casella
personale ha anni di posta che non riguardano nessuna candidatura, e
leggerla tutta a ogni giro sarebbe sia inutile sia — aprendo ogni mail di
chiunque altro scriva a quell'indirizzo — una violazione di scope che nessuna
candidatura giustifica.

**Non conserva il corpo delle mail non correlate.** L'``IMAP4.fetch`` per gli
header (``BODY.PEEK[HEADER...]``) e quello per il corpo (``BODY.PEEK[]``)
sono due chiamate separate apposta: si scaricano tutti gli header nella
finestra di tempo, si scarta subito chi non supera :func:`looks_related`, e
solo per chi resta si fa la seconda chiamata che porta il testo. ``PEEK`` in
entrambe non marca i messaggi come letti — il worker legge una casella che
resta anche quella di Filippo.

**Correlazione per dominio azienda o per thread.** Il primo criterio è
lessicale: i token del nome azienda normalizzato (``job.company_normalized``,
già calcolato dalla Fase 2 — stessa chiave con cui si fondono due annunci
duplicati) compaiono nel mittente o nell'oggetto. Non basta da solo: un
recruiter risponde spesso da un indirizzo Gmail personale che non contiene il
nome dell'azienda da nessuna parte. Il secondo criterio copre questo caso —
una mail il cui ``In-Reply-To``/``References`` cita un ``Message-ID`` già
riconosciuto come correlato resta nello stesso thread anche se il mittente
cambia.
"""

from __future__ import annotations

import datetime as dt
import email
import imaplib
import logging
from dataclasses import dataclass, field
from email.header import decode_header
from email.message import Message
from email.utils import parsedate_to_datetime
from typing import Protocol

from ..config import Settings
from ..pipeline.text import html_to_text, normalize_key

log = logging.getLogger(__name__)


class ImapError(RuntimeError):
    """La connessione o la ricerca IMAP è fallita: credenziali, rete, mailbox assente."""


@dataclass(frozen=True)
class EmailHeader:
    """Quel poco che serve per decidere *se* leggere una mail, non il contenuto."""

    uid: str
    message_id: str
    sender: str
    subject: str
    date: dt.datetime
    #: ``In-Reply-To`` + ``References``, per la correlazione per thread.
    in_reply_to: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CandidateEmail:
    """Una mail che ha superato :func:`looks_related`: da qui in poi la si legge."""

    header: EmailHeader
    body_text: str


class MailboxClient(Protocol):
    """L'unica cosa che serve da un client IMAP — astratta per i test.

    ``ImapMailbox`` sotto è l'unica implementazione vera; i test usano un
    finto in memoria, come ``_FakeSmtp`` fa per ``notify.mailer``.
    """

    def search_since(self, since: dt.date) -> list[EmailHeader]:
        """Solo header, di tutti i messaggi arrivati da ``since`` in poi."""

    def fetch_body(self, uid: str) -> str:
        """Il testo semplice di un messaggio già scelto come correlato."""

    def close(self) -> None: ...


class ImapMailbox:
    """Wrapper minimo su ``imaplib.IMAP4_SSL``, sola lettura su INBOX.

    Le stesse credenziali dell'SMTP di ``notify.mailer``
    (``GMAIL_ADDRESS``/``GMAIL_APP_PASSWORD``): una App Password di Gmail vale
    per entrambi i protocolli, non serve una seconda chiave.
    """

    def __init__(self, settings: Settings) -> None:
        try:
            settings.require("gmail_address", "gmail_app_password")
            self._conn = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port)
            self._conn.login(settings.gmail_address, settings.gmail_app_password.get_secret_value())
            # readonly=True e' la seconda meta' della promessa "non marca come
            # letto": IMAP la applica gia' senza, ma un client futuro che
            # smettesse di usare PEEK per errore resterebbe comunque bloccato
            # dal server, non solo dalla disciplina di chi scrive le query.
            self._conn.select("INBOX", readonly=True)
        except (imaplib.IMAP4.error, OSError, RuntimeError) as exc:
            # RuntimeError e' quella di ``settings.require``: una chiave
            # mancante non e' diversa, per chi chiama, da un server
            # irraggiungibile — in entrambi i casi non si legge la posta.
            raise ImapError(f"connessione IMAP fallita: {exc}") from exc

    def search_since(self, since: dt.date) -> list[EmailHeader]:
        criterio = since.strftime("%d-%b-%Y")
        try:
            status, dati = self._conn.search(None, "SINCE", criterio)
            if status != "OK":
                raise ImapError(f"ricerca IMAP fallita: {status}")

            intestazioni: list[EmailHeader] = []
            for uid_bytes in dati[0].split():
                uid = uid_bytes.decode()
                campi = "(FROM SUBJECT DATE MESSAGE-ID IN-REPLY-TO REFERENCES)"
                stato_fetch, righe = self._conn.fetch(
                    uid_bytes, f"(BODY.PEEK[HEADER.FIELDS {campi}])"
                )
                if stato_fetch != "OK" or not righe or not isinstance(righe[0], tuple):
                    continue
                intestazione = _parse_header(uid, righe[0][1])
                if intestazione is not None:
                    intestazioni.append(intestazione)
            return intestazioni
        except (imaplib.IMAP4.error, OSError) as exc:
            raise ImapError(f"lettura header IMAP fallita: {exc}") from exc

    def fetch_body(self, uid: str) -> str:
        try:
            # Il messaggio intero, non solo ``BODY[TEXT]``: quest'ultimo
            # restituirebbe il MIME multipart grezzo (boundary comprese) invece
            # del testo leggibile, perche' scegliere fra ``text/plain`` e
            # ``text/html`` richiede di parsare la struttura, non solo il corpo.
            status, righe = self._conn.fetch(uid, "(BODY.PEEK[])")
            if status != "OK" or not righe or not isinstance(righe[0], tuple):
                return ""
            return extract_text(righe[0][1])
        except (imaplib.IMAP4.error, OSError) as exc:
            raise ImapError(f"lettura corpo IMAP fallita: {exc}") from exc

    def close(self) -> None:
        try:
            self._conn.close()
            self._conn.logout()
        except (imaplib.IMAP4.error, OSError):
            # Chiusura best-effort: un server che ha gia' tagliato la
            # connessione non deve far fallire un task che ha comunque
            # gia' letto quello che gli serviva.
            pass


def looks_related(*, company_normalized: str, sender: str, subject: str) -> bool:
    """Criterio lessicale: un token del nome azienda nel mittente o nell'oggetto.

    Solo token di almeno 4 caratteri: sotto quella soglia restano quasi solo
    sigle troppo comuni (``"srl"`` è già filtrata da ``normalize_company``, ma
    un nome come ``"go"`` o ``"acme spa"`` -> ``"go"`` darebbe falsi positivi
    su qualunque mittente ``@google.com``).
    """
    token = [t for t in company_normalized.split() if len(t) >= 4]
    if not token:
        return False
    campo = normalize_key(f"{sender} {subject}")
    return any(t in campo for t in token)


def fetch_candidate_emails(
    mailbox: MailboxClient,
    *,
    since: dt.date,
    company_normalized: str,
    known_message_ids: frozenset[str] = frozenset(),
) -> list[CandidateEmail]:
    """Gli header nella finestra di tempo che superano la correlazione, con il corpo.

    ``known_message_ids`` sono i ``Message-ID`` già classificati per questa
    candidatura: una mail il cui thread cita uno di questi resta correlata
    anche quando il mittente — una risposta da un indirizzo Gmail personale,
    non dal dominio aziendale — non supera :func:`looks_related` da solo.
    """
    intestazioni = select_related(
        mailbox.search_since(since),
        since=since,
        company_normalized=company_normalized,
        known_message_ids=known_message_ids,
    )
    return [
        CandidateEmail(header=intestazione, body_text=mailbox.fetch_body(intestazione.uid))
        for intestazione in intestazioni
    ]


def select_related(
    headers: list[EmailHeader],
    *,
    since: dt.date,
    company_normalized: str,
    known_message_ids: frozenset[str] = frozenset(),
) -> list[EmailHeader]:
    """La parte pura di :func:`fetch_candidate_emails`, senza I/O.

    Separata perché il gestore ``check_email`` fa **una** ricerca IMAP con la
    data più antica fra tutte le candidature in attesa — aprire una
    connessione e una ``SEARCH`` per ognuna sarebbe lento e non necessario —
    e poi filtra la stessa lista di header per ciascuna, con il proprio
    ``since`` e i propri ``known_message_ids``.
    """
    soglia = dt.datetime.combine(since, dt.time.min, tzinfo=dt.UTC)
    scelti = []
    for intestazione in headers:
        if intestazione.date < soglia:
            continue
        per_dominio = looks_related(
            company_normalized=company_normalized,
            sender=intestazione.sender,
            subject=intestazione.subject,
        )
        per_thread = bool(known_message_ids.intersection(intestazione.in_reply_to))
        if per_dominio or per_thread:
            scelti.append(intestazione)
    return scelti


def _parse_header(uid: str, grezzo: bytes) -> EmailHeader | None:
    messaggio = email.message_from_bytes(grezzo)

    data = _parse_date(messaggio.get("Date"))
    if data is None:
        # Senza una data attendibile non si puo' verificare che il messaggio
        # sia successivo alla candidatura: si scarta piuttosto che rischiare
        # di trattare come nuova una mail di anni fa che il server ha comunque
        # restituito.
        return None

    message_id = (messaggio.get("Message-ID") or "").strip()
    riferimenti = " ".join(
        filter(None, (messaggio.get("In-Reply-To"), messaggio.get("References")))
    ).split()

    return EmailHeader(
        uid=uid,
        message_id=message_id,
        sender=_decode(messaggio.get("From") or ""),
        subject=_decode(messaggio.get("Subject") or ""),
        date=data,
        in_reply_to=tuple(riferimenti),
    )


def _parse_date(valore: str | None) -> dt.datetime | None:
    if not valore:
        return None
    try:
        parsata = parsedate_to_datetime(valore)
    except (TypeError, ValueError):
        return None
    # Un header ``Date`` senza fuso (raro, ma capita con mailer mal
    # configurati) darebbe un datetime naive: confrontarlo con la soglia
    # sempre UTC di `select_related` solleverebbe TypeError. Si assume UTC
    # invece di scartare il messaggio.
    return parsata if parsata.tzinfo is not None else parsata.replace(tzinfo=dt.UTC)


def _decode(intestazione: str) -> str:
    """``From``/``Subject`` possono arrivare MIME-encoded (``=?UTF-8?B?...?=``)."""
    pezzi = decode_header(intestazione)
    return "".join(
        pezzo.decode(codifica or "utf-8", errors="replace") if isinstance(pezzo, bytes) else pezzo
        for pezzo, codifica in pezzi
    )


def extract_text(messaggio_grezzo: bytes) -> str:
    """``text/plain`` se c'è, altrimenti ``text/html`` ripulito con lo stesso
    convertitore delle job description (``pipeline.text.html_to_text``): una
    risposta di recruiter è spesso solo HTML, e il classificatore lavora su
    testo, non su tag.
    """
    messaggio = email.message_from_bytes(messaggio_grezzo)

    html: str | None = None
    for parte in messaggio.walk():
        if parte.is_multipart():
            continue
        tipo = parte.get_content_type()
        if tipo == "text/plain":
            return _decode_part(parte).strip()
        if tipo == "text/html" and html is None:
            html = _decode_part(parte)

    return html_to_text(html) if html else ""


def _decode_part(parte: Message) -> str:
    payload = parte.get_payload(decode=True)
    if not isinstance(payload, bytes):
        return str(parte.get_payload())
    codifica = parte.get_content_charset() or "utf-8"
    try:
        return payload.decode(codifica, errors="replace")
    except LookupError:  # charset dichiarato ma sconosciuto a Python
        return payload.decode("utf-8", errors="replace")
