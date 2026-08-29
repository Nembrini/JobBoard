"""JSearch su RapidAPI — indicizza Google for Jobs, quindi LinkedIn e Indeed.

È l'unica via legale per vedere gli annunci pubblicati su LinkedIn e Indeed:
nessuno dei due ha un'API pubblica, e lo scraping violerebbe i termini con
rischio concreto di ban dell'account (vedi ARCHITECTURE.md §2.1).

**Il piano gratuito è ~200 chiamate al mese, cioè 6-7 al giorno.** È la risorsa
più scarsa dell'intero sistema, e l'adapter è costruito attorno a questo vincolo:

- un budget giornaliero esplicito, che l'adapter si rifiuta di superare;
- le query si consumano **in ordine di priorità**, così se il budget finisce a
  metà run a restare fuori sono le ricerche meno importanti, non le prime della
  lista alfabetica;
- il payload originale finisce in `job_source_link.raw`, così riprocessare non
  costa una seconda chiamata.

**Questo adapter parla la v5**, che non è una revisione della v1 ma un'altra
API: endpoint `/search-v2` (la vecchia risponde 404, non un redirect), `data`
diventato un oggetto con dentro `jobs`, impaginazione a cursore invece che a
numero di pagina. E, cosa che si scopre solo guardando i dati veri, i campi
strutturati arrivano quasi sempre vuoti: su dieci annunci, `job_country` era
valorizzato una volta e le due colonne con la data di pubblicazione **zero**.
Quello che c'è sempre è `job_location` ("Ivrea TO • tramite LinkedIn") e
`job_posted_at` ("4 giorni fa"), entrambi testo e localizzati. Da lì le due
funzioni di lettura qui sotto, e i test in `tests/test_jsearch.py`.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from collections.abc import Iterator
from typing import Any

from ..models.enums import SalaryPeriod
from .base import (
    HttpClient,
    RawJob,
    SearchQuery,
    SourceAdapter,
    SourceError,
    parse_iso,
    register,
)

log = logging.getLogger(__name__)

_HOST = "jsearch.p.rapidapi.com"
#: La v5 ha spostato la ricerca da ``/search`` a ``/search-v2``. La vecchia
#: risponde 404, non un redirect: se un giorno arriva una v6 il sintomo sara'
#: identico, quindi ``_explain`` lo dice esplicitamente.
_ENDPOINT = f"https://{_HOST}/search-v2"

#: La documentazione della v5 e' esplicita: conviene mettere titolo **e luogo**
#: dentro ``query``, non solo nel parametro ``country``. Con il codice ISO la
#: frase diventa "software developer in it", che non significa niente; con il
#: nome del paese si ottengono i risultati giusti (verificato su it).
_COUNTRY_NAMES = {
    "it": "italy",
    "de": "germany",
    "nl": "netherlands",
    "es": "spain",
    "fr": "france",
    "pt": "portugal",
    "ie": "ireland",
    "at": "austria",
    "be": "belgium",
    "pl": "poland",
    "ch": "switzerland",
    "gb": "united kingdom",
    "us": "united states",
}

_PERIODS = {
    "HOUR": SalaryPeriod.HOURLY,
    "DAY": SalaryPeriod.DAILY,
    "WEEK": SalaryPeriod.MONTHLY,  # approssimazione: si normalizza comunque ad annuo
    "MONTH": SalaryPeriod.MONTHLY,
    "YEAR": SalaryPeriod.YEARLY,
}


@register
class JSearchAdapter(SourceAdapter):
    slug = "jsearch"
    display_name = "JSearch (Google for Jobs)"
    required_settings = ("rapidapi_key",)
    default_rate_limit_per_min = 10
    #: Sei chiamate al giorno esauriscono ~180 delle ~200 mensili, lasciando un
    #: margine per le prove manuali.
    default_daily_budget = 6

    def fetch(self, query: SearchQuery, http: HttpClient) -> Iterator[RawJob]:
        if missing := self.missing_settings():
            raise SourceError(f"JSearch non configurato: manca {', '.join(missing)}")

        budget = int(self.config.get("daily_budget", self.default_daily_budget or 6))
        spent = 0

        # Le combinazioni sono generate parola-per-parola e poi paese-per-paese, in
        # quest'ordine: la prima parola chiave è quella che descrive meglio il
        # profilo, ed è quella che deve girare su tutti i mercati prima che il
        # budget finisca.
        for keyword in query.keywords:
            for country in query.countries:
                if spent >= budget:
                    log.warning(
                        "budget JSearch esaurito (%d chiamate): saltate le ricerche "
                        "rimanenti, riprendono domani",
                        budget,
                    )
                    return
                spent += 1
                yield from self._search(http, keyword, country, query)

    def http_headers(self) -> dict[str, str]:
        return {
            "X-RapidAPI-Key": self.settings.rapidapi_key.get_secret_value(),
            "X-RapidAPI-Host": _HOST,
        }

    def _search(
        self, http: HttpClient, keyword: str, country: str, query: SearchQuery
    ) -> Iterator[RawJob]:
        codice = country.lower()
        dove = _COUNTRY_NAMES.get(codice, codice)
        params = {
            "query": keyword if query.remote_only else f"{keyword} in {dove}",
            # Niente `page`: la v5 impagina con un cursore (`data.cursor`), non
            # con un numero. `num_pages` resta a 1 perche' **ogni pagina consuma
            # un credito**, e i crediti qui sono ~200 al mese.
            "num_pages": "1",
            "country": codice,
            "date_posted": _date_filter(query.posted_within_days),
        }
        if query.remote_only:
            params["work_from_home"] = "true"

        try:
            payload = http.get_json(_ENDPOINT, params=params)
        except SourceError as exc:
            raise _explain(exc) from exc

        # Nella v5 `data` e' un oggetto (`{"jobs": [...], "cursor": "..."}`), non
        # piu' l'elenco degli annunci. Iterarlo come prima non darebbe errore:
        # darebbe le chiavi del dizionario, cioe' due stringhe.
        dati = payload.get("data")
        annunci = dati.get("jobs") if isinstance(dati, dict) else dati
        for entry in annunci or []:
            job = _to_raw_job(entry, codice)
            if job is not None:
                yield job


def _explain(exc: SourceError) -> SourceError:
    """Traduce gli errori di RapidAPI, senza affermare piu' di quel che si sa.

    **Il 403 "not subscribed" non dice che la chiave e' valida.** Verificato: una
    chiave inventata di sana pianta riceve esattamente la stessa risposta, e il
    401 arriva solo quando l'header manca del tutto. Il messaggio quindi elenca
    le due cause possibili invece di sceglierne una — una versione precedente
    dichiarava valida la chiave e ha mandato a cercare il problema
    nell'abbonamento, mentre in ``.env`` non c'era nessuna chiave.
    """
    testo = str(exc)
    if "not subscribed" in testo.lower():
        return SourceError(
            "JSearch: 403 'not subscribed'. Due cause danno la stessa risposta. "
            "1) RAPIDAPI_KEY assente o malformata: eseguire 'jobboard doctor', che "
            "riconosce anche il caso in cui la riga di .env contiene il commento al "
            "posto del valore. 2) La chiave e' buona ma quell'applicazione RapidAPI "
            "non e' iscritta a JSearch: aprire "
            "rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch e premere 'Start Free "
            "Plan' sul piano Basic. L'iscrizione vale per singola API e per singola "
            "applicazione, non per account."
        )
    if "404" in testo and "does not exist" in testo:
        return SourceError(
            "JSearch: l'endpoint non esiste piu'. E' gia' successo una volta — la "
            "v5 ha spostato la ricerca da /search a /search-v2 rispondendo 404 e "
            "non un redirect. Controllare il percorso e la forma della risposta su "
            "rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch, endpoint 'Job Search': "
            "quando cambia la versione cambiano anche i nomi dei campi."
        )
    if "429" in testo:
        return SourceError(
            "JSearch: quota mensile esaurita. Riprende con il rinnovo del piano; "
            "nel frattempo le altre fonti continuano a girare."
        )
    return exc


def _date_filter(days: int) -> str:
    """L'API accetta solo quattro valori discreti, non un numero di giorni."""
    if days <= 1:
        return "today"
    if days <= 3:
        return "3days"
    if days <= 7:
        return "week"
    return "month"


def _to_raw_job(entry: dict[str, Any], country: str) -> RawJob | None:
    job_id = entry.get("job_id")
    title = entry.get("job_title")
    if not (job_id and title):
        return None

    apply_link = entry.get("job_apply_link")

    return RawJob(
        source=JSearchAdapter.slug,
        external_id=str(job_id),
        title=str(title),
        company=str(entry.get("employer_name") or "") or "Azienda non dichiarata",
        url=str(apply_link or ""),
        description=str(entry.get("job_description") or ""),
        location=_location(entry),
        # `job_country` e' arrivato valorizzato su 1 annuncio su 10. Il ripiego e'
        # il paese **richiesto**: non e' una supposizione sul singolo annuncio, e'
        # il filtro che Google ha applicato per restituirlo.
        country=(str(entry.get("job_country") or country)).upper()[:2],
        is_remote=entry.get("job_is_remote") if entry.get("job_is_remote") is not None else None,
        posted_at=_posted_at(entry),
        salary_min=_number(entry.get("job_min_salary")),
        salary_max=_number(entry.get("job_max_salary")),
        # `job_salary_currency` non esiste piu' nella v5. Al suo posto c'e' una
        # stringa libera, che e' esattamente quello che `pipeline.salary` sa
        # interpretare — valuta compresa.
        salary_text=str(entry.get("job_salary_string") or "") or None,
        salary_period=_PERIODS.get(str(entry.get("job_salary_period") or "").upper()),
        contract_hint=str(entry.get("job_employment_type") or "") or None,
        # Il portale vero: "LinkedIn", "Indeed", "Randstad". E' l'unico motivo per
        # cui questa fonte esiste, e senza salvarlo la dashboard mostrerebbe
        # "jsearch" al posto del nome che si sta cercando.
        publisher=str(entry.get("job_publisher") or "") or None,
        apply_url=_apply_url(entry),
        raw=entry,
    )


#: Coda che la v5 aggiunge a `job_location`: "Ivrea TO     •  tramite LinkedIn".
#: Il separatore e' un bullet, e la parola dopo cambia con la lingua del paese.
_VIA = re.compile(r"\s*[•·|]\s*.*$")


def _location(entry: dict[str, Any]) -> str | None:
    """Il luogo, da `job_city`/`job_state` se ci sono e da `job_location` se no.

    Nella v5 i campi strutturati arrivano quasi sempre vuoti — uno su dieci nel
    campione — mentre `job_location` c'e' sempre. Va pero' ripulito: contiene in
    coda il portale di provenienza ("Ivrea TO • tramite LinkedIn"), che
    finirebbe dentro la citta' e romperebbe sia la chiave di dedup sia il filtro
    per paese.
    """
    strutturato = ", ".join(str(p) for p in (entry.get("job_city"), entry.get("job_state")) if p)
    if strutturato:
        return strutturato

    grezzo = str(entry.get("job_location") or "").strip()
    pulito = _VIA.sub("", grezzo).strip()
    return pulito or None


def _apply_url(entry: dict[str, Any]) -> str | None:
    """Il link diretto al form dell'azienda, se ce n'e' uno.

    `apply_options` elenca tutti i modi di candidarsi con un flag `is_direct`:
    quello diretto porta al sito dell'azienda, gli altri a un portale che
    reindirizza. Solo il primo puo' portare a una candidatura automatica
    (Tier A), quindi si cerca li' anche quando `job_apply_is_direct` e' falso.
    """
    if entry.get("job_apply_is_direct") and entry.get("job_apply_link"):
        return str(entry["job_apply_link"])

    for opzione in entry.get("apply_options") or []:
        if isinstance(opzione, dict) and opzione.get("is_direct") and opzione.get("apply_link"):
            return str(opzione["apply_link"])
    return None


#: Unita' di tempo nelle lingue dei mercati che interroghiamo. Basta il prefisso:
#: "giorn" copre giorno/giorni, "Tag" copre Tag/Tagen, "dia" copre dia/dias.
_UNITA: tuple[tuple[tuple[str, ...], float], ...] = (
    (("minut", "minuut", "minuto", "minute"), 1 / 1440),
    (("ora", "ore", "hour", "stund", "hora", "heure", "uur", "godzin"), 1 / 24),
    (("giorn", "day", "tag", "dia", "día", "jour", "dag", "dni", "dzie"), 1.0),
    (("settiman", "week", "woche", "semana", "semaine", "weken", "tydz", "tygod"), 7.0),
    (("mes", "month", "monat", "mois", "maand", "miesi"), 30.0),
)

#: Parole che valgono "oggi" e "ieri" senza numero davanti.
_OGGI = ("oggi", "today", "heute", "hoy", "aujourd", "vandaag", "hoje", "dzisiaj", "dzis")
_IERI = ("ieri", "yesterday", "gestern", "ayer", "hier", "gisteren", "ontem", "wczoraj")

#: "un giorno fa", "a day ago", "vor einem Tag": nessuna cifra, ma vale 1.
_UNO = ("un", "una", "un'", "a", "an", "einem", "einer", "eine", "uma", "een")


def _posted_at(entry: dict[str, Any]) -> dt.datetime | None:
    """Quando e' stato pubblicato, con tre tentativi in ordine di affidabilita'.

    Nella v5 ``job_posted_at_datetime_utc`` e ``job_posted_at_timestamp`` sono
    arrivati **vuoti su tutti e dieci** gli annunci del campione: l'unica data
    disponibile e' ``job_posted_at``, che e' testo relativo e localizzato — "4
    giorni fa", "vor 5 Tagen". Lasciar perdere significherebbe non avere nessuna
    data su nessun annuncio JSearch, quindi la colonna vuota e l'ordinamento per
    data che li manda tutti in fondo.

    La lettura e' deliberatamente approssimativa: interessa il giorno, non il
    minuto. Quando non si capisce si restituisce ``None``, che e' onesto — una
    data inventata sarebbe peggio dell'assenza.
    """
    if esatta := parse_iso(entry.get("job_posted_at_datetime_utc")):
        return esatta

    timestamp = entry.get("job_posted_at_timestamp")
    if isinstance(timestamp, int | float) and timestamp > 0:
        return dt.datetime.fromtimestamp(float(timestamp), dt.UTC)

    return _da_relativa(str(entry.get("job_posted_at") or ""))


def _da_relativa(testo: str, adesso: dt.datetime | None = None) -> dt.datetime | None:
    """ "4 giorni fa" -> un datetime. ``None`` se il formato non si riconosce."""
    minuscolo = testo.strip().lower()
    if not minuscolo:
        return None

    ora = adesso or dt.datetime.now(dt.UTC)
    if any(p in minuscolo for p in _OGGI):
        return ora
    if any(p in minuscolo for p in _IERI):
        return ora - dt.timedelta(days=1)

    # Le parole intere, non i sottotesti: "an" dentro "settimana" non e' un
    # articolo, e senza questa distinzione "settimana" varrebbe "una settimana"
    # anche quando il numero c'e' e dice altro.
    parole = set(re.findall(r"[^\W\d_]+", minuscolo))

    for prefissi, giorni in _UNITA:
        if not any(p in minuscolo for p in prefissi):
            continue
        if cifre := re.search(r"[0-9]+", minuscolo):
            quantita = float(cifre.group())
        elif parole & set(_UNO):
            quantita = 1.0
        else:
            return None
        return ora - dt.timedelta(days=quantita * giorni)
        return ora - dt.timedelta(days=quantita * giorni)

    return None


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
