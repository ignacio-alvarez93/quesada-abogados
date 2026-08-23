import threading
import urllib.request

from tools.mercurio_lab.server import (
    DOCUMENT_PATH,
    MercurioLabHandler,
    MercurioLabServer,
)


def _get(base_url: str, path: str) -> str:
    with urllib.request.urlopen(
        base_url + path,
        timeout=5,
    ) as response:
        assert response.status == 200
        return response.read().decode("utf-8")


def test_general_twin_routes_are_navigable():
    server = MercurioLabServer(
        ("127.0.0.1", 0),
        MercurioLabHandler,
    )

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )
    thread.start()

    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        cases = (
            (
                "/",
                "SEDE_HOME",
            ),
            (
                "/procedimientos/index/categoria/34",
                "SEDE_EXTRANJERIA",
            ),
            (
                "/pagina/index/directorio/mercurio2",
                "SEDE_MERCURIO",
            ),
            (
                "/mercurio/inicioMercurio.html",
                "MERCURIO_INICIO",
            ),
            (
                "/mercurio/modoAcceso.html",
                "MERCURIO_MODO_ACCESO",
            ),
            (
                "/mercurio/entradaMercurio.html",
                "MERCURIO_ENTRY_IDLE",
            ),
        )

        for path, state in cases:
            html = _get(base, path)

            assert 'data-mercurio-twin="1"' in html
            assert (
                f'data-mercurio-state="{state}"'
                in html
            )

        models = _get(
            base,
            "/mercurio/seleccionModelo-33.html",
        )

        assert (
            'data-mercurio-state='
            '"MERCURIO_MODEL_SELECTION"'
            in models
        )
        assert 'name="datosForL"' in models
        assert 'value="EX01"' in models
        assert 'value="EX26"' in models

        documentation = _get(
            base,
            DOCUMENT_PATH,
        )

        assert 'id="listaIdsDocOb"' in documentation

    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
