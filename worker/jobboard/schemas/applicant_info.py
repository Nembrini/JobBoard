"""``ApplicantInfoBank``: il pool libero di fatti extra del candidato.

Diverso sia dal :class:`~jobboard.schemas.profile.MasterProfile` sia da
:class:`~jobboard.schemas.candidate.CandidateAnswers`, e per un motivo preciso.

* Il ``MasterProfile`` e' il CV **rivisto**: ogni bullet e' gia' passato sotto gli
  occhi di Filippo, e la Fase 6 lo tratta come l'unica fonte di verita' possibile.
* ``CandidateAnswers`` sono i dati per compilare un form — telefono, permesso di
  lavoro, preavviso — che non descrivono un traguardo, non entrano nella prosa di
  un CV.
* Questo pool sta in mezzo: fatti veri sul candidato che non sono (ancora, o mai)
  finiti in una voce del CV master — un risultato citato in un colloquio ma mai
  scritto, la lingua parlata a un livello base che non merita una riga tutta sua,
  la disponibilita' a una trasferta. La Fase 6 puo' pescarci **in aggiunta** al
  profilo, scegliendo le voci pertinenti per l'annuncio, con la stessa garanzia
  del resto: ogni voce ha un ``id`` a cui il validatore anti-invenzione puo'
  risalire, e ogni cifra citata deve comparire nel testo di partenza.

Come per il resto del profilo, l'``id`` si assegna alla creazione e non si
modifica: e' la chiave con cui Fase 6 e Fase 6.2 si parlano.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

#: Quante voci puo' contenere il pool. Non e' un limite tecnico ma editoriale: un
#: pool di centinaia di voci non e' piu' qualcosa che un candidato rivede a mano,
#: ed e' anche piu' testo di quanto la Fase 6 debba leggere per scegliere tre
#: fatti pertinenti.
MAX_ITEMS = 200


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ApplicantInfoItem(_Base):
    """Una voce libera: un fatto, un risultato, una risposta gia' pronta."""

    id: str = Field(description="Stabile e univoco, es. 'disponibilita-trasferte'")
    #: Categoria o domanda a cui la voce risponde, es. "Disponibilita'",
    #: "Motivazione", "Progetto extra". Libero: non e' un enum perche' le domande
    #: che un form o un colloquio possono fare non sono un elenco chiuso.
    label: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError(f"id non valido: {v!r} (atteso kebab-case)")
        return v


class ApplicantInfoBank(_Base):
    """Il pool per intero. Singleton sul database, come il resto del profilo."""

    items: list[ApplicantInfoItem] = Field(default_factory=list, max_length=MAX_ITEMS)

    @model_validator(mode="after")
    def _unique_ids(self) -> ApplicantInfoBank:
        visti: set[str] = set()
        duplicati: set[str] = set()
        for voce in self.items:
            (duplicati if voce.id in visti else visti).add(voce.id)
        if duplicati:
            raise ValueError(f"id duplicati nel pool: {sorted(duplicati)}")
        return self

    def to_prompt_block(self) -> str:
        """Le voci come testo per il prompt della Fase 6, con l'id ben visibile.

        Vuoto se il pool e' vuoto: il chiamante decide se includere il blocco,
        questo metodo non emette un'intestazione senza contenuto sotto.
        """
        return "\n".join(f"[id: {voce.id}] {voce.label}: {voce.text}" for voce in self.items)

    def known_texts(self) -> dict[str, str]:
        """Id -> testo, per il controllo delle cifre in :mod:`jobboard.ai.validator`."""
        return {voce.id: voce.text for voce in self.items}
