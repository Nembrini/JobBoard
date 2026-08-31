"""Test del reader IMAP (Fase 9.2): nessuna rete, nessuna connessione vera.

``ImapMailbox`` (l'unica implementazione con ``imaplib``) non è testata qui —
parlerebbe con un server vero. Quello che conta è testabile senza rete:
``looks_related``, la parsificazione degli header e ``select_related``/
``fetch_candidate_emails`` contro un finto che implementa ``MailboxClient``.
"""

from __future__ import annotations

import datetime as dt

from jobboard.tracking.imap_reader import (
    CandidateEmail,
    EmailHeader,
    _decode,
    _parse_header,
    extract_text,
    fetch_candidate_emails,
    looks_related,
    select_related,
)

# --- looks_related -----------------------------------------------------------------


def test_token_dell_azienda_nel_mittente() -> None:
    assert looks_related(
        company_normalized="acme software", sender="hr@acmesoftware.com", subject="Ciao"
    )


def test_token_dell_azienda_nell_oggetto() -> None:
    assert looks_related(
        company_normalized="acme software",
        sender="recruiter42@gmail.com",
        subject="La tua candidatura in Acme",
    )


def test_nessun_token_in_comune_non_e_correlata() -> None:
    assert not looks_related(
        company_normalized="acme software", sender="newsletter@altrosito.it", subject="Offerte"
    )


def test_token_troppo_corti_non_bastano() -> None:
    """ "go" (da "Acme Spa" -> "go"? no — caso reale: nome breve) non deve dare falsi positivi."""
    assert not looks_related(company_normalized="go srl", sender="io@google.com", subject="")


def test_azienda_senza_token_utili_non_e_mai_correlata() -> None:
    assert not looks_related(company_normalized="", sender="chiunque@ovunque.com", subject="")


# --- parsing header ------------------------------------------------------------------


def _header_bytes(
    *,
    frm: str = "HR Acme <hr@acme.com>",
    subject: str = "La tua candidatura",
    date: str = "Mon, 1 Sep 2025 10:00:00 +0200",
    message_id: str = "<abc@acme.com>",
    in_reply_to: str | None = None,
) -> bytes:
    righe = [f"From: {frm}", f"Subject: {subject}", f"Date: {date}", f"Message-ID: {message_id}"]
    if in_reply_to:
        righe.append(f"In-Reply-To: {in_reply_to}")
    return ("\r\n".join(righe) + "\r\n\r\n").encode()


def test_parse_header_legge_i_campi_base() -> None:
    intestazione = _parse_header("42", _header_bytes())
    assert intestazione is not None
    assert intestazione.uid == "42"
    assert intestazione.message_id == "<abc@acme.com>"
    assert intestazione.sender == "HR Acme <hr@acme.com>"
    assert intestazione.subject == "La tua candidatura"
    assert intestazione.date.year == 2025


def test_parse_header_senza_data_viene_scartato() -> None:
    grezzo = b"From: hr@acme.com\r\nSubject: Ciao\r\n\r\n"
    assert _parse_header("1", grezzo) is None


def test_parse_header_data_senza_fuso_diventa_utc() -> None:
    intestazione = _parse_header("1", _header_bytes(date="Mon, 1 Sep 2025 10:00:00"))
    assert intestazione is not None
    assert intestazione.date.tzinfo is not None


def test_decode_gestisce_l_encoded_word_mime() -> None:
    # "Città" in UTF-8 base64, come lo manderebbe un client che codifica gli accenti.
    assert _decode("=?UTF-8?B?Q2l0dMOgIFJlY3J1aXRlcg==?=") == "Città Recruiter"


def test_extract_text_preferisce_il_plain() -> None:
    grezzo = (
        b"Content-Type: multipart/alternative; boundary=X\r\n\r\n"
        b"--X\r\nContent-Type: text/plain\r\n\r\nTesto semplice\r\n"
        b"--X\r\nContent-Type: text/html\r\n\r\n<p>Testo <b>html</b></p>\r\n--X--\r\n"
    )
    assert extract_text(grezzo).strip() == "Testo semplice"


def test_extract_text_ripiega_sull_html_ripulito() -> None:
    grezzo = b"Content-Type: text/html\r\n\r\n<p>Ciao <b>Filippo</b></p>\r\n"
    assert "Ciao Filippo" in extract_text(grezzo)


# --- select_related / fetch_candidate_emails ------------------------------------------


def _h(
    uid: str,
    *,
    days_ago: int = 0,
    sender: str,
    subject: str = "",
    in_reply_to: tuple[str, ...] = (),
) -> EmailHeader:
    return EmailHeader(
        uid=uid,
        message_id=f"<{uid}@x>",
        sender=sender,
        subject=subject,
        date=dt.datetime.now(dt.UTC) - dt.timedelta(days=days_ago),
        in_reply_to=in_reply_to,
    )


def test_select_related_scarta_prima_del_since() -> None:
    oggi = dt.date.today()
    vecchia = _h("1", days_ago=10, sender="hr@acme.com")
    recente = _h("2", days_ago=0, sender="hr@acme.com")
    scelti = select_related(
        [vecchia, recente], since=oggi, company_normalized="acme", known_message_ids=frozenset()
    )
    assert [h.uid for h in scelti] == ["2"]


def test_select_related_per_thread_anche_senza_dominio() -> None:
    """Un recruiter risponde da Gmail personale: il dominio non basta, il thread sì."""
    oggi = dt.date.today()
    risposta = _h("2", sender="mario.rossi@gmail.com", in_reply_to=("<1@x>",))
    scelti = select_related(
        [risposta],
        since=oggi,
        company_normalized="acme",
        known_message_ids=frozenset({"<1@x>"}),
    )
    assert [h.uid for h in scelti] == ["2"]


def test_select_related_scarta_senza_dominio_ne_thread() -> None:
    oggi = dt.date.today()
    estranea = _h("3", sender="newsletter@altrosito.it")
    scelti = select_related(
        [estranea], since=oggi, company_normalized="acme", known_message_ids=frozenset()
    )
    assert scelti == []


class _FakeMailbox:
    """Implementa ``MailboxClient``: registra quali corpi vengono richiesti."""

    def __init__(self, headers: list[EmailHeader], bodies: dict[str, str]) -> None:
        self._headers = headers
        self._bodies = bodies
        self.corpi_richiesti: list[str] = []

    def search_since(self, since: dt.date) -> list[EmailHeader]:
        return self._headers

    def fetch_body(self, uid: str) -> str:
        self.corpi_richiesti.append(uid)
        return self._bodies.get(uid, "")

    def close(self) -> None:
        pass


def test_fetch_candidate_emails_non_scarica_il_corpo_dei_non_correlati() -> None:
    """La promessa centrale del modulo: niente corpo per chi non passa il filtro."""
    headers = [
        _h("correlata", sender="hr@acme.com", subject="La tua candidatura"),
        _h("estranea", sender="newsletter@altrosito.it", subject="Offerte del mese"),
    ]
    mailbox = _FakeMailbox(headers, bodies={"correlata": "Ciao, colloquio?"})

    risultato = fetch_candidate_emails(
        mailbox, since=dt.date.today(), company_normalized="acme", known_message_ids=frozenset()
    )

    assert [c.header.uid for c in risultato] == ["correlata"]
    assert mailbox.corpi_richiesti == ["correlata"]
    assert isinstance(risultato[0], CandidateEmail)
    assert risultato[0].body_text == "Ciao, colloquio?"
