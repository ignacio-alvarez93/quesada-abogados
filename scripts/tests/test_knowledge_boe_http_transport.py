import json
from pathlib import Path
import urllib.error

import pytest

import backend.knowledge.boe.transport as transport_module
from backend.knowledge.boe import (
    BOE_DOCUMENT_XML_ENDPOINT,
    BOE_SUMMARY_ENDPOINT,
    BoeHttpTransport,
    BoeTransportError,
    parse_boe_xml_document_payload,
)


FIXTURE_DIR = (
    Path(__file__).parent
    / "fixtures"
    / "knowledge"
    / "boe"
)


def _xml_fixture():
    return (
        FIXTURE_DIR
        / "document_real_shape.xml"
    ).read_bytes()


class _FakeResponse:
    def __init__(
        self,
        body,
        *,
        status=200,
    ):
        self._body = body
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc,
        traceback,
    ):
        return False


def test_real_shape_xml_maps_to_native_boe_payload():
    payload = parse_boe_xml_document_payload(
        "BOE-A-2026-15300",
        _xml_fixture(),
    )

    assert payload["id"] == "BOE-A-2026-15300"
    assert payload["published_on"] == "2026-07-14"
    assert payload["language"] == "es"
    assert payload["url"] == (
        "https://www.boe.es/eli/es/ai/2026/06/17/(1)"
    )

    assert "Artículo 1. Objeto." in payload["text"]

    metadata = payload["metadata"]

    assert metadata["rango"] == "Acuerdo Internacional"
    assert metadata["rango_codigo"] == "1180"
    assert metadata["departamento_codigo"] == "9562"
    assert metadata["pagina_inicial"] == "97970"
    assert metadata["pagina_final"] == "97979"
    assert metadata["estatus_legislativo"] == "L"
    assert metadata["boe_source_updated_at"] == (
        "20260720145601"
    )


def test_real_shape_xml_rejects_identity_mismatch():
    with pytest.raises(
        ValueError,
        match="identificador no coincide",
    ):
        parse_boe_xml_document_payload(
            "BOE-A-2026-OTHER",
            _xml_fixture(),
        )


def test_http_transport_requires_explicit_summary_date():
    transport = BoeHttpTransport()

    with pytest.raises(
        ValueError,
        match="fecha explícita",
    ):
        transport.discover()


def test_http_transport_rejects_invalid_summary_date():
    transport = BoeHttpTransport()

    with pytest.raises(
        ValueError,
        match="no es válida",
    ):
        transport.discover(
            cursor="20260231"
        )


def test_http_transport_uses_official_summary_endpoint(
    monkeypatch,
):
    calls = []

    payload = {
        "status": {
            "code": "200",
            "text": "ok",
        },
        "data": {
            "sumario": {
                "metadatos": {
                    "publicacion": "BOE",
                    "fecha_publicacion": "20260714",
                },
                "diario": [],
            }
        },
    }

    def fake_urlopen(
        request,
        timeout,
    ):
        calls.append(
            (
                request,
                timeout,
            )
        )

        return _FakeResponse(
            json.dumps(
                payload
            ).encode("utf-8")
        )

    monkeypatch.setattr(
        transport_module.urllib.request,
        "urlopen",
        fake_urlopen,
    )

    transport = BoeHttpTransport(
        timeout_seconds=12,
    )

    result = transport.discover(
        cursor="20260714"
    )

    assert result == payload
    assert len(calls) == 1

    request, timeout = calls[0]

    assert request.full_url == (
        BOE_SUMMARY_ENDPOINT.format(
            date="20260714"
        )
    )
    assert timeout == 12

    headers = {
        key.lower(): value
        for key, value
        in request.header_items()
    }

    assert headers["accept"] == "application/json"
    assert (
        headers["user-agent"]
        == "QuesadaAbogados-Knowledge/1.0"
    )


def test_http_transport_fetches_and_maps_xml(
    monkeypatch,
):
    calls = []

    def fake_urlopen(
        request,
        timeout,
    ):
        calls.append(
            request.full_url
        )

        return _FakeResponse(
            _xml_fixture()
        )

    monkeypatch.setattr(
        transport_module.urllib.request,
        "urlopen",
        fake_urlopen,
    )

    transport = BoeHttpTransport()

    payload = transport.fetch(
        "BOE-A-2026-15300"
    )

    assert calls == [
        BOE_DOCUMENT_XML_ENDPOINT.format(
            external_id=(
                "BOE-A-2026-15300"
            )
        )
    ]

    assert payload["id"] == "BOE-A-2026-15300"
    assert payload["published_on"] == "2026-07-14"
    assert (
        payload["metadata"]["url_pdf"]
        .endswith(
            "BOE-A-2026-15300.pdf"
        )
    )


def test_http_transport_wraps_http_error(
    monkeypatch,
):
    def fake_urlopen(
        request,
        timeout,
    ):
        raise urllib.error.HTTPError(
            request.full_url,
            404,
            "Not Found",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(
        transport_module.urllib.request,
        "urlopen",
        fake_urlopen,
    )

    with pytest.raises(
        BoeTransportError,
        match="404",
    ):
        BoeHttpTransport().discover(
            cursor="20260714"
        )


def test_http_transport_rejects_invalid_json(
    monkeypatch,
):
    def fake_urlopen(
        request,
        timeout,
    ):
        return _FakeResponse(
            b"not-json"
        )

    monkeypatch.setattr(
        transport_module.urllib.request,
        "urlopen",
        fake_urlopen,
    )

    with pytest.raises(
        BoeTransportError,
        match="JSON",
    ):
        BoeHttpTransport().discover(
            cursor="20260714"
        )
