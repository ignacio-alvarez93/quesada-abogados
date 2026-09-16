from dataclasses import dataclass

import pytest

from backend.knowledge.eurlex.authoritative_archive import (
    build_authoritative_eurlex_article_archive,
    validate_eurlex_catalogue_append_only,
)
from backend.knowledge.eurlex.transport import (
    EurLexConsolidatedRepresentationUnavailableError,
)


ORIGINAL = "32016R0399"

R2016 = "02016R0399-20161006"
R2017 = "02016R0399-20170407"
R2024 = "02016R0399-20240710"


@dataclass
class _Response:
    body: bytes


def _tree_notice(
    *identifiers,
):
    values = "".join(
        (
            "<IDENTIFIER>"
            f"<VALUE>{identifier}</VALUE>"
            "</IDENTIFIER>"
        )
        for identifier
        in identifiers
    )

    return (
        "<NOTICE>"
        f"{values}"
        "</NOTICE>"
    ).encode(
        "utf-8"
    )


def _article(
    text,
):
    return f"""
    <html>
      <body>
        <p class="title-article-norm">
          Artículo 1
        </p>
        <p class="norm">
          {text}
        </p>
      </body>
    </html>
    """.encode(
        "utf-8"
    )


class _Transport:
    def __init__(
        self,
        *,
        unavailable=(),
    ):
        self.unavailable = set(
            unavailable
        )

        self.content_calls = []

        # Deliberadamente desordenado.
        self.notice = _tree_notice(
            R2024,
            ORIGINAL,
            R2016,
            R2017,
        )

        self.bodies = {
            R2016: _article(
                "Estado A."
            ),
            R2017: _article(
                "Estado A."
            ),
            R2024: _article(
                "Estado B."
            ),
        }

    def fetch_tree_notice(
        self,
        celex,
    ):
        assert celex == ORIGINAL

        return _Response(
            body=self.notice
        )

    def fetch_consolidated_content(
        self,
        revision,
    ):
        self.content_calls.append(
            revision
        )

        if revision in self.unavailable:
            raise (
                EurLexConsolidatedRepresentationUnavailableError(
                    "representación española no disponible"
                )
            )

        return _Response(
            body=self.bodies[
                revision
            ]
        )


def test_authoritative_archive_fetches_complete_catalogue_chronologically():
    transport = _Transport()

    archive = (
        build_authoritative_eurlex_article_archive(
            original_celex=ORIGINAL,
            transport=transport,
        )
    )

    assert (
        archive.catalogue_revisions
        == (
            R2016,
            R2017,
            R2024,
        )
    )

    assert (
        transport.content_calls
        == [
            R2016,
            R2017,
            R2024,
        ]
    )

    assert (
        archive.history.revisions
        == archive.catalogue_revisions
    )

    assert (
        archive.oldest_revision
        == R2016
    )

    assert (
        archive.latest_revision
        == R2024
    )

    assert len(
        archive.catalogue_sha256
    ) == 64

    versions = (
        archive.history.document.versions_for_block(
            "article:1"
        )
    )

    # 2016 y 2017 forman el mismo episodio A.
    # 2024 inicia B.
    assert len(
        versions
    ) == 2

    assert (
        versions[
            0
        ].effective_from.isoformat()
        == "2016-10-06"
    )

    assert (
        versions[
            1
        ].effective_from.isoformat()
        == "2024-07-10"
    )


def test_authoritative_archive_fails_closed_if_catalogued_revision_is_unavailable():
    transport = _Transport(
        unavailable=(
            R2017,
        )
    )

    with pytest.raises(
        EurLexConsolidatedRepresentationUnavailableError
    ):
        build_authoritative_eurlex_article_archive(
            original_celex=ORIGINAL,
            transport=transport,
        )

    assert (
        transport.content_calls
        == [
            R2016,
            R2017,
        ]
    )


def test_catalogue_governance_allows_forward_append():
    result = (
        validate_eurlex_catalogue_append_only(
            (
                R2016,
                R2017,
            ),
            (
                R2016,
                R2017,
                R2024,
            ),
        )
    )

    assert result == (
        R2016,
        R2017,
        R2024,
    )


def test_catalogue_governance_rejects_historical_backfill():
    with pytest.raises(
        ValueError,
        match="backfill",
    ):
        validate_eurlex_catalogue_append_only(
            (
                R2017,
                R2024,
            ),
            (
                R2016,
                R2017,
                R2024,
            ),
        )


def test_catalogue_governance_rejects_historical_removal():
    with pytest.raises(
        ValueError,
        match="perdió revisiones",
    ):
        validate_eurlex_catalogue_append_only(
            (
                R2016,
                R2017,
                R2024,
            ),
            (
                R2016,
                R2017,
            ),
        )
