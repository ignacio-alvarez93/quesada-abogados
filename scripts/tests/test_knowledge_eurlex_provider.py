import json

import pytest

from backend.knowledge import (
    KnowledgeItemKind,
    KnowledgeProvider,
    validate_discovery_batch,
    validate_transformed_item,
)
from backend.knowledge.eurlex import (
    EurLexConsolidatedProvider,
    EurLexProvider,
    parse_eurlex_document_text,
    parse_tree_notice_primary_metadata,
)


TARGET = "32016R0399"

CONSOLIDATED = (
    "02016R0399-20251012"
)


METADATA_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<NOTICE>
  <WORK>
    <IDENTIFIER>
      <VALUE>32016R0399</VALUE>
    </IDENTIFIER>

    <WORK_DATE_DOCUMENT>
      <VALUE>2016-03-09</VALUE>
    </WORK_DATE_DOCUMENT>

    <SAMEAS>
      <URI>
        http://data.europa.eu/eli/reg/2016/399/oj
      </URI>
    </SAMEAS>

    <EXPRESSION>
      <EXPRESSION_TITLE>
        <VALUE>
          Reglamento (UE) 2016/399 del Parlamento Europeo y del Consejo
        </VALUE>
      </EXPRESSION_TITLE>
    </EXPRESSION>

    <EMBEDDED_NOTICE>
      <WORK>
        <IDENTIFIER>
          <VALUE>32024R9999</VALUE>
        </IDENTIFIER>
        <EXPRESSION_TITLE>
          <VALUE>
            Titulo de una norma relacionada que no debe usarse
          </VALUE>
        </EXPRESSION_TITLE>
      </WORK>
    </EMBEDDED_NOTICE>

    <IDENTIFIER>
      <VALUE>02016R0399-20251012</VALUE>
    </IDENTIFIER>
  </WORK>
</NOTICE>
"""


ORIGINAL_XHTML = b"""<!doctype html>
<html>
<head>
  <title>document.xml</title>
  <style>.x { display:none; }</style>
</head>
<body>
  <h1>Reglamento (UE) 2016/399</h1>
  <p>Articulo 1. Objeto y principios.</p>
  <p>Texto original oficial.</p>
  <script>window.bad = "ignore me";</script>
</body>
</html>
"""


CONSOLIDATED_XHTML = b"""<!doctype html>
<html>
<body>
  <h1>Reglamento (UE) 2016/399</h1>
  <p>Articulo 1. Texto consolidado vigente en espanol.</p>
  <p>Articulo 2. Disposiciones actualizadas.</p>
</body>
</html>
"""


class FakeTransport:
    def fetch_original(
        self,
        original_celex,
    ):
        assert (
            original_celex
            == TARGET
        )

        return {
            "id": TARGET,
            "metadata_xml": (
                METADATA_XML
            ),
            "metadata_final_url": (
                "https://example.test/"
                "metadata"
            ),
            "content_xhtml": (
                ORIGINAL_XHTML
            ),
            "content_final_url": (
                "https://example.test/"
                "original"
            ),
            "content_transport": (
                "CELLAR_CONTENT"
            ),
        }

    def fetch_consolidated(
        self,
        original_celex,
    ):
        assert (
            original_celex
            == TARGET
        )

        return {
            "id": TARGET,
            "consolidated_celex": (
                CONSOLIDATED
            ),
            "metadata_xml": (
                METADATA_XML
            ),
            "metadata_final_url": (
                "https://example.test/"
                "metadata"
            ),
            "content_xhtml": (
                CONSOLIDATED_XHTML
            ),
            "content_final_url": (
                "https://example.test/"
                "consolidated"
            ),
            "content_transport": (
                "CELLAR_CONSOLIDATED"
            ),
            "skipped_unavailable_revisions": (),
        }


def test_primary_metadata_ignores_embedded_related_title():
    metadata = (
        parse_tree_notice_primary_metadata(
            METADATA_XML,
            external_id=TARGET,
        )
    )

    assert (
        metadata["title"]
        == (
            "Reglamento (UE) 2016/399 "
            "del Parlamento Europeo y del Consejo"
        )
    )

    assert (
        metadata["published_on"].isoformat()
        == "2016-03-09"
    )

    assert (
        metadata["original_eli"]
        == (
            "http://data.europa.eu/"
            "eli/reg/2016/399/oj"
        )
    )


def test_xhtml_extracts_visible_text_only():
    content = (
        parse_eurlex_document_text(
            ORIGINAL_XHTML
        )
    )

    assert (
        "Articulo 1"
        in content
    )

    assert (
        "Texto original oficial"
        in content
    )

    assert (
        "window.bad"
        not in content
    )

    assert (
        "display:none"
        not in content
    )


def test_original_provider_satisfies_generic_contract():
    provider = EurLexProvider(
        FakeTransport()
    )

    assert isinstance(
        provider,
        KnowledgeProvider,
    )

    assert (
        provider.source_key
        == "EUR_LEX"
    )


def test_original_provider_discovery_is_governed_by_explicit_celex():
    provider = EurLexProvider(
        FakeTransport()
    )

    batch = provider.discover(
        cursor=TARGET
    )

    validate_discovery_batch(
        provider,
        batch,
    )

    assert (
        len(
            batch.items
        )
        == 1
    )

    assert (
        batch.items[
            0
        ].canonical_key
        == (
            "EUR_LEX:"
            + TARGET
        )
    )


def test_original_provider_builds_legislation_item():
    provider = EurLexProvider(
        FakeTransport()
    )

    reference = (
        provider.discover(
            cursor=TARGET
        ).items[0]
    )

    item = (
        provider.to_knowledge_item(
            reference,
            provider.fetch(
                reference
            ),
        )
    )

    validate_transformed_item(
        provider,
        reference,
        item,
    )

    assert (
        item.source_key
        == "EUR_LEX"
    )

    assert (
        item.external_id
        == TARGET
    )

    assert (
        item.item_kind
        is KnowledgeItemKind.LEGISLATION
    )

    assert (
        item.source_revision
        == TARGET
    )

    assert (
        item.language
        == "es"
    )

    assert (
        item.published_on.isoformat()
        == "2016-03-09"
    )

    assert (
        item.canonical_uri
        == (
            "http://data.europa.eu/"
            "eli/reg/2016/399/oj"
        )
    )

    assert (
        "Texto original oficial"
        in item.content_text
    )

    metadata = dict(
        item.metadata
    )

    assert (
        metadata[
            "content_transport"
        ]
        == "CELLAR_CONTENT"
    )


def test_consolidated_provider_builds_separate_identity():
    provider = (
        EurLexConsolidatedProvider(
            FakeTransport()
        )
    )

    reference = (
        provider.discover(
            cursor=TARGET
        ).items[0]
    )

    item = (
        provider.to_knowledge_item(
            reference,
            provider.fetch(
                reference
            ),
        )
    )

    validate_transformed_item(
        provider,
        reference,
        item,
    )

    assert (
        item.source_key
        == "EUR_LEX_CONSOLIDATED"
    )

    assert (
        item.external_id
        == TARGET
    )

    assert (
        item.source_revision
        == CONSOLIDATED
    )

    assert (
        item.canonical_uri
        == (
            "http://data.europa.eu/"
            "eli/reg/2016/399/"
            "2025-10-12"
        )
    )

    assert (
        "Texto consolidado vigente"
        in item.content_text
    )

    metadata = dict(
        item.metadata
    )

    assert (
        metadata[
            "consolidated_celex"
        ]
        == CONSOLIDATED
    )

    assert (
        json.loads(
            metadata[
                "skipped_unavailable_revisions_json"
            ]
        )
        == []
    )


@pytest.mark.parametrize(
    "provider_class",
    [
        EurLexProvider,
        EurLexConsolidatedProvider,
    ],
)
def test_discovery_rejects_missing_celex(
    provider_class,
):
    provider = provider_class(
        FakeTransport()
    )

    with pytest.raises(
        ValueError
    ):
        provider.discover()


@pytest.mark.parametrize(
    "provider_class",
    [
        EurLexProvider,
        EurLexConsolidatedProvider,
    ],
)
def test_discovery_rejects_sector_zero_as_input(
    provider_class,
):
    provider = provider_class(
        FakeTransport()
    )

    with pytest.raises(
        ValueError
    ):
        provider.discover(
            cursor=CONSOLIDATED
        )
