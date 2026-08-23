from pathlib import Path
import threading
import urllib.error
import urllib.request

from tools.mercurio_lab.server import (
    MercurioLabHandler,
    MercurioLabServer,
)


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
        'src="/mercurio/resources/js/plupload.full.min.js"',
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
    expected = (
        "new window.plupload.Uploader",
        'browse_button: "addDou"',
        'url: "uploadDocumento"',
        "multi_selection: false",
        "FilesAdded:",
        "FileUploaded:",
        "state.uploader.start()",
        'byId("fileDocumentoAdjuntos").value =',
    )

    for token in expected:
        assert token in JS

    assert "labPluploadInput" not in HTML
    assert "labPluploadInput" not in JS
    assert "state.selectedFile" not in JS



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


def test_lab_allows_only_document_upload_posts():
    server = MercurioLabServer(
        ("127.0.0.1", 0),
        MercurioLabHandler,
    )
    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )
    thread.start()

    base = "http://127.0.0.1:" + str(server.server_port)
    crlf = bytes((13, 10))
    boundary = "----MercurioLabContract"
    pdf = b"%PDF-1.4 CONTRACT"

    parts = [
        b"--" + boundary.encode(),
        b"Content-Disposition: form-data; name=\"id_tipo_documento\"",
        b"",
        b"47",
        b"--" + boundary.encode(),
        b"Content-Disposition: form-data; name=\"de_documento\"",
        b"",
        b"Seguro de enfermedad",
        b"--" + boundary.encode(),
        b"Content-Disposition: form-data; name=\"file\"; filename=\"contract.pdf\"",
        b"Content-Type: application/pdf",
        b"",
    ]

    body = (
        crlf.join(parts)
        + crlf
        + pdf
        + crlf
        + b"--"
        + boundary.encode()
        + b"--"
        + crlf
    )

    def post(path, data):
        request = urllib.request.Request(
            base + path,
            data=data,
            headers={
                "Content-Type":
                    "multipart/form-data; boundary=" + boundary
            },
            method="POST",
        )
        return urllib.request.urlopen(request)

    try:
        for path in (
            "/mercurio/uploadDocumento",
            "/mercurio/uploadDocumentoRenova",
        ):
            with post(path, body) as response:
                result = response.read().decode("utf-8")
                assert response.status == 200
                assert "contract.pdf" in result
                assert ">47</td>" in result

        for path in (
            "/mercurio/registroEntrada.html",
            "/mercurio/otroPost",
        ):
            try:
                urllib.request.urlopen(
                    urllib.request.Request(
                        base + path,
                        data=b"x",
                        method="POST",
                    )
                )
                raise AssertionError(
                    "POST should be blocked: " + path
                )
            except urllib.error.HTTPError as exc:
                assert exc.code == 405
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_lab_serves_local_calendar_svg():
    required = (
        '"calendar.svg"',
        '"image/svg+xml"',
    )

    for token in required:
        assert token in SERVER

    asset = (
        LAB_ROOT
        / "static"
        / "calendar.svg"
    )

    assert asset.exists()

    svg = asset.read_text(
        encoding="utf-8"
    )

    assert "<svg" in svg
