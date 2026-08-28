"""Interpretazione della retribuzione, da testo libero a RAL annua confrontabile.

Il problema è che ogni fonte la scrive a modo suo: `"€30.000 - €40.000"`,
`"$211.4K - $290.6K"`, `"15 €/ora"`, `"RAL 35k + benefit"`, `"competitive"`.
Senza una forma comune non si può né ordinare né filtrare.

Due regole non negoziabili, che vengono dalla promessa fatta alla dashboard —
*"RAL se dichiarata"*:

1. **Se l'annuncio non dichiara nulla, il risultato è "non dichiarata".** Mai una
   stima, mai uno zero, mai un valore di comodo. La colonna mostra "n.d.".
2. **La conversione in euro serve solo a ordinare.** Quello che si mostra resta
   sempre l'importo originale nella valuta originale: un cambio approssimato è
   utile per mettere in fila, disonesto da esibire come cifra.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..models.enums import SalaryPeriod

#: Cambi approssimati verso euro, fissati a mano il 2026-08-28. Servono **solo**
#: per rendere confrontabili annunci in valute diverse: non vengono mai mostrati
#: e un errore del 5% non cambia l'ordine di una tabella.
_EUR_RATES = {
    "EUR": 1.0,
    "USD": 0.92,
    "GBP": 1.17,
    "CHF": 1.05,
    "PLN": 0.23,
    "SEK": 0.088,
    "NOK": 0.086,
    "DKK": 0.134,
    "CZK": 0.040,
    "CAD": 0.68,
    "AUD": 0.61,
}

#: Ore lavorate in un anno a tempo pieno: 215 giorni per 8 ore.
_HOURS_PER_YEAR = 1720
_DAYS_PER_YEAR = 215

_SYMBOLS = {"€": "EUR", "$": "USD", "£": "GBP", "₣": "CHF"}
_CODES = re.compile(r"\b(EUR|USD|GBP|CHF|PLN|SEK|NOK|DKK|CZK|CAD|AUD)\b", re.I)

#: Un numero con separatori e opzionale suffisso k: "30.000", "1,234.56", "211.4K".
_NUMBER = re.compile(r"\d[\d.,]*\s*[kK]?")

_PERIOD_SOURCES: tuple[tuple[SalaryPeriod, str], ...] = (
    (SalaryPeriod.HOURLY, r"/\s*(?:h|hr|ora|hour)\b|\bhourly\b|\bper hour\b|\ball.ora\b"),
    (SalaryPeriod.DAILY, r"/\s*(?:d|day|giorno)\b|\bal giorno\b|\bper day\b|\bdaily\b"),
    (SalaryPeriod.MONTHLY, r"/\s*(?:m|mese|month)\b|\bal mese\b|\bper month\b|\bmensil"),
    (SalaryPeriod.YEARLY, r"/\s*(?:y|yr|anno|year)\b|\bper year\b|\bannual|\bannuo\b|\bRAL\b"),
)

_PERIOD_PATTERNS = tuple((periodo, re.compile(p, re.I)) for periodo, p in _PERIOD_SOURCES)

#: "x14 mensilità", "14 mensilità": in Italia una RAL mensile va moltiplicata per
#: il numero di mensilità, che è 13 o 14 molto più spesso di 12.
_MENSILITA = re.compile(r"\b(?:x\s*)?(1[2-6])\s*(?:ª\s*)?mensilit", re.I)

#: Sotto questa cifra un importo annuo sarebbe implausibile in Europa: se il
#: periodo non è dichiarato, numeri più piccoli non sono RAL.
_MIN_PLAUSIBLE_YEARLY = 10_000
#: Sopra questa cifra un importo orario sarebbe implausibile.
_MAX_PLAUSIBLE_HOURLY = 500


@dataclass(frozen=True)
class Salary:
    """Retribuzione di un annuncio, dichiarata o assente."""

    is_stated: bool = False
    min: int | None = None
    max: int | None = None
    currency: str | None = None
    period: SalaryPeriod | None = None
    #: Solo per ordinare e filtrare. Non si mostra mai.
    eur_year_min: int | None = None
    eur_year_max: int | None = None

    @classmethod
    def not_stated(cls) -> Salary:
        return cls()


NOT_STATED = Salary()


def from_structured(
    minimum: float | None,
    maximum: float | None,
    currency: str | None,
    period: SalaryPeriod | None,
) -> Salary:
    """Costruisce una :class:`Salary` dai campi già strutturati di una fonte."""
    if not minimum and not maximum:
        return NOT_STATED

    valuta = (currency or "EUR").upper()
    periodo = period or _infer_period(minimum or maximum)
    return _build(minimum, maximum, valuta, periodo)


def parse(text: str | None, *, default_currency: str | None = None) -> Salary:
    """Estrae la retribuzione da testo libero.

    Restituisce :data:`NOT_STATED` quando non trova cifre credibili — che è il
    caso più frequente: la maggior parte degli annunci italiani non dichiara
    nulla, e "competitive salary" non è una dichiarazione.
    """
    if not text or not text.strip():
        return NOT_STATED

    numeri = _numbers(text)
    if not numeri:
        return NOT_STATED

    valuta = _currency(text) or (default_currency or "").upper() or None
    periodo = _period(text) or _infer_period(numeri[0])

    minimo = numeri[0]
    massimo = numeri[1] if len(numeri) > 1 and numeri[1] >= numeri[0] else None

    if periodo is SalaryPeriod.MONTHLY and (mensilita := _MENSILITA.search(text)):
        # Non è una conversione ma un dato dichiarato: "1.800 € x 14 mensilità"
        # vale 25.200 all'anno, non 21.600.
        return _build(minimo, massimo, valuta, periodo, months_per_year=int(mensilita.group(1)))

    return _build(minimo, massimo, valuta, periodo)


def _build(
    minimum: float | None,
    maximum: float | None,
    currency: str | None,
    period: SalaryPeriod | None,
    *,
    months_per_year: int = 12,
) -> Salary:
    rate = _EUR_RATES.get((currency or "").upper())
    eur_min = _to_eur_year(minimum, period, rate, months_per_year)
    eur_max = _to_eur_year(maximum, period, rate, months_per_year)
    return Salary(
        is_stated=True,
        min=int(minimum) if minimum else None,
        max=int(maximum) if maximum else None,
        currency=currency,
        period=period,
        eur_year_min=eur_min,
        eur_year_max=eur_max,
    )


def _to_eur_year(
    amount: float | None, period: SalaryPeriod | None, rate: float | None, months: int
) -> int | None:
    """Porta un importo a euro annui. ``None`` se manca valuta o periodo.

    Meglio nessun valore che un valore inventato: un ordinamento con dentro una
    conversione sbagliata è peggio di uno che lascia in fondo gli annunci senza
    dati confrontabili.
    """
    if not amount or rate is None or period is None:
        return None
    per_anno = {
        SalaryPeriod.HOURLY: amount * _HOURS_PER_YEAR,
        SalaryPeriod.DAILY: amount * _DAYS_PER_YEAR,
        SalaryPeriod.MONTHLY: amount * months,
        SalaryPeriod.YEARLY: amount,
    }[period]
    return round(per_anno * rate)


def _numbers(text: str) -> list[float]:
    valori = []
    for match in _NUMBER.finditer(text):
        numero = _to_number(match.group())
        if numero is not None and numero > 0:
            valori.append(numero)
    return valori


def _to_number(raw: str) -> float | None:
    """Da "30.000" a 30000, "211.4K" -> 211400, "1,234.56" -> 1234.56.

    L'ambiguità fra separatore delle migliaia e separatore decimale è reale e non
    si risolve guardando la lingua: ``€30.000`` in un annuncio italiano vale
    trentamila, la stessa stringa in inglese varrebbe trenta. La regola usata è
    posizionale e funziona su entrambe le convenzioni: **un separatore seguito da
    esattamente tre cifre separa le migliaia**, tutto il resto è decimale.
    """
    testo = raw.strip()
    moltiplicatore = 1000.0 if testo[-1:].lower() == "k" else 1.0
    testo = testo.rstrip("kK").strip()
    if not testo:
        return None

    ultimo = max(testo.rfind("."), testo.rfind(","))
    if ultimo == -1:
        pulito = testo
    else:
        cifre_dopo = len(testo) - ultimo - 1
        if cifre_dopo == 3 and moltiplicatore == 1.0:
            pulito = testo.replace(".", "").replace(",", "")
        else:
            pulito = testo[:ultimo].replace(".", "").replace(",", "") + "." + testo[ultimo + 1 :]

    try:
        return float(pulito) * moltiplicatore
    except ValueError:
        return None


def _currency(text: str) -> str | None:
    for simbolo, codice in _SYMBOLS.items():
        if simbolo in text:
            return codice
    if match := _CODES.search(text):
        return match.group(1).upper()
    return None


def _period(text: str) -> SalaryPeriod | None:
    for periodo, pattern in _PERIOD_PATTERNS:
        if pattern.search(text):
            return periodo
    return None


def _infer_period(amount: float | None) -> SalaryPeriod | None:
    """Deduce il periodo dall'ordine di grandezza, quando non è dichiarato.

    Non è una stima della retribuzione — quella resta il numero dell'annuncio —
    ma dell'unità di misura, e le fasce non si sovrappongono: in Europa nessuno
    guadagna 45.000 € l'ora e nessuno ne guadagna 25 l'anno. Fuori dalle fasce
    sicure si restituisce ``None`` e l'annuncio resta senza valore confrontabile.
    """
    if amount is None:
        return None
    if amount >= _MIN_PLAUSIBLE_YEARLY:
        return SalaryPeriod.YEARLY
    if amount <= _MAX_PLAUSIBLE_HOURLY:
        return SalaryPeriod.HOURLY
    return None
