"""Test dell'autofill euristico (Fase 7.3): nessun browser, solo testo e punteggi."""

from __future__ import annotations

from jobboard.apply.fields import FieldPlan
from jobboard.apply.heuristics import DetectedField, find_resume_field, match_fields


def _campo(
    kind: str, label: str = "", name: str = "", element_id: str = "", order: int = 0
) -> DetectedField:
    return DetectedField(  # type: ignore[arg-type]
        kind=kind, label=label, name=name, element_id=element_id, order=order
    )


def test_trova_il_campo_per_label() -> None:
    campi = [_campo("text", label="Email address")]
    piano = FieldPlan(values={"email": "filippo@example.com"})
    azioni = match_fields(campi, piano)
    assert len(azioni) == 1
    assert azioni[0].logical_key == "email"
    assert azioni[0].value == "filippo@example.com"


def test_trova_il_campo_per_attributo_name_quando_manca_la_label() -> None:
    campi = [_campo("tel", name="candidate[phone]")]
    piano = FieldPlan(values={"phone": "+39 333 1234567"})
    azioni = match_fields(campi, piano)
    assert azioni[0].field.name == "candidate[phone]"


def test_last_name_non_ruba_il_campo_di_first_name() -> None:
    """'last name' contiene 'name' ma non deve mai vincere su first_name."""
    campi = [
        _campo("text", label="First Name", order=0),
        _campo("text", label="Last Name", order=1),
    ]
    piano = FieldPlan(values={"first_name": "Filippo", "last_name": "Nembrini"})
    azioni = {a.logical_key: a.field.label for a in match_fields(campi, piano)}
    assert azioni == {"first_name": "First Name", "last_name": "Last Name"}


def test_un_campo_gia_assegnato_non_viene_riusato() -> None:
    """'Nome e cognome' contiene sia 'nome' sia 'cognome': non deve finire assegnato a entrambi."""
    campi = [_campo("text", label="Nome e cognome")]
    piano = FieldPlan(values={"first_name": "Filippo", "last_name": "Nembrini"})
    azioni = match_fields(campi, piano)
    assert len(azioni) == 1


def test_nessuna_corrispondenza_non_produce_azioni() -> None:
    campi = [_campo("text", label="Codice fiscale")]
    piano = FieldPlan(values={"email": "filippo@example.com"})
    assert match_fields(campi, piano) == []


def test_campo_vuoto_nel_piano_viene_ignorato() -> None:
    campi = [_campo("text", label="Phone")]
    piano = FieldPlan(values={"phone": ""})
    assert match_fields(campi, piano) == []


def test_checkbox_booleano_riceve_true_o_false_come_stringa() -> None:
    campi = [_campo("checkbox", label="Willing to relocate")]
    piano = FieldPlan(booleans={"willing_to_relocate": True})
    azioni = match_fields(campi, piano)
    assert azioni[0].value == "true"


def test_a_parita_di_punteggio_vince_il_campo_prima_nel_dom() -> None:
    """Un form con un secondo campo 'nome' demografico più in basso non deve vincere."""
    campi = [
        _campo("text", label="First name", order=0),
        _campo("text", label="Legal first name", order=5),
    ]
    piano = FieldPlan(values={"first_name": "Filippo"})
    azioni = match_fields(campi, piano)
    assert azioni[0].field.order == 0


def test_domanda_extra_si_trova_per_la_sua_stessa_label() -> None:
    campi = [_campo("textarea", label="Perche' vuoi lavorare qui?")]
    piano = FieldPlan(values={"Perche' vuoi lavorare qui?": "Risposta"})
    azioni = match_fields(campi, piano)
    assert azioni[0].value == "Risposta"


def test_trova_il_campo_file_del_curriculum_per_label() -> None:
    campi = [
        _campo("file", label="Cover letter"),
        _campo("file", label="Resume/CV"),
    ]
    trovato = find_resume_field(campi)
    assert trovato is not None
    assert trovato.label == "Resume/CV"


def test_un_solo_campo_file_senza_label_e_comunque_il_curriculum() -> None:
    campi = [_campo("file")]
    assert find_resume_field(campi) is campi[0]


def test_due_campi_file_senza_label_non_si_indovina() -> None:
    campi = [_campo("file"), _campo("file")]
    assert find_resume_field(campi) is None


def test_nessun_campo_file_restituisce_none() -> None:
    assert find_resume_field([_campo("text")]) is None
