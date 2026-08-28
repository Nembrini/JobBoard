"""``MasterProfile``: la rappresentazione strutturata del CV di partenza.

E' la radice di tutto il sistema. I punteggi di compatibilita' si calcolano su
questo, e ogni CV su misura viene costruito **solo** da queste voci: il
validatore anti-invenzione della Fase 6 rifiuta qualunque affermazione che non
risalga a un elemento di questo oggetto.

Da qui due scelte di forma:

* ogni esperienza e ogni bullet hanno un ``id`` stabile, cosi' il validatore puo'
  dire *quale* voce giustifica una frase, non solo che "esiste da qualche parte";
* i bullet sono gia' scomposti secondo **ACR** (Action-Context-Result), perche' e'
  il formato che il prompt di riscrittura si aspetta.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: Mese in formato ``YYYY-MM``. I CV scrivono "Gen 2022", "01/2022", "2022":
#: la normalizzazione avviene in fase di estrazione, qui si accetta una sola forma.
YearMonth = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]

#: Livello CEFR, oppure madrelingua.
CefrLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2", "native"]

_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Contact(_Base):
    full_name: str = Field(min_length=2, max_length=120)
    email: str | None = None
    phone: str | None = None
    city: str | None = None
    country: str | None = Field(default=None, description="ISO 3166-1 alpha-2")
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None


class Bullet(_Base):
    """Una singola affermazione verificabile, scomposta secondo ACR."""

    id: str = Field(description="Stabile e univoco nel profilo, es. 'acme-be-1'")
    text: str = Field(min_length=10, max_length=400, description="Il testo come appare nel CV")
    #: Il verbo/azione. La riscrittura puo' cambiarlo, non inventarlo.
    action: str | None = None
    #: Contesto: prodotto, team, scala, vincoli.
    context: str | None = None
    #: Risultato misurabile, se dichiarato. Un CV senza numeri non li acquisisce
    #: per magia: se qui e' ``None``, il CV generato non puo' inventarne.
    result: str | None = None
    #: Tecnologie citate nel bullet, per il matching esatto dello Stadio 1.
    skills: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError(f"id non valido: {v!r} (atteso kebab-case)")
        return v


class Experience(_Base):
    id: str
    company: str
    role: str
    location: str | None = None
    work_mode: Literal["on_site", "hybrid", "remote", "unknown"] = "unknown"
    employment_type: str | None = Field(
        default=None, description="Indeterminato, stage, freelance, ..."
    )
    start: YearMonth
    #: ``None`` significa "in corso".
    end: YearMonth | None = None
    bullets: list[Bullet] = Field(default_factory=list)
    tech: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError(f"id non valido: {v!r} (atteso kebab-case)")
        return v

    @model_validator(mode="after")
    def _dates_ordered(self) -> Experience:
        if self.end and self.end < self.start:
            raise ValueError(f"{self.id}: la data di fine precede quella di inizio")
        return self


class Education(_Base):
    id: str
    institution: str
    degree: str
    field_of_study: str | None = None
    start: YearMonth | None = None
    end: YearMonth | None = None
    grade: str | None = None
    highlights: list[str] = Field(default_factory=list)


class Project(_Base):
    id: str
    name: str
    description: str = Field(max_length=600)
    url: str | None = None
    tech: list[str] = Field(default_factory=list)
    #: Distingue i progetti personali da quelli fatti sul lavoro: alcuni annunci
    #: valutano diversamente le due cose.
    context: Literal["personal", "academic", "professional", "open_source"] = "personal"


class Certification(_Base):
    id: str
    name: str
    issuer: str | None = None
    issued: YearMonth | None = None
    expires: YearMonth | None = None
    credential_url: str | None = None


class LanguageSkill(_Base):
    #: ISO 639-1, es. ``it``, ``en``.
    code: str = Field(min_length=2, max_length=3)
    level: CefrLevel


class Skills(_Base):
    #: Tecnologie, strumenti, linguaggi: quelli su cui si fa matching esatto.
    hard: list[str] = Field(default_factory=list)
    #: Competenze trasversali. Entrano nel CV generato ma non nel punteggio:
    #: dedurle da una job description produce solo rumore.
    soft: list[str] = Field(default_factory=list)


class MasterProfile(_Base):
    """Il CV di partenza, strutturato e verificato a mano una volta sola."""

    contact: Contact
    #: Titolo professionale in una riga, es. "Software Developer".
    headline: str | None = Field(default=None, max_length=120)
    #: Il summary originale. Quello su misura viene rigenerato per ogni annuncio.
    summary: str | None = Field(default=None, max_length=1200)

    experiences: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    skills: Skills = Field(default_factory=Skills)
    languages: list[LanguageSkill] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids(self) -> MasterProfile:
        """Gli id devono essere univoci: il validatore anti-invenzione li usa come chiavi."""
        seen: set[str] = set()
        duplicates: set[str] = set()
        for item_id in self._all_ids():
            (duplicates if item_id in seen else seen).add(item_id)
        if duplicates:
            raise ValueError(f"id duplicati nel profilo: {sorted(duplicates)}")
        return self

    def _all_ids(self) -> list[str]:
        ids = [e.id for e in self.experiences]
        ids += [b.id for e in self.experiences for b in e.bullets]
        ids += [x.id for x in self.education]
        ids += [x.id for x in self.projects]
        ids += [x.id for x in self.certifications]
        return ids

    # -- utilita' per gli stadi successivi ------------------------------------

    def known_skills(self) -> set[str]:
        """Tutte le competenze dichiarate, in minuscolo.

        E' l'insieme rispetto a cui il validatore della Fase 6 decide se una
        skill nel CV generato e' vera o inventata.
        """
        out = {s.lower() for s in self.skills.hard} | {s.lower() for s in self.skills.soft}
        for exp in self.experiences:
            out |= {t.lower() for t in exp.tech}
            for bullet in exp.bullets:
                out |= {s.lower() for s in bullet.skills}
        for project in self.projects:
            out |= {t.lower() for t in project.tech}
        return out

    def to_embedding_text(self) -> str:
        """Testo denso per l'embedding dello Stadio 1.

        Include ruoli, bullet e tecnologie; esclude anagrafica e date, che
        aggiungerebbero solo rumore alla similarita' semantica.
        """
        parts: list[str] = []
        if self.headline:
            parts.append(self.headline)
        if self.summary:
            parts.append(self.summary)
        for exp in self.experiences:
            parts.append(f"{exp.role} presso {exp.company}")
            parts.extend(b.text for b in exp.bullets)
            if exp.tech:
                parts.append(", ".join(exp.tech))
        for project in self.projects:
            parts.append(f"{project.name}: {project.description}")
        if self.skills.hard:
            parts.append(", ".join(self.skills.hard))
        for edu in self.education:
            parts.append(f"{edu.degree} {edu.field_of_study or ''} {edu.institution}".strip())
        return "\n".join(p for p in parts if p)
