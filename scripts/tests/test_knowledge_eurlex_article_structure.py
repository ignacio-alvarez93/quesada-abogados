from datetime import date

import pytest

from backend.knowledge.eurlex import (
    build_eurlex_article_block_id,
    compute_eurlex_article_semantic_sha256,
    normalize_eurlex_article_identifier,
    normalize_eurlex_article_semantic_text,
    parse_eurlex_article_snapshot,
)


def test_normalizes_plain_article():
    assert (
        normalize_eurlex_article_identifier(
            "Artículo 21"
        )
        == "21"
    )

    assert (
        build_eurlex_article_block_id(
            "Artículo 21"
        )
        == "article:21"
    )


@pytest.mark.parametrize(
    (
        "heading",
        "expected",
    ),
    (
        (
            "Artículo 6 bis",
            "6bis",
        ),
        (
            "Artículo 8 ter",
            "8ter",
        ),
        (
            "Artículo 10 quater",
            "10quater",
        ),
        (
            "Artículo 12a",
            "12a",
        ),
    ),
)
def test_normalizes_inserted_articles(
    heading,
    expected,
):
    assert (
        normalize_eurlex_article_identifier(
            heading
        )
        == expected
    )


def test_legacy_renderer_ignores_correspondence_table():
    raw = b"""
    <html>
      <body>
        <p class="title-article-norm">
          Art\xc3\xadculo 1
        </p>
        <p class="stitle-article-norm">
          Objeto
        </p>
        <p class="norm">
          Texto uno.
        </p>

        <p class="title-article-norm">
          Art\xc3\xadculo 2
        </p>
        <p class="stitle-article-norm">
          Definiciones
        </p>
        <p class="norm">
          Texto dos.
        </p>

        <hr class="separator-annex"/>

        <table>
          <tr>
            <td>
              <p class="tbl-norm">
                Art\xc3\xadculo 1
              </p>
            </td>
          </tr>
        </table>
      </body>
    </html>
    """

    snapshot = (
        parse_eurlex_article_snapshot(
            raw,
            original_celex="32016R0399",
            consolidated_celex=(
                "02016R0399-20161006"
            ),
        )
    )

    assert (
        snapshot.original_celex
        == "32016R0399"
    )

    assert (
        snapshot.effective_from
        == date(
            2016,
            10,
            6,
        )
    )

    assert tuple(
        article.block_id
        for article
        in snapshot.articles
    ) == (
        "article:1",
        "article:2",
    )

    assert all(
        article.renderer
        == "LEGACY"
        for article
        in snapshot.articles
    )

    assert (
        snapshot.articles[0].title
        == "Objeto"
    )

    assert (
        "Texto uno."
        in snapshot.articles[
            0
        ].content_text
    )


def test_modern_renderer_uses_semantic_identity_not_native_id():
    raw = b"""
    <html>
      <body>
        <div
          class="eli-subdivision"
          id="art_6a"
        >
          <p
            class="title-article-norm"
            id="id-random-heading"
          >
            Art\xc3\xadculo 6 bis
          </p>
          <div
            class="eli-title"
            id="art_6a.tit_1"
          >
            <p class="stitle-article-norm">
              Control especial
            </p>
          </div>
          <p class="norm">
            Texto nuevo.
          </p>
        </div>
      </body>
    </html>
    """

    snapshot = (
        parse_eurlex_article_snapshot(
            raw,
            original_celex="32016R0399",
            consolidated_celex=(
                "02016R0399-20240710"
            ),
        )
    )

    article = snapshot.articles[
        0
    ]

    assert (
        article.block_id
        == "article:6bis"
    )

    assert (
        article.legal_identifier
        == "6bis"
    )

    assert (
        article.native_structural_id
        == "art_6a"
    )

    assert (
        article.heading_source_id
        == "id-random-heading"
    )

    assert (
        article.renderer
        == "ELI"
    )

    assert (
        article.title
        == "Control especial"
    )


def test_duplicate_semantic_article_fails_closed():
    raw = b"""
    <html>
      <body>
        <p class="title-article-norm">
          Art\xc3\xadculo 1
        </p>
        <p class="norm">
          Primero.
        </p>

        <p class="title-article-norm">
          Art\xc3\xadculo 1
        </p>
        <p class="norm">
          Duplicado.
        </p>
      </body>
    </html>
    """

    with pytest.raises(
        ValueError,
        match="duplicado",
    ):
        parse_eurlex_article_snapshot(
            raw,
            original_celex="32016R0399",
            consolidated_celex=(
                "02016R0399-20161006"
            ),
        )

def test_semantic_fingerprint_ignores_renderer_whitespace_only():
    legacy = (
        "Artículo 3\n"
        "Definiciones\n\n"
        "1. A efectos del presente Reglamento,\n"
        "se entenderá por frontera exterior."
    )

    eli = (
        "  Artículo 3   "
        "Definiciones "
        "1. A efectos del presente Reglamento, "
        "se entenderá por frontera exterior.  "
    )

    assert (
        normalize_eurlex_article_semantic_text(
            legacy
        )
        == normalize_eurlex_article_semantic_text(
            eli
        )
    )

    assert (
        compute_eurlex_article_semantic_sha256(
            legacy
        )
        == compute_eurlex_article_semantic_sha256(
            eli
        )
    )


def test_semantic_fingerprint_detects_substantive_change():
    before = (
        "Artículo 8 "
        "La duración máxima será de 90 días."
    )

    after = (
        "Artículo 8 "
        "La duración máxima será de 180 días."
    )

    assert (
        compute_eurlex_article_semantic_sha256(
            before
        )
        != compute_eurlex_article_semantic_sha256(
            after
        )
    )


def test_legacy_renderer_stops_article_before_structural_division():
    raw = b"""
    <html>
      <body>
        <p class="title-article-norm">
          Art\xc3\xadculo 4
        </p>
        <p class="norm">
          Texto del art\xc3\xadculo cuatro.
        </p>

        <p
          class="title-division-1"
          id="division-random"
        >
          T\xc3\x8dTULO II
        </p>

        <p class="stitle-division-1">
          FRONTERAS EXTERIORES
        </p>

        <p class="title-division-1">
          CAP\xc3\x8dTULO I
        </p>

        <p class="stitle-division-1">
          Cruce de las fronteras exteriores
        </p>

        <p class="title-article-norm">
          Art\xc3\xadculo 5
        </p>
        <p class="norm">
          Texto del art\xc3\xadculo cinco.
        </p>
      </body>
    </html>
    """

    snapshot = parse_eurlex_article_snapshot(
        raw,
        original_celex="32016R0399",
        consolidated_celex=(
            "02016R0399-20170407"
        ),
    )

    assert tuple(
        article.block_id
        for article
        in snapshot.articles
    ) == (
        "article:4",
        "article:5",
    )

    article_4 = snapshot.get(
        "article:4"
    )

    article_5 = snapshot.get(
        "article:5"
    )

    assert article_4 is not None
    assert article_5 is not None

    assert (
        "Texto del artículo cuatro."
        in article_4.content_text
    )

    assert (
        "TÍTULO II"
        not in article_4.content_text
    )

    assert (
        "FRONTERAS EXTERIORES"
        not in article_4.content_text
    )

    assert (
        "CAPÍTULO I"
        not in article_4.content_text
    )

    assert (
        "Cruce de las fronteras exteriores"
        not in article_4.content_text
    )

    assert (
        article_4.content_text
        == (
            "Artículo 4\n"
            "Texto del artículo cuatro."
        )
    )

    assert (
        article_5.content_text
        == (
            "Artículo 5\n"
            "Texto del artículo cinco."
        )
    )



def test_legacy_renderer_stops_article_before_regulation_final_formula():
    legacy = parse_eurlex_article_snapshot(
        b"""
        <html>
          <body>
            <p class="title-article-norm">
              Art\xc3\xadculo 45
            </p>
            <p class="stitle-article-norm">
              Entrada en vigor
            </p>
            <p class="norm">
              El presente Reglamento entrar\xc3\xa1 en vigor
              a los veinte d\xc3\xadas de su publicaci\xc3\xb3n
              en el Diario Oficial de la Uni\xc3\xb3n Europea.
            </p>
            <p class="norm">
              El presente Reglamento ser\xc3\xa1 obligatorio
              en todos sus elementos y directamente aplicable
              en los Estados miembros de conformidad con los Tratados.
            </p>
            <hr class="separator-annex"/>
            <p class="title-annex-1">
              ANEXO I
            </p>
          </body>
        </html>
        """,
        original_celex="32016R0399",
        consolidated_celex="02016R0399-20170407",
    )

    eli = parse_eurlex_article_snapshot(
        b"""
        <html>
          <body>
            <div class="eli-subdivision" id="art_45">
              <p class="title-article-norm">
                Art\xc3\xadculo 45
              </p>
              <div class="eli-title" id="art_45.tit_1">
                <p class="stitle-article-norm">
                  Entrada en vigor
                </p>
              </div>
              <p class="norm">
                El presente Reglamento entrar\xc3\xa1 en vigor
                a los veinte d\xc3\xadas de su publicaci\xc3\xb3n
                en el Diario Oficial de la Uni\xc3\xb3n Europea.
              </p>
            </div>

            <div class="eli-subdivision" id="fnp_1">
              <p class="norm">
                El presente Reglamento ser\xc3\xa1 obligatorio
                en todos sus elementos y directamente aplicable
                en los Estados miembros de conformidad con los Tratados.
              </p>
            </div>

            <div id="anx_I">
              <p class="title-annex-1">
                ANEXO I
              </p>
            </div>
          </body>
        </html>
        """,
        original_celex="32016R0399",
        consolidated_celex="02016R0399-20240710",
    )

    legacy_article = legacy.get(
        "article:45"
    )

    eli_article = eli.get(
        "article:45"
    )

    assert legacy_article is not None
    assert eli_article is not None

    final_formula = (
        "El presente Reglamento será obligatorio "
        "en todos sus elementos"
    )

    assert (
        final_formula
        not in legacy_article.content_text
    )

    assert (
        final_formula
        not in eli_article.content_text
    )

    assert (
        normalize_eurlex_article_semantic_text(
            legacy_article.content_text
        )
        ==
        normalize_eurlex_article_semantic_text(
            eli_article.content_text
        )
    )

    assert (
        "Entrada en vigor"
        in legacy_article.content_text
    )

    assert (
        "Entrada en vigor"
        in eli_article.content_text
    )
