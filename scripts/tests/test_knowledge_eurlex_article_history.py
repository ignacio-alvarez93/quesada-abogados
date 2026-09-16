from datetime import date

from backend.knowledge import (
    KnowledgeTemporalBlockChangeKind,
    KnowledgeTemporalDiffStatus,
    KnowledgeTemporalResolutionStatus,
    compare_document_at_dates,
    resolve_block_version_at,
)

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


def test_eurlex_history_resolves_with_generic_temporal_engine():
    first = _snapshot(
        revision="02016R0399-20161006",
        body="""
        <html><body>
          <p class="title-article-norm">
            Artículo 8
          </p>
          <p class="norm">
            Versión inicial.
          </p>
        </body></html>
        """,
    )

    second = _snapshot(
        revision="02016R0399-20170407",
        body="""
        <html><body>
          <p class="title-article-norm">
            Artículo 8
          </p>
          <p class="norm">
            Versión modificada.
          </p>
        </body></html>
        """,
    )

    history = build_eurlex_article_history(
        (
            second,
            first,
        )
    )

    before_first = resolve_block_version_at(
        history.document,
        "article:8",
        date(
            2016,
            10,
            5,
        ),
    )

    first_day = resolve_block_version_at(
        history.document,
        "article:8",
        date(
            2016,
            10,
            6,
        ),
    )

    before_change = resolve_block_version_at(
        history.document,
        "article:8",
        date(
            2017,
            4,
            6,
        ),
    )

    change_day = resolve_block_version_at(
        history.document,
        "article:8",
        date(
            2017,
            4,
            7,
        ),
    )

    future = resolve_block_version_at(
        history.document,
        "article:8",
        date(
            2030,
            1,
            1,
        ),
    )

    assert (
        before_first.status
        is KnowledgeTemporalResolutionStatus.BEFORE_FIRST_EFFECTIVE
    )

    assert before_first.version is None

    assert (
        first_day.status
        is KnowledgeTemporalResolutionStatus.RESOLVED
    )

    assert (
        first_day.version
        is not None
    )

    assert (
        first_day.version.version_position
        == 1
    )

    assert (
        before_change.version
        is not None
    )

    assert (
        before_change.version.version_key
        == first_day.version.version_key
    )

    assert (
        change_day.version
        is not None
    )

    assert (
        change_day.version.version_position
        == 2
    )

    assert (
        change_day.version.version_key
        != first_day.version.version_key
    )

    assert (
        future.version
        is not None
    )

    assert (
        future.version.version_key
        == change_day.version.version_key
    )


def test_eurlex_temporal_engine_respects_article_creation_date():
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
              Artículo añadido.
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

    before_creation = resolve_block_version_at(
        history.document,
        "article:6bis",
        date(
            2020,
            1,
            1,
        ),
    )

    creation_day = resolve_block_version_at(
        history.document,
        "article:6bis",
        date(
            2024,
            7,
            10,
        ),
    )

    unknown = resolve_block_version_at(
        history.document,
        "article:999",
        date(
            2024,
            7,
            10,
        ),
    )

    assert (
        before_creation.status
        is KnowledgeTemporalResolutionStatus.BEFORE_FIRST_EFFECTIVE
    )

    assert before_creation.version is None

    assert (
        creation_day.status
        is KnowledgeTemporalResolutionStatus.RESOLVED
    )

    assert (
        creation_day.version
        is not None
    )

    assert (
        creation_day.version.effective_from
        == date(
            2024,
            7,
            10,
        )
    )

    assert (
        unknown.status
        is KnowledgeTemporalResolutionStatus.BLOCK_NOT_FOUND
    )

    assert unknown.version is None


def test_eurlex_history_diff_classifies_added_modified_and_unchanged():
    legacy = _snapshot(
        revision="02016R0399-20170407",
        body="""
        <html><body>
          <p class="title-article-norm">
            Artículo 1
          </p>
          <p class="norm">
            Texto estable.
          </p>

          <p class="title-article-norm">
            Artículo 2
          </p>
          <p class="norm">
            Texto anterior.
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
            <p class="norm">
                 Texto estable.
            </p>
          </div>

          <div class="eli-subdivision" id="art_2">
            <p class="title-article-norm">
              Artículo 2
            </p>
            <p class="norm">
              Texto modificado.
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
            legacy,
            eli,
        )
    )

    diff = compare_document_at_dates(
        history.document,
        date(
            2017,
            4,
            7,
        ),
        date(
            2024,
            7,
            10,
        ),
    )

    assert (
        diff.status
        is KnowledgeTemporalDiffStatus.RESOLVED
    )

    assert diff.added_count == 1
    assert diff.removed_count == 0
    assert diff.modified_count == 1
    assert diff.unchanged_count == 1

    changes = {
        change.block_id:
            change
        for change
        in diff.changes
    }

    assert (
        changes[
            "article:6bis"
        ].kind
        is KnowledgeTemporalBlockChangeKind.ADDED
    )

    assert (
        changes[
            "article:2"
        ].kind
        is KnowledgeTemporalBlockChangeKind.MODIFIED
    )

    # Mismo contenido jurídico, aunque cambia LEGACY -> ELI
    # y el whitespace del XHTML.
    assert (
        "article:1"
        not in changes
    )


def test_eurlex_history_diff_respects_effective_date_boundary():
    before = _snapshot(
        revision="02016R0399-20170407",
        body="""
        <html><body>
          <p class="title-article-norm">
            Artículo 1
          </p>
          <p class="norm">
            Texto estable.
          </p>
        </body></html>
        """,
    )

    after = _snapshot(
        revision="02016R0399-20240710",
        body="""
        <html><body>
          <div class="eli-subdivision" id="art_1">
            <p class="title-article-norm">
              Artículo 1
            </p>
            <p class="norm">
              Texto estable.
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

    before_effective = compare_document_at_dates(
        history.document,
        date(
            2017,
            4,
            7,
        ),
        date(
            2024,
            7,
            9,
        ),
    )

    on_effective = compare_document_at_dates(
        history.document,
        date(
            2017,
            4,
            7,
        ),
        date(
            2024,
            7,
            10,
        ),
    )

    assert (
        before_effective.status
        is KnowledgeTemporalDiffStatus.RESOLVED
    )

    assert before_effective.added_count == 0
    assert before_effective.modified_count == 0
    assert before_effective.removed_count == 0
    assert before_effective.unchanged_count == 1

    assert (
        on_effective.status
        is KnowledgeTemporalDiffStatus.RESOLVED
    )

    assert on_effective.added_count == 1
    assert on_effective.modified_count == 0
    assert on_effective.removed_count == 0
    assert on_effective.unchanged_count == 1

    assert (
        on_effective.changes[
            0
        ].block_id
        == "article:6bis"
    )

    assert (
        on_effective.changes[
            0
        ].kind
        is KnowledgeTemporalBlockChangeKind.ADDED
    )



def test_history_collapses_editorial_only_change_and_stores_legal_content():
    from backend.knowledge.eurlex import (
        normalize_eurlex_article_legal_semantic_text,
    )
    from backend.knowledge.legal_structure import (
        compute_block_version_key,
    )

    before = _snapshot(
        revision="02016R0399-20240710",
        body="""
        <html><body>
          <div class="eli-subdivision" id="art_5">
            <p class="title-article-norm">
              Artículo 5
            </p>

            <p class="modref">
              ▼M6
            </p>

            <p class="norm">
              Texto jurídicamente estable.
            </p>

            <p class="modref">
              ▼B
            </p>
          </div>
        </body></html>
        """,
    )

    after = _snapshot(
        revision="02016R0399-20251012",
        body="""
        <html><body>
          <div class="eli-subdivision" id="art_5">
            <p class="title-article-norm">
              Artículo 5
            </p>

            <p class="modref">
              ▼M7
            </p>

            <p class="norm">
              Texto jurídicamente estable.
            </p>

            <p class="modref">
              ▼B
            </p>
          </div>
        </body></html>
        """,
    )

    before_article = before.get(
        "article:5"
    )

    after_article = after.get(
        "article:5"
    )

    assert before_article is not None
    assert after_article is not None

    # La evidencia documental sí cambia.
    assert (
        before_article.content_text
        !=
        after_article.content_text
    )

    history = build_eurlex_article_history(
        (
            before,
            after,
        )
    )

    versions = (
        history.document.versions_for_block(
            "article:5"
        )
    )

    # Jurídicamente es una sola versión.
    assert len(
        versions
    ) == 1

    version = versions[
        0
    ]

    assert (
        version.effective_from.isoformat()
        == "2024-07-10"
    )

    assert version.is_current is True

    # KnowledgeBlockVersion contiene el texto jurídico canónico,
    # no la última evidence editorial del renderer.
    assert (
        version.content_text
        ==
        normalize_eurlex_article_legal_semantic_text(
            after_article.content_text
        )
    )

    assert "▼M6" not in version.content_text
    assert "▼M7" not in version.content_text
    assert "▼B" not in version.content_text

    # La identidad genérica vuelve a ser recomputable desde
    # los propios campos almacenados de KnowledgeBlockVersion.
    recomputed = compute_block_version_key(
        source_key=version.source_key,
        external_id=version.external_id,
        block_id=version.block_id,
        modifier_external_id=(
            version.modifier_external_id
        ),
        published_on=version.published_on,
        effective_from=version.effective_from,
        content_text=version.content_text,
    )

    assert (
        recomputed
        ==
        version.version_key
    )

    metadata = dict(
        version.metadata
    )

    assert (
        metadata[
            "eurlex_first_revision"
        ]
        == "02016R0399-20240710"
    )

    assert (
        metadata[
            "eurlex_last_revision"
        ]
        == "02016R0399-20251012"
    )
