import json

from backend.knowledge.boe_consolidated.transport import (
    BoeConsolidatedHttpTransport,
)


TARGET = "BOE-A-2024-24099"


class _RecordingTransport(
    BoeConsolidatedHttpTransport
):
    def __init__(self):
        super().__init__(
            timeout_seconds=1,
        )
        self.calls = []

    def _request_bytes(
        self,
        url,
        *,
        accept,
    ):
        self.calls.append(
            (
                url,
                accept,
            )
        )

        if url.endswith(
            "/metadatos"
        ):
            return json.dumps(
                {
                    "data": [
                        {
                            "identificador": (
                                TARGET
                            )
                        }
                    ]
                }
            ).encode()

        if url.endswith(
            "/analisis"
        ):
            return json.dumps(
                {
                    "data": [
                        {}
                    ]
                }
            ).encode()

        if url.endswith(
            "/texto/indice"
        ):
            return json.dumps(
                {
                    "data": [
                        {
                            "bloque": []
                        }
                    ]
                }
            ).encode()

        if url.endswith(
            "/texto"
        ):
            return (
                b"<response/>"
            )

        return json.dumps(
            {
                "status": {
                    "code": "200",
                    "text": "ok",
                },
                "data": [],
            }
        ).encode()


def test_discovery_uses_explicit_update_date_and_all_results():
    transport = (
        _RecordingTransport()
    )

    transport.discover(
        cursor="20260605"
    )

    assert len(
        transport.calls
    ) == 1

    url, accept = (
        transport.calls[0]
    )

    assert (
        "from=20260605"
        in url
    )

    assert (
        "to=20260605"
        in url
    )

    assert (
        "limit=-1"
        in url
    )

    assert (
        accept
        == "application/json"
    )


def test_fetch_uses_json_for_structured_data_and_xml_for_text():
    transport = (
        _RecordingTransport()
    )

    payload = transport.fetch(
        TARGET
    )

    assert payload[
        "id"
    ] == TARGET

    assert len(
        transport.calls
    ) == 4

    calls = {
        url: accept
        for url, accept
        in transport.calls
    }

    metadata_url = next(
        url
        for url in calls
        if url.endswith(
            "/metadatos"
        )
    )

    analysis_url = next(
        url
        for url in calls
        if url.endswith(
            "/analisis"
        )
    )

    index_url = next(
        url
        for url in calls
        if url.endswith(
            "/texto/indice"
        )
    )

    text_url = next(
        url
        for url in calls
        if url.endswith(
            "/texto"
        )
    )

    assert (
        calls[metadata_url]
        == "application/json"
    )

    assert (
        calls[analysis_url]
        == "application/json"
    )

    assert (
        calls[index_url]
        == "application/json"
    )

    assert (
        "application/xml"
        in calls[text_url]
    )


def test_invalid_discovery_date_is_rejected():
    transport = (
        _RecordingTransport()
    )

    for value in (
        "",
        "20260230",
        "abcdefgh",
        "202601",
    ):
        try:
            transport.discover(
                cursor=value
            )
        except ValueError:
            pass
        else:
            raise AssertionError(
                "fecha inválida aceptada: "
                f"{value!r}"
            )
