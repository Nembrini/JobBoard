"""Guardrail dell'invio (Fase 7.5): quanto e verso chi il worker puo' agire da solo.

Contano meno di quanto contassero nel piano originale — con Tier A e B che si
fermano entrambi prima del submit (vedi ``__init__.py``), non c'e' piu' un
invio automatico da frenare. Restano comunque tre cose che il worker fa senza
che tu guardi: aprire un browser sul tuo PC, navigare verso il sito di
un'azienda mai contattata prima, e caricarci il tuo CV. Ognuna ha un limite.

Le funzioni qui sono **decisioni pure**: prendono numeri gia' contati, non
interrogano il database. La query che produce quei numeri sta in
``handlers.py``, accanto alla sessione — separarla qui renderebbe questo
modulo testabile solo con un database vero, che e' esattamente quello che
questo repository evita (vedi CLAUDE.md, sezione Comandi).
"""

from __future__ import annotations

from dataclasses import dataclass


class GuardrailBlocked(RuntimeError):
    """Un guardrail ha fermato la preparazione. Il messaggio e' per la dashboard."""


@dataclass(frozen=True)
class GuardrailCheck:
    """Esito di tutti i controlli prima di aprire il browser."""

    ok: bool
    reason: str | None = None
    #: ``True`` solo quando manca la conferma esplicita per un'azienda nuova:
    #: e' l'unico caso in cui il chiamante deve chiedere qualcosa invece di
    #: limitarsi a rimandare a domani (il cap) o a fermarsi (dry-run globale
    #: gestito a parte, in ``handlers.py``, perche' non blocca — simula).
    needs_company_confirmation: bool = False


def check_daily_cap(prepared_today: int, cap: int) -> GuardrailCheck:
    """Il tetto giornaliero di form aperti, per non riempire lo schermo di notte.

    Conta le preparazioni (``ApplicationEventType.PREPARED``), non le
    candidature spedite: e' il numero di volte in cui il worker ha aperto un
    browser e toccato un sito di terzi, che e' l'azione da limitare.
    """
    if prepared_today >= cap:
        return GuardrailCheck(
            ok=False,
            reason=(
                f"tetto giornaliero raggiunto ({prepared_today}/{cap} candidature preparate "
                "oggi): riprova domani, o alza daily_application_cap in worker/.env"
            ),
        )
    return GuardrailCheck(ok=True)


def check_new_company(
    prior_applications_to_company: int, *, confirmed: bool
) -> GuardrailCheck:
    """La prima candidatura verso un'azienda mai vista richiede una conferma esplicita.

    ``confirmed`` arriva dal payload del task: la dashboard lo mette a
    ``True`` solo dopo che l'utente ha risposto a un dialogo apposta (vedi
    ``web/src/lib/cv-actions.ts``). Un secondo task verso la stessa azienda
    non lo richiede piu' — ``prior_applications_to_company`` conta anche le
    candidature non ancora spedite, quindi basta che una sia arrivata almeno
    alla preparazione.
    """
    if prior_applications_to_company > 0 or confirmed:
        return GuardrailCheck(ok=True)
    return GuardrailCheck(
        ok=False,
        reason="prima candidatura verso questa azienda: serve una conferma esplicita",
        needs_company_confirmation=True,
    )
