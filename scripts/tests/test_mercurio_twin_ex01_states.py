from pathlib import Path


ROOT = Path(__file__).parents[2]

JS = (
    ROOT
    / "tools"
    / "mercurio_lab"
    / "static"
    / "mercurio_ex01.js"
).read_text(
    encoding="utf-8"
)


def test_authorization_to_personal_transition_exists():
    assert (
        'step ===\n                "autorizacionSup"'
        in JS
    )
    assert '"tab-datos_personales"' in JS
    assert '"EX01_PERSONAL"' in JS


def test_selected_ex01_contract_is_persisted_in_dom():
    assert '"idOpcionAutorizacion"' in JS
    assert '"codOpcionAutorizacion"' in JS
    assert '"supuestoSeleccionadoSup"' in JS

    assert (
        '"EX-01-2-01"'
        in JS
    )

    assert '"MER"' in JS
    assert '"NLR"' in JS


def test_personal_to_presenter_transition_exists():
    assert 'step === "personales"' in JS
    assert '"tab-datos_presentador"' in JS
    assert '"EX01_PRESENTER"' in JS


def test_presenter_to_notification_transition_exists():
    assert 'step === "presentador"' in JS
    assert '"tab-datos_notificacion"' in JS
    assert '"EX01_NOTIFICATION"' in JS


def test_conclude_goes_only_to_local_document_stage():
    assert "window.enviaDatosSup" in JS

    assert (
        "presentacionTelematicaDocumentacion.html"
        in JS
    )

    assert (
        "delegaciondelgobierno.gob.es"
        not in JS
    )


def test_ex01_tabs_follow_real_progressive_state_machine():
    from pathlib import Path

    js = (
        Path(
            "tools/mercurio_lab/static/"
            "mercurio_ex01.js"
        )
        .read_text(encoding="utf-8")
    )

    required = (
        "const TAB_ORDER",
        "function updateTabStates(panelId)",
        '"r-tabs-state-active"',
        '"r-tabs-state-default"',
        '"r-tabs-state-disabled"',
        "updateTabStates(panelId);",
        '"d-li-personales"',
        '"d-li-presentador"',
        '"d-li-notificacion"',
    )

    for token in required:
        assert token in js
