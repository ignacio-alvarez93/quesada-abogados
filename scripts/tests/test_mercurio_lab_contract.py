from pathlib import Path


ROOT = (
    Path(__file__)
    .parents[2]
)

LAB_ROOT = (
    ROOT
    / "tools"
    / "mercurio_lab"
)

HTML = (
    LAB_ROOT
    / "static"
    / "documentacion.html"
).read_text(
    encoding="utf-8"
)

JS = (
    LAB_ROOT
    / "static"
    / "mercurio_lab.js"
).read_text(
    encoding="utf-8"
)

SERVER = (
    LAB_ROOT
    / "server.py"
).read_text(
    encoding="utf-8"
)


def test_lab_uses_same_documentation_url_fragment():
    assert (
        "presentacionTelematicaDocumentacion.html"
        in SERVER
    )


def test_lab_reproduces_document_dom_contract():
    required = (
        'id="listaIdsDocOb"',
        'value="1|39|47"',
        'id="docAdjuntarAdjuntos"',
        'id="desDocumentoAdjuntos"',
        'id="fileDocumentoAdjuntos"',
        'id="addDou"',
        'id="btnOpeAdjuntar"',
        'id="zonaadj"',
        'id="cont_tabla_datos_adj"',
        'id="tabla_datos_adj"',
        'id="continuaNot"',
        'id="FrmDatos"',
        "input",
        'type="file"',
        'class="moxie-shim"',
    )

    for token in required:
        assert token in HTML


def test_lab_reproduces_observed_document_type_catalog():
    expected = {
        "1":
            (
                "Pasaporte, título de viaje o "
                "cédula de inscripción completos, "
                "válidos y en vigor de la persona "
                "extranjera."
            ),

        "25":
            (
                "En su caso, informe sobre "
                "escolarización de menores a cargo "
                "en españa"
            ),

        "39":
            "Recursos económicos",

        "47":
            (
                "Documentación acreditativa de "
                "seguro de enfermedad"
            ),

        "51":
            "Tasa (mod. 790 cód. 052)",

        "119":
            (
                "Informe positivo de esfuerzo de "
                "integración de la CCAA."
            ),

        "999":
            "Otros documentos que desee aportar",
    }

    for code, label in expected.items():
        assert (
            f'value="{code}"'
            in HTML
        )

        assert (
            label
            in HTML
        )


def test_lab_required_document_contract_matches_capture():
    expected = (
        'iddocob="1"',
        'iddocob="39"',
        'iddocob="47"',
    )

    for token in expected:
        assert token in HTML


def test_lab_mimics_plupload_file_added_semantics():
    assert (
        'byId(\n                "fileDocumentoAdjuntos"\n            ).value ='
        in JS
    )

    assert (
        "state.selectedFile.name"
        in JS
    )

    assert (
        '"labPluploadInput"'
        in JS
    )


def test_lab_mimics_duplicate_document_type_rule():
    assert (
        'code === "999"'
        in JS
    )

    assert (
        'code === "10"'
        in JS
    )

    assert (
        "codeAlreadyAttached"
        in JS
    )


def test_lab_uploaded_row_matches_reader_cell_contract():
    block_start = JS.index(
        "function appendUploadedRow("
    )

    block_end = JS.index(
        "function resetAttachForm(",
        0,
    )

    assert (
        block_start
        > block_end
    )

    block = JS[
        block_start:
    ]

    ordered = (
        "createDeleteCell(",
        "filename;",
        "description;",
        "hash;",
        "code;",
    )

    positions = [
        block.index(
            token
        )
        for token
        in ordered
    ]

    assert (
        positions
        == sorted(
            positions
        )
    )


def test_lab_continuar_uses_required_codes_vs_uploaded_codes():
    assert (
        "requiredCodes()"
        in JS
    )

    assert (
        "uploadedCodes()"
        in JS
    )

    assert (
        "REQUIRED_DOCUMENTS_MISSING"
        in JS
    )

    assert (
        "DOCUMENTATION_COMPLETE"
        in JS
    )


def test_lab_never_submits_real_presentation():
    assert (
        'onsubmit="return false;"'
        in HTML
    )

    assert (
        "POST_DISABLED"
        in SERVER
    )

    assert (
        "do_POST"
        in SERVER
    )

    assert (
        "status=405"
        in SERVER
    )


def test_lab_is_local_only_and_contains_no_real_mercurio_host():
    combined = (
        HTML
        + JS
        + SERVER
    )

    assert (
        'DEFAULT_HOST = "127.0.0.1"'
        in SERVER
    )

    assert (
        "mercurio.delegaciondelgobierno.gob.es"
        not in combined
    )


def test_lab_has_empty_partial_and_complete_fixtures():
    assert (
        'fixture === "empty"'
        in JS
    )

    assert (
        'fixture === "partial"'
        in JS
    )

    assert (
        'fixture === "complete"'
        in JS
    )

    assert (
        '"51"'
        in JS
    )
