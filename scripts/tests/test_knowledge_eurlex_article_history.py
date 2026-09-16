from backend.knowledge.eurlex import (
    build_eurlex_article_history,
    parse_eurlex_article_snapshot,
)


def _snapshot(
    *,
    revision,
    body,
):
    return parse_eurlex_article_snapshot(
        body.encode(
            "utf-8"
        ),
        original_celex="32016R0399",
        consolidated_celex=revision,
    )


def test_history_collapses_whitespace_only_renderer_change():
    legacy = _snapshot(
        revision="02016R0399-20161006",
        body="""
        <html><body>
          <p class="title-article-norm">
            Artículo 1
          </p>
          <p class="stitle-article-norm">
            Objeto
          </p>
          <p class="norm">
            Texto jurídicamente estable.
          </p>
        </body></html>
        """,
    )

    eli = _snapshot(
        revision="02016R0399-20240710",
        body="""
        <html><body>
          <div class="eli-subdivision" id="art_1">
            <p class="title-article-norm">
              Artículo 1
            </p>
            <div class="eli-title" id="art_1.tit_1">
              <p class="stitle-article-norm">
                Objeto
              </p>
            </div>
            <p class="norm">
                Texto jurídicamente estable.
            </p>
          </div>
        </body></html>
        """,
    )

    history = build_eurlex_article_history(
        (
            eli,
            legacy,
        )
    )

    assert history.block_count == 1
    assert history.version_count == 1

    version = (
        history.document.versions_for_block(
            "article:1"
        )[0]
    )

    assert (
        version.effective_from.isoformat()
        == "2016-10-06"
    )

    metadata = dict(
        version.metadata
    )

    assert (
        metadata[
            "eurlex_first_revision"
        ]
        == "02016R0399-20161006"
    )

    assert (
        metadata[
            "eurlex_last_revision"
        ]
        == "02016R0399-20240710"
    )


def test_history_creates_new_version_for_substantive_change():
    before = _snapshot(
        revision="02016R0399-20161006",
        body="""
        <html><body>
          <p class="title-article-norm">
            Artículo 8
          </p>
          <p class="norm">
            Duración máxima 90 días.
          </p>
        </body></html>
        """,
    )

    after = _snapshot(
        revision="02016R0399-20170407",
        body="""
        <html><body>
          <p class="title-article-norm">
            Artículo 8
          </p>
          <p class="norm">
            Duración máxima 180 días.
          </p>
        </body></html>
        """,
    )

    history = build_eurlex_article_history(
        (
            before,
            after,
        )
    )

    versions = (
        history.document.versions_for_block(
            "article:8"
        )
    )

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
        == "2017-04-07"
    )

    assert versions[
        0
    ].is_current is False

    assert versions[
        1
    ].is_current is True


def test_history_allows_article_added_later():
    before = _snapshot(
        revision="02016R0399-20161006",
        body="""
        <html><body>
          <p class="title-article-norm">
            Artículo 6
          </p>
          <p class="norm">
            Artículo original.
          </p>
        </body></html>
        """,
    )

    after = _snapshot(
        revision="02016R0399-20240710",
        body="""
        <html><body>
          <div class="eli-subdivision" id="art_6">
            <p class="title-article-norm">
              Artículo 6
            </p>
            <p class="norm">
              Artículo original.
            </p>
          </div>

          <div class="eli-subdivision" id="art_6a">
            <p class="title-article-norm">
              Artículo 6 bis
            </p>
            <p class="norm">
              Artículo nuevo.
            </p>
          </div>
        </body></html>
        """,
    )

    history = build_eurlex_article_history(
        (
            before,
            after,
        )
    )

    versions = (
        history.document.versions_for_block(
            "article:6bis"
        )
    )

    assert len(
        versions
    ) == 1

    assert (
        versions[
            0
        ].effective_from.isoformat()
        == "2024-07-10"
    )

    assert versions[
        0
    ].is_current is True


def test_history_fails_closed_when_article_disappears():
    before = _snapshot(
        revision="02016R0399-20161006",
        body="""
        <html><body>
          <p class="title-article-norm">
            Artículo 1
          </p>
          <p class="norm">
            Uno.
          </p>

          <p class="title-article-norm">
            Artículo 2
          </p>
          <p class="norm">
            Dos.
          </p>
        </body></html>
        """,
    )

    after = _snapshot(
        revision="02016R0399-20170407",
        body="""
        <html><body>
          <p class="title-article-norm">
            Artículo 1
          </p>
          <p class="norm">
            Uno.
          </p>
        </body></html>
        """,
    )

    try:
        build_eurlex_article_history(
            (
                before,
                after,
            )
        )
    except ValueError as exc:
        assert (
            "effective_to"
            in str(
                exc
            )
        )
    else:
        raise AssertionError(
            "Debía fallar ante artículo desaparecido"
        )


def test_history_rejects_mixed_original_celex():
    first = _snapshot(
        revision="02016R0399-20161006",
        body="""
        <html><body>
          <p class="title-article-norm">
            Artículo 1
          </p>
          <p class="norm">
            Uno.
          </p>
        </body></html>
        """,
    )

    second = (
        parse_eurlex_article_snapshot(
            b"""
            <html><body>
              <p class="title-article-norm">
                Articulo 1
              </p>
              <p class="norm">
                Uno.
              </p>
            </body></html>
            """,
            original_celex="32021L1883",
            consolidated_celex=(
                "02021L1883-20211028"
            ),
        )
    )

    try:
        build_eurlex_article_history(
            (
                first,
                second,
            )
        )
    except ValueError as exc:
        assert (
            "normas originales distintas"
            in str(
                exc
            )
        )
    else:
        raise AssertionError(
            "Debía rechazar CELEX originales distintos"
        )
