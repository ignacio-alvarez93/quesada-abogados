from email.message import Message
import io
import urllib.error

import pytest

from backend.knowledge.eurlex.transport import (
    EurLexHttpTransport,
    EurLexNotFoundError,
    EurLexTransportError,
)


class FakeResponse:
    def __init__(
        self,
        *,
        body=b"payload",
        status=200,
        url="https://resolved.test/item",
        content_type="application/xml",
    ):
        self.status = status
        self._body = body
        self._url = url

        self.headers = Message()
        self.headers[
            "Content-Type"
        ] = content_type

    def read(self):
        return self._body

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc,
        tb,
    ):
        return False


def test_tree_notice_uses_cellar_and_spanish_language():
    seen = []

    def fake_urlopen(
        request,
        timeout,
    ):
        seen.append(
            (
                request,
                timeout,
            )
        )

        return FakeResponse(
            body=b"<NOTICE />",
        )

    transport = EurLexHttpTransport(
        urlopen_fn=fake_urlopen,
        sleep_fn=lambda _: None,
    )

    response = transport.fetch_tree_notice(
        "32016R0399"
    )

    assert response.status == 200

    request, timeout = seen[0]

    assert (
        request.full_url
        == (
            "https://publications.europa.eu/"
            "resource/celex/32016R0399"
        )
    )

    assert (
        request.get_header(
            "Accept-language"
        )
        == "spa"
    )

    assert (
        "notice=tree"
        in request.get_header(
            "Accept"
        )
    )

    assert timeout == 60.0


def test_treaty_celex_is_url_encoded():
    seen = []

    def fake_urlopen(
        request,
        timeout,
    ):
        seen.append(
            request.full_url
        )

        return FakeResponse(
            body=b"<NOTICE />",
        )

    transport = EurLexHttpTransport(
        urlopen_fn=fake_urlopen,
        sleep_fn=lambda _: None,
    )

    transport.fetch_tree_notice(
        "12016M/TXT"
    )

    assert seen == [
        (
            "https://publications.europa.eu/"
            "resource/celex/12016M%2FTXT"
        )
    ]


def test_timeout_is_retried_with_backoff():
    calls = []
    sleeps = []

    def fake_urlopen(
        request,
        timeout,
    ):
        calls.append(
            request.full_url
        )

        if len(calls) < 3:
            raise TimeoutError(
                "temporary"
            )

        return FakeResponse(
            body=b"<NOTICE />",
        )

    transport = EurLexHttpTransport(
        attempts=3,
        backoff_seconds=2,
        urlopen_fn=fake_urlopen,
        sleep_fn=sleeps.append,
    )

    response = transport.fetch_tree_notice(
        "32021L1883"
    )

    assert response.status == 200
    assert len(calls) == 3

    assert sleeps == [
        2.0,
        4.0,
    ]


def test_404_is_not_retried_for_tree_notice():
    calls = []

    def fake_urlopen(
        request,
        timeout,
    ):
        calls.append(
            request.full_url
        )

        raise urllib.error.HTTPError(
            request.full_url,
            404,
            "Not Found",
            hdrs=None,
            fp=io.BytesIO(),
        )

    transport = EurLexHttpTransport(
        attempts=5,
        urlopen_fn=fake_urlopen,
        sleep_fn=lambda _: None,
    )

    with pytest.raises(
        EurLexNotFoundError
    ):
        transport.fetch_tree_notice(
            "32016R0399"
        )

    assert len(calls) == 1


def test_retryable_http_error_is_retried():
    calls = []

    def fake_urlopen(
        request,
        timeout,
    ):
        calls.append(
            request.full_url
        )

        if len(calls) == 1:
            raise urllib.error.HTTPError(
                request.full_url,
                503,
                "Service Unavailable",
                hdrs=None,
                fp=io.BytesIO(),
            )

        return FakeResponse(
            body=b"<NOTICE />",
        )

    transport = EurLexHttpTransport(
        attempts=2,
        urlopen_fn=fake_urlopen,
        sleep_fn=lambda _: None,
    )

    response = transport.fetch_tree_notice(
        "32016R0399"
    )

    assert response.status == 200
    assert len(calls) == 2


def test_non_retryable_http_error_fails_immediately():
    calls = []

    def fake_urlopen(
        request,
        timeout,
    ):
        calls.append(
            request.full_url
        )

        raise urllib.error.HTTPError(
            request.full_url,
            403,
            "Forbidden",
            hdrs=None,
            fp=io.BytesIO(),
        )

    transport = EurLexHttpTransport(
        attempts=4,
        urlopen_fn=fake_urlopen,
        sleep_fn=lambda _: None,
    )

    with pytest.raises(
        EurLexTransportError
    ):
        transport.fetch_tree_notice(
            "32016R0399"
        )

    assert len(calls) == 1


def test_original_content_falls_back_to_eurlex_after_cellar_404():
    urls = []

    def fake_urlopen(
        request,
        timeout,
    ):
        urls.append(
            request.full_url
        )

        if (
            "publications.europa.eu"
            in request.full_url
        ):
            raise urllib.error.HTTPError(
                request.full_url,
                404,
                "Not Found",
                hdrs=None,
                fp=io.BytesIO(),
            )

        return FakeResponse(
            body=b"<html>EU</html>",
            content_type="text/html",
        )

    transport = EurLexHttpTransport(
        urlopen_fn=fake_urlopen,
        sleep_fn=lambda _: None,
    )

    response = (
        transport.fetch_original_content(
            "32024L1233"
        )
    )

    assert (
        response.transport
        == "EUR_LEX_CONTENT"
    )

    assert (
        len(urls)
        == 2
    )

    assert (
        "eur-lex.europa.eu"
        in urls[1]
    )

    assert (
        "CELEX%3A32024L1233"
        in urls[1]
    )


def test_consolidated_cellar_404_uses_official_eurlex_fallback():
    urls = []

    def fake_urlopen(
        request,
        timeout,
    ):
        urls.append(
            request.full_url
        )

        if (
            "publications.europa.eu"
            in request.full_url
        ):
            raise urllib.error.HTTPError(
                request.full_url,
                404,
                "Not Found",
                hdrs=None,
                fp=io.BytesIO(),
            )

        return FakeResponse(
            body=b"<html>consolidated</html>",
            content_type="text/html",
        )

    transport = EurLexHttpTransport(
        urlopen_fn=fake_urlopen,
        sleep_fn=lambda _: None,
    )

    response = (
        transport.fetch_consolidated_content(
            "02024L1233-20240430"
        )
    )

    assert (
        response.transport
        == "ELI_CONSOLIDATED"
    )

    assert (
        (
            "data.europa.eu/eli/"
            "dir/2024/1233/"
            "2024-04-30/spa/html"
        )
        in urls[-1]
    )


def test_resolve_latest_consolidated_uses_structured_tree_notice():
    raw = b"""<NOTICE>
      <IDENTIFIER>
        <VALUE>32016R0399</VALUE>
      </IDENTIFIER>
      <IDENTIFIER>
        <VALUE>02016R0399-20240710</VALUE>
      </IDENTIFIER>
      <IDENTIFIER>
        <VALUE>02016R0399-20251012</VALUE>
      </IDENTIFIER>
    </NOTICE>"""

    def fake_urlopen(
        request,
        timeout,
    ):
        return FakeResponse(
            body=raw,
        )

    transport = EurLexHttpTransport(
        urlopen_fn=fake_urlopen,
        sleep_fn=lambda _: None,
    )

    selected, metadata = (
        transport.resolve_latest_consolidated(
            "32016R0399"
        )
    )

    assert (
        selected
        == "02016R0399-20251012"
    )

    assert (
        metadata.body
        == raw
    )


def test_resolve_treaty_revision_after_txt_suffix():
    raw = b"""<NOTICE>
      <IDENTIFIER>
        <VALUE>12016M/TXT</VALUE>
      </IDENTIFIER>
      <IDENTIFIER>
        <VALUE>02016M/TXT</VALUE>
      </IDENTIFIER>
      <IDENTIFIER>
        <VALUE>02016M/TXT-20250315</VALUE>
      </IDENTIFIER>
    </NOTICE>"""

    def fake_urlopen(
        request,
        timeout,
    ):
        return FakeResponse(
            body=raw,
        )

    transport = EurLexHttpTransport(
        urlopen_fn=fake_urlopen,
        sleep_fn=lambda _: None,
    )

    selected, _ = (
        transport.resolve_latest_consolidated(
            "12016M/TXT"
        )
    )

    assert (
        selected
        == "02016M/TXT-20250315"
    )


def test_fetch_original_returns_native_payload():
    calls = []

    def fake_urlopen(
        request,
        timeout,
    ):
        calls.append(
            request.get_header(
                "Accept"
            )
        )

        if (
            "notice=tree"
            in request.get_header(
                "Accept"
            )
        ):
            return FakeResponse(
                body=b"<NOTICE />",
            )

        return FakeResponse(
            body=b"<html>original</html>",
            content_type="application/xhtml+xml",
        )

    transport = EurLexHttpTransport(
        urlopen_fn=fake_urlopen,
        sleep_fn=lambda _: None,
    )

    payload = transport.fetch_original(
        "32016R0399"
    )

    assert (
        payload["id"]
        == "32016R0399"
    )

    assert (
        payload["metadata_xml"]
        == b"<NOTICE />"
    )

    assert (
        payload["content_xhtml"]
        == b"<html>original</html>"
    )

    assert (
        payload["content_transport"]
        == "CELLAR_CONTENT"
    )

    assert len(calls) == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "timeout_seconds": 0,
        },
        {
            "attempts": 0,
        },
        {
            "backoff_seconds": -1,
        },
        {
            "user_agent": "",
        },
    ],
)
def test_invalid_transport_configuration_fails_closed(
    kwargs,
):
    with pytest.raises(
        ValueError
    ):
        EurLexHttpTransport(
            **kwargs
        )


def test_builds_dated_eli_for_directive_consolidated():
    transport = EurLexHttpTransport(
        urlopen_fn=lambda *_args, **_kwargs: None,
        sleep_fn=lambda _: None,
    )

    assert (
        transport._eli_consolidated_url(
            "02024L1233-20240430"
        )
        == (
            "https://data.europa.eu/eli/"
            "dir/2024/1233/"
            "2024-04-30/spa/html"
        )
    )


def test_builds_dated_eli_for_regulation_consolidated():
    transport = EurLexHttpTransport(
        urlopen_fn=lambda *_args, **_kwargs: None,
        sleep_fn=lambda _: None,
    )

    assert (
        transport._eli_consolidated_url(
            "02016R0399-20251012"
        )
        == (
            "https://data.europa.eu/eli/"
            "reg/2016/399/"
            "2025-10-12/spa/html"
        )
    )


def test_treaty_consolidated_does_not_invent_act_eli():
    transport = EurLexHttpTransport(
        urlopen_fn=lambda *_args, **_kwargs: None,
        sleep_fn=lambda _: None,
    )

    assert (
        transport._eli_consolidated_url(
            "02016M/TXT-20250315"
        )
        is None
    )


def test_http_202_is_retried_until_final_representation():
    calls = []
    sleeps = []

    def fake_urlopen(
        request,
        timeout,
    ):
        calls.append(
            request.full_url
        )

        if (
            "publications.europa.eu"
            in request.full_url
        ):
            raise urllib.error.HTTPError(
                request.full_url,
                404,
                "Not Found",
                hdrs=None,
                fp=io.BytesIO(),
            )

        eli_calls = [
            url
            for url in calls
            if "data.europa.eu/eli/"
            in url
        ]

        if len(eli_calls) < 3:
            return FakeResponse(
                body=b"processing",
                status=202,
                content_type="text/html",
            )

        return FakeResponse(
            body=b"<html>final consolidated</html>",
            status=200,
            content_type="text/html",
        )

    transport = EurLexHttpTransport(
        attempts=3,
        backoff_seconds=1,
        urlopen_fn=fake_urlopen,
        sleep_fn=sleeps.append,
    )

    response = (
        transport.fetch_consolidated_content(
            "02024L1233-20240430"
        )
    )

    assert response.status == 200

    assert (
        response.transport
        == "ELI_CONSOLIDATED"
    )

    assert (
        response.body
        == b"<html>final consolidated</html>"
    )

    assert sleeps == [
        1.0,
        2.0,
    ]


def test_latest_unavailable_language_revision_falls_back_to_previous_spanish_revision():
    from backend.knowledge.eurlex.transport import (
        EurLexConsolidatedRepresentationUnavailableError,
    )

    metadata = b"""<NOTICE>
        <IDENTIFIER>
            <VALUE>32016R0399</VALUE>
        </IDENTIFIER>
        <IDENTIFIER>
            <VALUE>02016R0399-20240101</VALUE>
        </IDENTIFIER>
        <IDENTIFIER>
            <VALUE>02016R0399-20250101</VALUE>
        </IDENTIFIER>
    </NOTICE>"""

    class LanguageAwareTransport(
        EurLexHttpTransport
    ):
        def fetch_tree_notice(
            self,
            celex,
        ):
            return FakeResponseAdapter(
                body=metadata,
                transport="CELLAR_TREE",
            )

        def fetch_consolidated_content(
            self,
            consolidated_celex,
        ):
            if (
                consolidated_celex
                == "02016R0399-20250101"
            ):
                raise (
                    EurLexConsolidatedRepresentationUnavailableError(
                        "not Spanish"
                    )
                )

            return FakeResponseAdapter(
                body=b"<html>Spanish previous</html>",
                transport="CELLAR_CONSOLIDATED",
            )


    transport = LanguageAwareTransport(
        sleep_fn=lambda _: None,
    )

    payload = transport.fetch_consolidated(
        "32016R0399"
    )

    assert (
        payload["consolidated_celex"]
        == "02016R0399-20240101"
    )

    assert (
        payload["skipped_unavailable_revisions"]
        == (
            "02016R0399-20250101",
        )
    )


def test_all_language_specific_revisions_unavailable_fails_explicitly():
    from backend.knowledge.eurlex.transport import (
        EurLexConsolidatedRepresentationUnavailableError,
    )

    metadata = b"""<NOTICE>
        <IDENTIFIER>
            <VALUE>32024L1233</VALUE>
        </IDENTIFIER>
        <IDENTIFIER>
            <VALUE>02024L1233-20240430</VALUE>
        </IDENTIFIER>
    </NOTICE>"""

    class NoSpanishTransport(
        EurLexHttpTransport
    ):
        def fetch_tree_notice(
            self,
            celex,
        ):
            return FakeResponseAdapter(
                body=metadata,
                transport="CELLAR_TREE",
            )

        def fetch_consolidated_content(
            self,
            consolidated_celex,
        ):
            raise (
                EurLexConsolidatedRepresentationUnavailableError(
                    "not Spanish"
                )
            )


    transport = NoSpanishTransport(
        sleep_fn=lambda _: None,
    )

    with pytest.raises(
        EurLexConsolidatedRepresentationUnavailableError
    ):
        transport.fetch_consolidated(
            "32024L1233"
        )


class FakeResponseAdapter:
    def __init__(
        self,
        *,
        body,
        transport,
    ):
        self.body = body
        self.transport = transport
        self.final_url = (
            "https://example.test/final"
        )
        self.status = 200
        self.content_type = "text/html"
        self.requested_url = (
            "https://example.test/requested"
        )
