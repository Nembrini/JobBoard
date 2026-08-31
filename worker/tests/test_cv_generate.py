"""Test della Fase 6: validatore anti-invenzione, template ATS, fit a una pagina.

Nessun database e nessuna chiamata LLM: il provider e' finto e restituisce CV
scritti a mano. I test che producono un PDF usano Playwright, come gia' fa
``conftest.py`` per i CV di prova in ingresso.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jobboard.ai.tailor import LINGUA_PREDEFINITA, TailoredCV, build_prompt, language_for
from jobboard.ai.validator import feedback, numeri, validate
from jobboard.cv.generate import GenerationError, file_name, generate, storage_path_for
from jobboard.cv.render import DENSITA, HEADINGS, build_html, extract_text, page_count
from jobboard.schemas import ApplicantInfoBank, ApplicantInfoItem
from tests.conftest_cv import CV_ONESTO, ProviderFinto, annuncio, cv, profilo


def _pool(**overrides: object) -> ApplicantInfoBank:
    voce = ApplicantInfoItem(
        **{
            "id": "disponibilita-trasferte",
            "label": "Disponibilità",
            "text": "Disponibile a trasferte fino a tre giorni al mese.",
            **overrides,
        }
    )
    return ApplicantInfoBank(items=[voce])


# --- il caso normale ----------------------------------------------------------


def test_un_cv_onesto_passa() -> None:
    """La linea di base: se questo fallisce, il validatore blocca tutto.

    Il CV traduce le soft skill, usa la grafia dell'annuncio per le tecnologie e
    converte in cifre i numeri che il profilo scrive a lettere: tre cose giuste
    che una versione ingenua del validatore scambierebbe per invenzioni.
    """
    assert validate(cv(), profilo()) == []


# --- regola 1: ogni frase ha una fonte ----------------------------------------


def test_un_bullet_senza_fonte_nel_profilo_e_una_violazione() -> None:
    guasto = cv(
        experience=[{"id": "acme-be", "bullets": [{"source_id": "inventato-9", "text": "Cose."}]}]
    )
    violazioni = validate(guasto, profilo())
    assert [v.regola for v in violazioni] == ["bullet-inesistente"]


def test_un_bullet_attribuito_al_datore_di_lavoro_sbagliato_e_una_violazione() -> None:
    """Il caso piu' grave: la frase e' vera, l'azienda no.

    Un id che esiste non basta: sotto Globex, un bullet di Acme diventa
    un'affermazione falsa su chi ha fatto cosa e dove.
    """
    guasto = cv(
        experience=[{"id": "globex-jr", "bullets": [{"source_id": "acme-be-1", "text": "Cose."}]}]
    )
    violazioni = validate(guasto, profilo())
    assert [v.regola for v in violazioni] == ["bullet-di-un-altra-esperienza"]
    assert "un'altra esperienza" in violazioni[0].dettaglio


def test_un_esperienza_inventata_e_una_violazione() -> None:
    guasto = cv(experience=[{"id": "azienda-mai-vista", "bullets": []}])
    assert [v.regola for v in validate(guasto, profilo())] == ["esperienza-inesistente"]


# --- regola 2: le cifre non si inventano --------------------------------------


def test_una_percentuale_inventata_blocca_il_cv() -> None:
    """Il guasto che questa fase esiste per impedire.

    "Ridotto" diventa "ridotto del 40%": la frase e' plausibile, la fonte non
    dice niente del genere, e in un colloquio non si recupera.
    """
    guasto = cv(
        experience=[
            {
                "id": "acme-be",
                "bullets": [
                    {
                        "source_id": "acme-be-2",
                        "text": "Migrated the database to PostgreSQL, improving latency by 35%.",
                    }
                ],
            }
        ]
    )
    violazioni = validate(guasto, profilo())
    assert [v.regola for v in violazioni] == ["cifra-inventata"]
    assert "35" in violazioni[0].dettaglio


def test_le_cifre_scritte_a_lettere_nel_profilo_valgono_come_cifre() -> None:
    """Il falso positivo che renderebbe inutile il validatore.

    Il profilo dice "da sei ore a venti minuti" e "dal quaranta all'ottanta
    percento" — cosi' scrivono i CV veri. Il CV generato scrive 6, 20, 40%, 80%,
    perche' cosi' si scrive un CV. Sono le stesse affermazioni.
    """
    assert validate(cv(), profilo()) == []


def test_un_numero_nel_summary_si_confronta_con_tutto_il_profilo() -> None:
    guasto = cv(summary="Backend developer with 15 years of experience in Python.")
    violazioni = validate(guasto, profilo())
    assert [v.regola for v in violazioni] == ["cifra-inventata"]
    assert violazioni[0].dove == "summary"


@pytest.mark.parametrize(
    ("testo", "atteso"),
    [
        ("da sei ore a venti minuti", {6, 20}),
        ("ridotto da 6 ore a 20 minuti", {6, 20}),
        ("quaranta milioni di righe", {40_000_000}),
        ("40M di righe", {40_000_000}),
        ("dal quaranta all'ottanta percento", {40, 80}),
        ("ventotto progetti, trentuno clienti", {28, 31}),
        ("forty-five servizi", {45}),
        ("1.000 utenti", {1000}),
        ("1,5 milioni", {1_500_000}),
        ("budget da 50k euro", {50_000}),
        # "per cento" e' un'unita' di misura, non il numero cento: senza questa
        # eccezione una percentuale scritta a parole introduce un 100 fantasma.
        ("copertura dal 40 all'80 per cento", {40, 80}),
        ("cento clienti", {100}),
    ],
)
def test_estrazione_dei_numeri(testo: str, atteso: set[float]) -> None:
    assert numeri(testo) == {float(v) for v in atteso}


# --- regola 3: le competenze si dichiarano solo se dichiarate -----------------


def test_una_competenza_senza_provenienza_nel_profilo_e_una_violazione() -> None:
    guasto = cv(
        skills={"hard": [{"text": "Kubernetes", "source": "Kubernetes"}], "soft": []},
    )
    violazioni = validate(guasto, profilo())
    assert [v.regola for v in violazioni] == ["skill-non-dichiarata"]


def test_java_non_giustifica_javascript() -> None:
    """Il buco della prima versione, che confrontava per prefisso.

    ``"javascript".startswith("java")``: un profilo che dichiara Java
    giustificava un CV che dichiara JavaScript. Con la provenienza dichiarata il
    confronto e' esatto e il caso non si pone.
    """
    guasto = cv(skills={"hard": [{"text": "JavaScript", "source": "JavaScript"}], "soft": []})
    assert [v.regola for v in validate(guasto, profilo())] == ["skill-non-dichiarata"]


def test_una_grafia_diversa_della_stessa_tecnologia_passa() -> None:
    """ "Postgres" nel CV, "PostgreSQL" nel profilo: e' la parola dell'annuncio."""
    buono = cv(skills={"hard": [{"text": "Postgres", "source": "PostgreSQL"}], "soft": []})
    assert validate(buono, profilo()) == []


def test_una_soft_skill_tradotta_passa_se_dichiara_l_originale() -> None:
    """Senza questo, la Fase 6.7 e la 6.2 si escluderebbero a vicenda."""
    buono = cv(skills={"hard": [], "soft": [{"text": "Teamwork", "source": "Lavoro in team"}]})
    assert validate(buono, profilo()) == []


# --- regola 4: additional_info segue le regole 1 e 2, contro il pool ----------


def test_una_voce_aggiuntiva_con_fonte_vera_passa() -> None:
    buono = cv(
        additional_info=[
            {
                "source_id": "disponibilita-trasferte",
                "text": "Available for up to 3 days of travel a month.",
            }
        ]
    )
    assert validate(buono, profilo(), _pool()) == []


def test_una_voce_aggiuntiva_senza_pool_e_una_violazione() -> None:
    """Nessun pool passato al validatore: qualunque source_id citato e' inventato."""
    guasto = cv(additional_info=[{"source_id": "disponibilita-trasferte", "text": "Cose."}])
    violazioni = validate(guasto, profilo(), None)
    assert [v.regola for v in violazioni] == ["informazione-inesistente"]


def test_una_voce_aggiuntiva_con_id_inesistente_nel_pool_e_una_violazione() -> None:
    guasto = cv(additional_info=[{"source_id": "id-mai-visto", "text": "Cose."}])
    violazioni = validate(guasto, profilo(), _pool())
    assert [v.regola for v in violazioni] == ["informazione-inesistente"]


def test_una_cifra_inventata_in_una_voce_aggiuntiva_e_una_violazione() -> None:
    guasto = cv(
        additional_info=[
            {
                "source_id": "disponibilita-trasferte",
                "text": "Available for up to 10 days of travel a month.",
            }
        ]
    )
    violazioni = validate(guasto, profilo(), _pool())
    assert [v.regola for v in violazioni] == ["cifra-inventata"]
    assert "10" in violazioni[0].dettaglio


def test_il_summary_puo_citare_un_numero_della_voce_aggiuntiva() -> None:
    """Il pool entra nel confronto dei numeri del summary, non solo dei bullet."""
    buono = cv(summary="Backend developer available for up to 3 days of travel a month in Python.")
    assert validate(buono, profilo(), _pool()) == []


def test_il_prompt_include_il_pool_solo_se_non_vuoto() -> None:
    con_pool = build_prompt(profilo(), annuncio(), applicant_info=_pool())
    assert "[id: disponibilita-trasferte]" in con_pool
    assert "INFORMAZIONI APPLICANTE" in con_pool

    senza_pool = build_prompt(profilo(), annuncio(), applicant_info=ApplicantInfoBank())
    assert "INFORMAZIONI APPLICANTE" not in senza_pool


# --- correzione ---------------------------------------------------------------


def test_il_feedback_nomina_il_punto_da_correggere() -> None:
    violazioni = validate(cv(summary="Ten years and 99 projects."), profilo())
    testo = feedback(violazioni)
    assert "summary" in testo
    assert "CORREZIONI OBBLIGATORIE" in testo


# --- lingua (6.7) -------------------------------------------------------------


@pytest.mark.parametrize(
    ("dichiarata", "attesa"),
    [("it", "it"), ("en", "en"), ("de", "de"), ("EN", "en"), ("en-GB", "en")],
)
def test_la_lingua_del_cv_segue_quella_dell_annuncio(dichiarata: str, attesa: str) -> None:
    assert language_for(annuncio(lang=dichiarata)) == attesa


@pytest.mark.parametrize("dichiarata", [None, "", "pl", "zh"])
def test_una_lingua_che_non_sappiamo_impaginare_ricade_sull_inglese(dichiarata: str | None) -> None:
    """Non sul paese e non sull'italiano: l'inglese e' quello che ogni ATS legge."""
    assert language_for(annuncio(lang=dichiarata)) == LINGUA_PREDEFINITA


def test_ogni_lingua_ammessa_ha_i_suoi_heading() -> None:
    """Una lingua senza heading produrrebbe un CV meta' tradotto."""
    from jobboard.ai.tailor import LINGUE

    for lingua in LINGUE:
        assert lingua in HEADINGS, f"heading mancanti per {lingua}"
        assert set(HEADINGS[lingua]) == set(HEADINGS[LINGUA_PREDEFINITA])


# --- il prompt ----------------------------------------------------------------


def test_il_prompt_espone_gli_id_che_il_modello_deve_ricopiare() -> None:
    testo = build_prompt(profilo(), annuncio())
    assert "[id: acme-be]" in testo
    assert "[id: acme-be-1]" in testo


def test_i_gap_arrivano_al_modello_come_cose_da_non_colmare() -> None:
    """Senza, il modo piu' naturale di adattare un CV e' scrivere di saper fare
    proprio la cosa che manca."""
    testo = build_prompt(profilo(), annuncio(), gaps=["Kubernetes non dichiarato"])
    assert "Kubernetes non dichiarato" in testo
    assert "Non colmarli" in testo


# --- template ATS-safe (6.3) --------------------------------------------------


def test_il_template_non_usa_niente_di_cio_che_rompe_un_parser() -> None:
    html = build_html(cv(), profilo(), lingua="en")
    for vietato in ("<table", "<td", "<img", "<svg", "column-count", "position: absolute"):
        assert vietato not in html, f"il template contiene {vietato}"


def test_il_template_stampa_la_grafia_scelta_e_non_la_provenienza() -> None:
    html = build_html(cv(), profilo(), lingua="en")
    # Si guarda la riga delle competenze e non tutto il documento: "PostgreSQL"
    # compare legittimamente nel summary, dove il modello l'ha scritto.
    riga = html.split("<h2>Skills</h2>", 1)[1].split("<h2>", 1)[0]
    assert "Postgres ·" in riga or riga.strip().endswith("Postgres</p>")
    # `source` serve al validatore, non al lettore: non deve finire nel documento.
    assert "PostgreSQL" not in riga


def test_le_esperienze_escono_in_ordine_cronologico_inverso() -> None:
    """L'ordine non lo decide il modello: quello in corso viene per primo."""
    invertito = cv(
        experience=[CV_ONESTO["experience"][1], CV_ONESTO["experience"][0]],
    )
    html = build_html(invertito, profilo(), lingua="en")
    assert html.index("Acme Srl") < html.index("Globex SpA")


def test_gli_heading_sono_quelli_della_lingua_richiesta() -> None:
    italiano = build_html(cv(), profilo(), lingua="it")
    assert "Esperienza professionale" in italiano
    assert "Experience" not in italiano


def test_le_date_sono_numeriche_e_senza_lingua() -> None:
    """Un mese scritto a lettere va tradotto, e un mese tradotto male e' una data
    che il parser scarta."""
    html = build_html(cv(), profilo(), lingua="fr")
    assert "01/2022" in html
    # L'apostrofo esce come entita' HTML: e' l'autoescape del template, che qui
    # e' esattamente cio' che si vuole.
    assert "Aujourd&#39;hui" in html


# --- nomi e percorsi (6.5) ----------------------------------------------------


def test_il_nome_del_file_viene_dal_profilo() -> None:
    assert file_name(profilo()) == "Filippo_Nembrini_Resume.pdf"


def test_il_percorso_ha_una_cartella_per_annuncio() -> None:
    """Cosi' il nome visibile del file resta sempre lo stesso senza sovrascrivere
    il CV di un'altra candidatura."""
    assert storage_path_for(77, profilo()) == "77/Filippo_Nembrini_Resume.pdf"


# --- orchestrazione -----------------------------------------------------------


def test_un_cv_bocciato_tre_volte_non_produce_nessun_pdf(tmp_path: Path) -> None:
    """Il blocco che rende spedibile quello che arriva in dashboard."""
    inventato = cv(summary="Backend developer with 99 years of experience.")
    provider = ProviderFinto(inventato)

    with pytest.raises(GenerationError) as errore:
        generate(provider, profilo(), annuncio(), tmp_path / "cv.pdf", max_tentativi=3)

    assert provider.chiamate == 3
    assert "99" in str(errore.value)
    assert not (tmp_path / "cv.pdf").exists()


def test_il_secondo_tentativo_riceve_l_elenco_degli_errori(tmp_path: Path) -> None:
    """Rigenerare senza dire cosa era sbagliato ripeterebbe lo stesso errore."""
    provider = ProviderFinto(cv(summary="Backend developer, 99 years."), cv())
    risultato = generate(provider, profilo(), annuncio(), tmp_path / "cv.pdf")

    assert risultato.tentativi == 2
    assert "CORREZIONI OBBLIGATORIE" in provider.prompt_ricevuti[1]
    assert "CORREZIONI OBBLIGATORIE" not in provider.prompt_ricevuti[0]


def test_da_un_annuncio_esce_un_pdf_di_una_pagina_con_testo_estraibile(tmp_path: Path) -> None:
    """La verifica della fase, in miniatura: una pagina, testo vero, sezioni ATS."""
    pdf = tmp_path / "cv.pdf"
    risultato = generate(ProviderFinto(cv()), profilo(), annuncio(), pdf)

    assert risultato.pagine == 1
    assert page_count(pdf) == 1
    assert risultato.lingua == "en"
    assert risultato.fit.densita is DENSITA[0], "non doveva servire stringere"

    testo = extract_text(pdf).upper()
    assert len(testo) > 400, "un PDF senza testo estraibile e' un foglio bianco per un ATS"
    for sezione in ("PROFESSIONAL SUMMARY", "EXPERIENCE", "SKILLS", "EDUCATION"):
        assert sezione in testo
    assert "FILIPPO NEMBRINI" in testo
    assert "FILIPPO@EXAMPLE.COM" in testo


def test_un_cv_troppo_lungo_viene_prima_accorciato_e_poi_stretto(tmp_path: Path) -> None:
    """L'ordine dei rimedi: prima si toglie contenuto, poi si stringe.

    Il provider finto rifiuta di accorciare — restituisce sempre lo stesso CV
    lunghissimo — quindi il loop esaurisce le compressioni e deve arrivare alla
    densita' minima. E' il caso peggiore, ed e' quello che va verificato.
    """
    lungo = _cv_lunghissimo()
    provider = ProviderFinto(lungo)
    risultato = generate(provider, profilo(), annuncio(), tmp_path / "cv.pdf")

    assert risultato.fit.compressioni > 0, "doveva provare a tagliare contenuto prima"
    assert risultato.fit.densita is not DENSITA[0], "poi doveva stringere"
    assert risultato.pagine == 1, "e alla fine doveva starci"
    assert (tmp_path / "cv.pdf").is_file()


def _cv_lunghissimo() -> TailoredCV:
    """Un CV che non sta in una pagina, costruito ripetendo bullet leciti.

    I bullet sono duplicati della stessa fonte: restano validi (stesso
    ``source_id``, stesse cifre), quindi il documento supera il validatore e
    arriva davvero al loop di fit, che e' quello che si vuole provare.
    """
    riempimento = [
        {"source_id": "acme-be-1", "text": CV_ONESTO["experience"][0]["bullets"][0]["text"]}
        for _ in range(28)
    ]
    return cv(
        experience=[{"id": "acme-be", "bullets": riempimento}],
        summary=CV_ONESTO["summary"],
    )
