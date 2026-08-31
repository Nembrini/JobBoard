"""Dal testo grezzo del CV a un :class:`MasterProfile` validato.

Gli **id delle voci non li produce il modello**: vengono assegnati qui in modo
deterministico. Un LLM li genera incoerenti fra una chiamata e l'altra, a volte
duplicati, e sono la chiave con cui il validatore anti-invenzione della Fase 6
collega una frase del CV generato alla voce che la giustifica. Devono essere
stabili e univoci per costruzione, non per fortuna.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any

from ..ai import LLMProvider, LLMUsage, get_provider
from ..schemas import MasterProfile
from .extract import ExtractedDocument

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
Sei un parser di curriculum. Trasformi il testo di un CV in dati strutturati.

Regole non negoziabili:
- Riporta ESCLUSIVAMENTE cio' che il CV dichiara. Non dedurre, non completare,
  non arrotondare, non inventare date, aziende, tecnologie o risultati.
- Se un'informazione non c'e', lascia il campo vuoto o omettilo. Un campo
  assente e' corretto; un campo inventato rende inutilizzabile tutto il resto.
- Conserva i numeri esattamente come compaiono: percentuali, quantita', durate.
  Sono la parte piu' preziosa del CV.
- Le date vanno normalizzate nel formato YYYY-MM. "Gen 2022" diventa "2022-01".
  Se il CV indica solo l'anno, usa 01 come mese. Per un incarico ancora in
  corso ometti il campo di fine.
- Per ogni bullet dell'esperienza compila anche, quando il testo lo consente:
  action (il verbo principale), context (prodotto, team, scala) e result (il
  risultato misurabile). Se il bullet non dichiara un risultato, lascia result
  vuoto: non fabbricarne uno.
- In skills.hard metti tecnologie, linguaggi e strumenti. In skills.soft le
  competenze trasversali. Non spostare una skill da una categoria all'altra.
- Il campo id di ogni voce puo' restare una stringa vuota: viene assegnato dopo.
"""

USER_PROMPT = """\
Struttura questo CV. La lingua del documento e' {language}.

--- INIZIO CV ---
{text}
--- FINE CV ---
"""

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def structure(
    document: ExtractedDocument,
    *,
    provider: LLMProvider | None = None,
    model: str | None = None,
) -> tuple[MasterProfile, list[str], LLMUsage]:
    """Struttura il CV estratto.

    Ritorna il profilo, la lista di **avvertimenti** da mostrare in revisione
    (non sono errori, sono i punti dove vale la pena che un umano guardi) e il
    consumo della chiamata, per la dashboard dei costi della Fase 10.2.
    """
    llm = provider or get_provider()

    result = llm.generate_json(
        USER_PROMPT.format(language=document.language or "sconosciuta", text=document.text),
        MasterProfile,
        system=SYSTEM_PROMPT,
        model=model,
    )
    log.info(
        "CV strutturato con %s: %d token in, %d out",
        result.usage.model,
        result.usage.input_tokens,
        result.usage.output_tokens,
    )

    data = _assign_ids(_normalize(result.value))
    profile = MasterProfile.model_validate(data)
    return profile, _warnings(profile, document), result.usage


def _normalize(data: dict[str, Any]) -> dict[str, Any]:
    """Ritocchi di forma che non alterano i fatti.

    Solo cose che il CV generato non deve ereditare dall'impaginazione
    dell'originale: un nome scritto in maiuscolo per scelta grafica finirebbe
    urlato dentro un altro template.
    """
    contact = data.get("contact")
    if isinstance(contact, dict):
        name = contact.get("full_name")
        if isinstance(name, str) and name.isupper():
            contact["full_name"] = name.title()

    for key, fields in _DATE_FIELDS.items():
        for item in data.get(key) or []:
            if not isinstance(item, dict):
                continue
            for field in fields:
                if field in item:
                    item[field] = _normalize_month(item[field])
    return data


#: Dove stanno le date, per sezione.
_DATE_FIELDS: dict[str, tuple[str, ...]] = {
    "experiences": ("start", "end"),
    "education": ("start", "end"),
    "certifications": ("issued", "expires"),
}

#: Le forme in cui un LLM scrive una data, in ordine di frequenza osservata.
_MONTH_FORMS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^(?P<y>\d{4})-(?P<m>\d{1,2})(?:-\d{1,2})?$"),  # 2024-3, 2024-03-15
    re.compile(r"^(?P<m>\d{1,2})[/.](?P<y>\d{4})$"),  # 03/2024
    re.compile(r"^(?P<y>\d{4})[/.](?P<m>\d{1,2})$"),  # 2024/03
)

#: Come il modello puo' scrivere "sto ancora lavorando qui".
_ONGOING = frozenset({"", "presente", "present", "current", "attuale", "oggi", "in corso", "n/a"})


def _normalize_month(value: Any) -> Any:
    """Porta una data a ``YYYY-MM``, o la lascia com'e' se non la riconosce.

    Il prompt chiede gia' questo formato, ma il modello a volte risponde ``2024``
    o ``03/2024``: prima di questa funzione bastava una sola data cosi' per far
    fallire la validazione dell'intero profilo, dopo sette secondi di chiamata.
    Cio' che resta irriconoscibile passa oltre e viene rifiutato dallo schema,
    che e' il comportamento giusto: meglio un errore che una data inventata.

    Un anno senza mese diventa gennaio. E' una convenzione, non un dato: applicata
    a inizio **e** fine, conserva la durata corretta di un percorso di studi.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value

    text = value.strip()
    if text.lower() in _ONGOING:
        return None
    if re.fullmatch(r"\d{4}", text):
        return f"{text}-01"
    for pattern in _MONTH_FORMS:
        if match := pattern.match(text):
            month = int(match["m"])
            if 1 <= month <= 12:
                return f"{match['y']}-{month:02d}"
    return text


# --- assegnazione degli id ---------------------------------------------------


def _slug(*parts: str, fallback: str) -> str:
    raw = "-".join(p for p in parts if p)
    ascii_only = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    slug = _SLUG_STRIP.sub("-", ascii_only.lower()).strip("-")
    return slug or fallback


def _unique(slug: str, taken: set[str]) -> str:
    if slug not in taken:
        taken.add(slug)
        return slug
    n = 2
    while f"{slug}-{n}" in taken:
        n += 1
    taken.add(f"{slug}-{n}")
    return f"{slug}-{n}"


def _assign_ids(data: dict[str, Any]) -> dict[str, Any]:
    """Riscrive tutti gli id, ignorando quelli eventualmente prodotti dal modello.

    Derivati dal contenuto (azienda + ruolo, nome del progetto...) cosi' che
    ristrutturare lo stesso CV produca gli stessi id, e il diff fra due versioni
    del profilo resti leggibile.
    """
    taken: set[str] = set()

    for i, exp in enumerate(data.get("experiences") or [], start=1):
        exp["id"] = _unique(
            _slug(exp.get("company", ""), exp.get("role", ""), fallback=f"esperienza-{i}"), taken
        )
        for j, bullet in enumerate(exp.get("bullets") or [], start=1):
            bullet["id"] = _unique(f"{exp['id']}-{j}", taken)

    for key, prefix, name_fields in (
        ("education", "formazione", ("institution", "degree")),
        ("projects", "progetto", ("name",)),
        ("certifications", "certificazione", ("name", "issuer")),
    ):
        for i, item in enumerate(data.get(key) or [], start=1):
            parts = [str(item.get(f, "")) for f in name_fields]
            item["id"] = _unique(_slug(*parts, fallback=f"{prefix}-{i}"), taken)

    return data


# --- avvertimenti per la revisione -------------------------------------------


def _warnings(profile: MasterProfile, document: ExtractedDocument) -> list[str]:
    """Punti su cui vale la pena che un umano guardi, prima di usare il profilo."""
    out: list[str] = []

    if document.possibly_lost_numbers:
        out.append(
            "l'estrattore scartato aveva trovato le cifre "
            f"{', '.join(document.possibly_lost_numbers)}, assenti nel testo usato: "
            "controlla che non manchino da qualche bullet"
        )

    if not profile.experiences:
        out.append("nessuna esperienza lavorativa riconosciuta")
    if not profile.skills.hard:
        out.append("nessuna competenza tecnica riconosciuta")
    if not profile.contact.email:
        out.append("email non riconosciuta: serve per i form di candidatura")

    # Un bullet senza result non e' un errore, ma senza numeri il CV su misura
    # non potra' produrre affermazioni forti: meglio saperlo prima.
    bullets = [b for e in profile.experiences for b in e.bullets]
    without_result = [b.id for b in bullets if not b.result]
    if bullets and len(without_result) == len(bullets):
        out.append("nessun bullet dichiara un risultato misurabile")
    elif len(without_result) > len(bullets) * 0.7:
        out.append(f"{len(without_result)} bullet su {len(bullets)} senza risultato misurabile")

    # Un'esperienza senza bullet finisce nel CV come una riga vuota.
    empty = [e.id for e in profile.experiences if not e.bullets]
    if empty:
        out.append(f"esperienze senza alcun bullet: {', '.join(empty)}")

    return out
