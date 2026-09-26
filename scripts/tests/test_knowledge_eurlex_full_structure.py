import pytest

from backend.knowledge.eurlex.article_structure import (
    normalize_eurlex_article_semantic_text,
)
from backend.knowledge.eurlex.full_structure import (
    EurLexFullBlockKind,
    parse_eurlex_full_structure_snapshot,
)
from backend.knowledge.eurlex.parser import (
    parse_eurlex_document_text,
)


ORIGINAL = "32016R0399"


LEGACY = """
<html>
  <body>
    <p class="reference">
      02016R0399 - ES - TEST
    </p>

    <p class="disclaimer">
      Instrumento de documentación.
    </p>

    <p class="title-division-1">
      TÍTULO I
    </p>

    <p class="title-division-2">
      DISPOSICIONES GENERALES
    </p>

    <p class="title-article-norm">
      Artículo 1
    </p>

    <p class="stitle-article-norm">
      Objeto
    </p>

    <p class="norm">
      Texto del artículo uno.
    </p>

    <p class="title-division-1">
      TÍTULO IV
    </p>

    <p class="title-division-2">
      DISPOSICIONES FINALES
    </p>

    <p class="title-article-norm">
      Artículo 45
    </p>

    <p class="stitle-article-norm">
      Entrada en vigor
    </p>

    <p class="norm">
      El presente Reglamento entrará en vigor.
    </p>

    <p class="norm">
      El presente Reglamento será obligatorio
      en todos sus elementos y directamente aplicable.
    </p>

    <hr class="separator-annex"/>

    <p class="title-annex-1">
      ANEXO I
    </p>

    <p class="title-gr-seq-level-1">
      Primer anexo
    </p>

    <p class="norm">
      Contenido del primer anexo.
    </p>

    <hr class="separator-annex"/>

    <p class="title-annex-1">
      ANEXO II
    </p>

    <table>
      <tr>
        <td>
          <p class="tbl-norm">
            Contenido tabular del segundo anexo.
          </p>
        </td>
      </tr>
    </table>
  </body>
</html>
""".encode("utf-8")


ELI = """
<html>
  <body>
    <div class="eli-container">

      <p class="reference">
        02016R0399 - ES - TEST
      </p>

      <p class="disclaimer">
        Instrumento de documentación.
      </p>

      <div class="eli-subdivision" id="tis_I">
        <p class="title-division-1">
          TÍTULO I
        </p>

        <p class="title-division-2">
          DISPOSICIONES GENERALES
        </p>

        <div class="eli-subdivision" id="art_1">
          <p class="title-article-norm">
            Artículo 1
          </p>

          <div class="eli-title">
            <p class="stitle-article-norm">
              Objeto
            </p>
          </div>

          <p class="norm">
            Texto del artículo uno.
          </p>
        </div>
      </div>

      <div class="eli-subdivision" id="tis_IV">
        <p class="title-division-1">
          TÍTULO IV
        </p>

        <p class="title-division-2">
          DISPOSICIONES FINALES
        </p>

        <div class="eli-subdivision" id="art_45">
          <p class="title-article-norm">
            Artículo 45
          </p>

          <div class="eli-title">
            <p class="stitle-article-norm">
              Entrada en vigor
            </p>
          </div>

          <p class="norm">
            El presente Reglamento entrará en vigor.
          </p>
        </div>
      </div>

      <div class="eli-subdivision" id="fnp_1">
        <p class="norm">
          El presente Reglamento será obligatorio
          en todos sus elementos y directamente aplicable.
        </p>
      </div>

      <div id="anx_I">
        <p class="title-annex-1">
          ANEXO I
        </p>

        <p class="title-gr-seq-level-1">
          Primer anexo
        </p>

        <p class="norm">
          Contenido del primer anexo.
        </p>
      </div>

      <div id="anx_II">
        <p class="title-annex-1">
          ANEXO II
        </p>

        <table>
          <tr>
            <td>
              <p class="tbl-norm">
                Contenido tabular del segundo anexo.
              </p>
            </td>
          </tr>
        </table>
      </div>

    </div>
  </body>
</html>
""".encode("utf-8")


def _semantic(value):
    return (
        normalize_eurlex_article_semantic_text(
            value
        )
    )


def test_full_structure_partitions_legacy_document():
    snapshot = (
        parse_eurlex_full_structure_snapshot(
            LEGACY,
            original_celex=ORIGINAL,
            consolidated_celex=(
                "02016R0399-20170407"
            ),
        )
    )

    assert snapshot.renderer == "LEGACY"

    assert tuple(
        block.block_id
        for block
        in snapshot.blocks
    ) == (
        "document:header",
        "division:title:I",
        "article:1",
        "division:title:IV",
        "article:45",
        "document:final-formula",
        "annex:I",
        "annex:II",
    )

    assert snapshot.get(
        "document:header"
    ).kind is EurLexFullBlockKind.HEADER

    assert snapshot.get(
        "division:title:I"
    ).title == "DISPOSICIONES GENERALES"

    assert snapshot.get(
        "article:1"
    ).title == "Objeto"

    assert (
        "El presente Reglamento será obligatorio"
        not in snapshot.get(
            "article:45"
        ).content_text
    )

    assert (
        "El presente Reglamento será obligatorio"
        in snapshot.get(
            "document:final-formula"
        ).content_text
    )

    assert (
        "Contenido tabular del segundo anexo."
        in snapshot.get(
            "annex:II"
        ).content_text
    )


def test_full_structure_partitions_eli_document():
    snapshot = (
        parse_eurlex_full_structure_snapshot(
            ELI,
            original_celex=ORIGINAL,
            consolidated_celex=(
                "02016R0399-20251012"
            ),
        )
    )

    assert snapshot.renderer == "ELI"

    assert tuple(
        block.block_id
        for block
        in snapshot.blocks
    ) == (
        "document:header",
        "division:title:I",
        "article:1",
        "division:title:IV",
        "article:45",
        "document:final-formula",
        "annex:I",
        "annex:II",
    )

    final_formula = snapshot.get(
        "document:final-formula"
    )

    assert final_formula is not None

    assert (
        final_formula.native_structural_id
        == "fnp_1"
    )


def test_full_structure_preserves_complete_visible_text():
    for raw, revision in (
        (
            LEGACY,
            "02016R0399-20170407",
        ),
        (
            ELI,
            "02016R0399-20251012",
        ),
    ):
        snapshot = (
            parse_eurlex_full_structure_snapshot(
                raw,
                original_celex=ORIGINAL,
                consolidated_celex=revision,
            )
        )

        old_full_text = (
            parse_eurlex_document_text(
                raw
            )
        )

        assert (
            _semantic(
                snapshot.current_content_text
            )
            ==
            _semantic(
                old_full_text
            )
        )


def test_full_structure_identity_is_renderer_neutral():
    legacy = (
        parse_eurlex_full_structure_snapshot(
            LEGACY,
            original_celex=ORIGINAL,
            consolidated_celex=(
                "02016R0399-20170407"
            ),
        )
    )

    eli = (
        parse_eurlex_full_structure_snapshot(
            ELI,
            original_celex=ORIGINAL,
            consolidated_celex=(
                "02016R0399-20251012"
            ),
        )
    )

    assert tuple(
        block.block_id
        for block
        in legacy.blocks
    ) == tuple(
        block.block_id
        for block
        in eli.blocks
    )

    assert tuple(
        _semantic(
            block.content_text
        )
        for block
        in legacy.blocks
    ) == tuple(
        _semantic(
            block.content_text
        )
        for block
        in eli.blocks
    )


def test_eli_physical_article_boundary_preserves_external_editorial_marker():
    raw = """
    <html>
      <body>
        <div class="eli-container">

          <p class="reference">
            TEST
          </p>

          <div
            class="eli-subdivision"
            id="tis_I"
          >
            <p class="title-division-1">
              TÍTULO I
            </p>

            <p class="title-division-2">
              DISPOSICIONES GENERALES
            </p>

            <div
              class="eli-subdivision"
              id="art_1"
            >
              <p class="title-article-norm">
                Artículo 1
              </p>

              <p class="norm">
                Contenido jurídico uno.
              </p>
            </div>

            <p class="arrow">
              ▼M3
            </p>

            <div
              class="eli-subdivision"
              id="art_2"
            >
              <p class="title-article-norm">
                Artículo 2
              </p>

              <p class="norm">
                Contenido jurídico dos.
              </p>
            </div>

          </div>
        </div>
      </body>
    </html>
    """.encode(
        "utf-8"
    )

    snapshot = (
        parse_eurlex_full_structure_snapshot(
            raw,
            original_celex=ORIGINAL,
            consolidated_celex=(
                "02016R0399-20251012"
            ),
        )
    )

    assert tuple(
        block.block_id
        for block
        in snapshot.blocks
    ) == (
        "document:header",
        "division:title:I",
        "article:1",
        "editorial:after:article:1",
        "article:2",
    )

    article_1 = snapshot.get(
        "article:1"
    )

    editorial = snapshot.get(
        "editorial:after:article:1"
    )

    article_2 = snapshot.get(
        "article:2"
    )

    assert article_1 is not None
    assert editorial is not None
    assert article_2 is not None

    assert (
        editorial.kind
        is EurLexFullBlockKind.EDITORIAL
    )

    assert "▼M3" not in (
        article_1.content_text
    )

    assert (
        editorial.content_text
        == "▼M3"
    )

    assert "▼M3" not in (
        article_2.content_text
    )


LEGACY_CAPITULO = """
<html>
  <body>
    <p class="reference">
      02016R0399 - ES - TEST
    </p>

    <p class="title-division-1">
      TÍTULO II
    </p>

    <p class="title-division-2">
      FRONTERAS EXTERIORES
    </p>

    <p class="title-division-1">
      CAPÍTULO I
    </p>

    <p class="stitle-division-1">
      Cruce de las fronteras exteriores
    </p>

    <p class="title-article-norm">
      Artículo 5
    </p>

    <p class="norm">
      Texto del artículo cinco.
    </p>
  </body>
</html>
""".encode("utf-8")


ELI_CAPITULO = """
<html>
  <body>
    <div class="eli-container">

      <p class="reference">
        02016R0399 - ES - TEST
      </p>

      <div class="eli-subdivision" id="tis_II">
        <p class="title-division-1">
          TÍTULO II
        </p>

        <p class="title-division-2">
          FRONTERAS EXTERIORES
        </p>

        <div class="eli-subdivision" id="chp_I">
          <p class="title-division-1">
            CAPÍTULO I
          </p>

          <p class="stitle-division-1">
            Cruce de las fronteras exteriores
          </p>

          <div class="eli-subdivision" id="art_5">
            <p class="title-article-norm">
              Artículo 5
            </p>

            <p class="norm">
              Texto del artículo cinco.
            </p>
          </div>
        </div>
      </div>

    </div>
  </body>
</html>
""".encode("utf-8")


def test_full_structure_partitions_capitulo_within_titulo():
    for raw, revision in (
        (
            LEGACY_CAPITULO,
            "02016R0399-20170407",
        ),
        (
            ELI_CAPITULO,
            "02016R0399-20251012",
        ),
    ):
        snapshot = (
            parse_eurlex_full_structure_snapshot(
                raw,
                original_celex=ORIGINAL,
                consolidated_celex=revision,
            )
        )

        assert tuple(
            block.block_id
            for block
            in snapshot.blocks
        ) == (
            "document:header",
            "division:title:II",
            "division:title:II:chapter:I",
            "article:5",
        )

        titulo = snapshot.get(
            "division:title:II"
        )

        capitulo = snapshot.get(
            "division:title:II:chapter:I"
        )

        article_5 = snapshot.get(
            "article:5"
        )

        assert titulo is not None
        assert capitulo is not None
        assert article_5 is not None

        assert (
            titulo.title
            == "FRONTERAS EXTERIORES"
        )

        assert (
            capitulo.title
            == "Cruce de las fronteras exteriores"
        )

        assert (
            "TÍTULO II"
            not in capitulo.content_text
        )

        assert (
            "FRONTERAS EXTERIORES"
            not in capitulo.content_text
        )

        assert (
            "CAPÍTULO I"
            not in article_5.content_text
        )


def test_full_structure_rejects_unknown_division_kind():
    raw = """
    <html>
      <body>
        <p class="title-division-1">
          SECCIÓN I
        </p>

        <p class="title-division-2">
          Contenido de sección.
        </p>

        <p class="title-article-norm">
          Artículo 1
        </p>

        <p class="norm">
          Texto del artículo uno.
        </p>
      </body>
    </html>
    """.encode("utf-8")

    with pytest.raises(
        ValueError,
        match="División EUR-Lex desconocida",
    ):
        parse_eurlex_full_structure_snapshot(
            raw,
            original_celex=ORIGINAL,
            consolidated_celex=(
                "02016R0399-20170407"
            ),
        )


def test_full_structure_rejects_single_unnumbered_annex():
    raw = """
    <html>
      <body>
        <p class="title-article-norm">
          Artículo 1
        </p>

        <p class="norm">
          Texto del artículo uno.
        </p>

        <p class="title-annex-1">
          ANEXO
        </p>

        <p class="norm">
          Contenido del anexo sin numerar.
        </p>
      </body>
    </html>
    """.encode("utf-8")

    with pytest.raises(
        ValueError,
        match="Rótulo EUR-Lex no es ANEXO",
    ):
        parse_eurlex_full_structure_snapshot(
            raw,
            original_celex=ORIGINAL,
            consolidated_celex=(
                "02016R0399-20170407"
            ),
        )


def test_full_structure_rejects_final_formula_split_across_multiple_fnp_subdivisions():
    raw = """
    <html>
      <body>
        <div class="eli-container">

          <p class="reference">
            TEST
          </p>

          <div class="eli-subdivision" id="art_1">
            <p class="title-article-norm">
              Artículo 1
            </p>

            <p class="norm">
              Contenido jurídico uno.
            </p>
          </div>

          <div class="eli-subdivision" id="fnp_1">
            <p class="norm">
              El presente Reglamento será obligatorio
              en todos sus elementos.
            </p>
          </div>

          <div class="eli-subdivision" id="fnp_2">
            <p class="norm">
              Hecho en Bruselas.
            </p>
          </div>

        </div>
      </body>
    </html>
    """.encode("utf-8")

    with pytest.raises(
        ValueError,
        match="duplicado",
    ):
        parse_eurlex_full_structure_snapshot(
            raw,
            original_celex=ORIGINAL,
            consolidated_celex=(
                "02016R0399-20251012"
            ),
        )


def test_full_structure_editorial_marker_before_first_structural_block_is_absorbed_into_header():
    raw = """
    <html>
      <body>
        <p class="reference">
          TEST
        </p>

        <p class="arrow">
          ▼M1
        </p>

        <p class="title-article-norm">
          Artículo 1
        </p>

        <p class="norm">
          Texto del artículo uno.
        </p>
      </body>
    </html>
    """.encode("utf-8")

    snapshot = (
        parse_eurlex_full_structure_snapshot(
            raw,
            original_celex=ORIGINAL,
            consolidated_celex=(
                "02016R0399-20170407"
            ),
        )
    )

    # No finished block exists yet to anchor an EDITORIAL
    # split, so the marker is absorbed into document:header.
    # Documented current behavior, not a fix (see PREAMBLE
    # blocker).
    assert tuple(
        block.block_id
        for block
        in snapshot.blocks
    ) == (
        "document:header",
        "article:1",
    )

    assert (
        "▼M1"
        in snapshot.get(
            "document:header"
        ).content_text
    )


def test_full_structure_rejects_orphan_trailing_content_after_eli_annex_closes():
    raw = """
    <html>
      <body>
        <div class="eli-container">

          <p class="reference">
            TEST
          </p>

          <div class="eli-subdivision" id="tis_I">
            <p class="title-division-1">
              TÍTULO I
            </p>

            <p class="title-division-2">
              DISPOSICIONES GENERALES
            </p>

            <div class="eli-subdivision" id="art_1">
              <p class="title-article-norm">
                Artículo 1
              </p>

              <p class="norm">
                Contenido jurídico uno.
              </p>
            </div>
          </div>

          <div id="anx_I">
            <p class="title-annex-1">
              ANEXO I
            </p>

            <p class="norm">
              Contenido del anexo.
            </p>
          </div>

        </div>

        <p class="footer-disclaimer">
          Aviso de pie de página no estructural.
        </p>
      </body>
    </html>
    """.encode("utf-8")

    with pytest.raises(
        ValueError,
        match="huérfano",
    ):
        parse_eurlex_full_structure_snapshot(
            raw,
            original_celex=ORIGINAL,
            consolidated_celex=(
                "02016R0399-20251012"
            ),
        )


def test_full_structure_eli_annex_is_bounded_by_its_own_container():
    raw = """
    <html>
      <body>
        <div class="eli-container">

          <p class="reference">
            TEST
          </p>

          <div id="anx_I">
            <p class="title-annex-1">
              ANEXO I
            </p>

            <p class="norm">
              Contenido del primer anexo.
            </p>
          </div>

          <div id="anx_II">
            <p class="title-annex-1">
              ANEXO II
            </p>

            <p class="norm">
              Contenido del segundo anexo.
            </p>
          </div>

        </div>
      </body>
    </html>
    """.encode("utf-8")

    snapshot = (
        parse_eurlex_full_structure_snapshot(
            raw,
            original_celex=ORIGINAL,
            consolidated_celex=(
                "02016R0399-20251012"
            ),
        )
    )

    annex_i = snapshot.get(
        "annex:I"
    )

    annex_ii = snapshot.get(
        "annex:II"
    )

    assert annex_i is not None
    assert annex_ii is not None

    assert (
        annex_i.native_structural_id
        == "anx_I"
    )

    assert (
        annex_ii.native_structural_id
        == "anx_II"
    )

    assert (
        "Contenido del segundo anexo"
        not in annex_i.content_text
    )

    assert (
        "Contenido del primer anexo"
        not in annex_ii.content_text
    )


def test_full_structure_parsing_is_deterministic_across_repeated_runs():
    for raw, revision in (
        (
            LEGACY,
            "02016R0399-20170407",
        ),
        (
            ELI,
            "02016R0399-20251012",
        ),
    ):
        first = (
            parse_eurlex_full_structure_snapshot(
                raw,
                original_celex=ORIGINAL,
                consolidated_celex=revision,
            )
        )

        second = (
            parse_eurlex_full_structure_snapshot(
                raw,
                original_celex=ORIGINAL,
                consolidated_celex=revision,
            )
        )

        assert first == second

        assert (
            first.blocks
            == second.blocks
        )


def test_full_structure_ignores_html_comments_as_editorial_noise():
    raw = """
    <html>
      <body>
        <p class="reference">
          02016R0399 - ES - TEST
        </p>

        <p class="title-division-1">
          TÍTULO I
        </p>

        <p class="title-division-2">
          DISPOSICIONES GENERALES
        </p>

        <!-- nota editorial interna, no debe aparecer en el texto -->

        <p class="title-article-norm">
          Artículo 1
        </p>

        <p class="norm">
          Texto del artículo uno.
        </p>
      </body>
    </html>
    """.encode("utf-8")

    snapshot = (
        parse_eurlex_full_structure_snapshot(
            raw,
            original_celex=ORIGINAL,
            consolidated_celex=(
                "02016R0399-20170407"
            ),
        )
    )

    assert tuple(
        block.block_id
        for block
        in snapshot.blocks
    ) == (
        "document:header",
        "division:title:I",
        "article:1",
    )

    assert (
        "nota editorial interna"
        not in snapshot.current_content_text
    )


def test_full_structure_article_identity_ignores_nbsp_in_heading():
    raw = (
        "<html><body>"
        '<p class="reference">02016R0399 - ES - TEST</p>'
        '<p class="title-article-norm">Artículo 1</p>'
        '<p class="norm">Texto del artículo uno.</p>'
        "</body></html>"
    ).encode("utf-8")

    snapshot = (
        parse_eurlex_full_structure_snapshot(
            raw,
            original_celex=ORIGINAL,
            consolidated_celex=(
                "02016R0399-20170407"
            ),
        )
    )

    article = snapshot.get(
        "article:1"
    )

    assert article is not None

    assert (
        article.heading
        == "Artículo 1"
    )


LEGACY_MULTIPLE_ARTICLE_SIBLINGS = """
<html>
  <body>
    <p class="reference">
      02016R0399 - ES - TEST
    </p>

    <p class="title-division-1">
      TÍTULO I
    </p>

    <p class="title-division-2">
      DISPOSICIONES GENERALES
    </p>

    <p class="title-article-norm">
      Artículo 1
    </p>

    <p class="norm">
      Texto uno.
    </p>

    <p class="title-article-norm">
      Artículo 2
    </p>

    <p class="norm">
      Texto dos.
    </p>

    <p class="title-article-norm">
      Artículo 3
    </p>

    <p class="norm">
      Texto tres.
    </p>
  </body>
</html>
""".encode("utf-8")


def test_full_structure_partitions_multiple_article_siblings_within_same_division():
    snapshot = (
        parse_eurlex_full_structure_snapshot(
            LEGACY_MULTIPLE_ARTICLE_SIBLINGS,
            original_celex=ORIGINAL,
            consolidated_celex=(
                "02016R0399-20170407"
            ),
        )
    )

    assert tuple(
        block.block_id
        for block
        in snapshot.blocks
    ) == (
        "document:header",
        "division:title:I",
        "article:1",
        "article:2",
        "article:3",
    )

    assert (
        "Texto dos"
        not in snapshot.get(
            "article:1"
        ).content_text
    )

    assert (
        "Texto tres"
        not in snapshot.get(
            "article:1"
        ).content_text
    )

    assert (
        "Texto uno"
        not in snapshot.get(
            "article:3"
        ).content_text
    )


LEGACY_MULTIPLE_CHAPTER_SIBLINGS = """
<html>
  <body>
    <p class="reference">
      02016R0399 - ES - TEST
    </p>

    <p class="title-division-1">
      TÍTULO II
    </p>

    <p class="title-division-2">
      FRONTERAS EXTERIORES
    </p>

    <p class="title-division-1">
      CAPÍTULO I
    </p>

    <p class="stitle-division-1">
      Cruce de las fronteras exteriores
    </p>

    <p class="title-article-norm">
      Artículo 5
    </p>

    <p class="norm">
      Texto del artículo cinco.
    </p>

    <p class="title-division-1">
      CAPÍTULO II
    </p>

    <p class="stitle-division-1">
      Vigilancia de fronteras
    </p>

    <p class="title-article-norm">
      Artículo 6
    </p>

    <p class="norm">
      Texto del artículo seis.
    </p>
  </body>
</html>
""".encode("utf-8")


ELI_MULTIPLE_CHAPTER_SIBLINGS = """
<html>
  <body>
    <div class="eli-container">

      <p class="reference">
        02016R0399 - ES - TEST
      </p>

      <div class="eli-subdivision" id="tis_II">
        <p class="title-division-1">
          TÍTULO II
        </p>

        <p class="title-division-2">
          FRONTERAS EXTERIORES
        </p>

        <div class="eli-subdivision" id="chp_I">
          <p class="title-division-1">
            CAPÍTULO I
          </p>

          <p class="stitle-division-1">
            Cruce de las fronteras exteriores
          </p>

          <div class="eli-subdivision" id="art_5">
            <p class="title-article-norm">
              Artículo 5
            </p>

            <p class="norm">
              Texto del artículo cinco.
            </p>
          </div>
        </div>

        <div class="eli-subdivision" id="chp_II">
          <p class="title-division-1">
            CAPÍTULO II
          </p>

          <p class="stitle-division-1">
            Vigilancia de fronteras
          </p>

          <div class="eli-subdivision" id="art_6">
            <p class="title-article-norm">
              Artículo 6
            </p>

            <p class="norm">
              Texto del artículo seis.
            </p>
          </div>
        </div>
      </div>

    </div>
  </body>
</html>
""".encode("utf-8")


def test_full_structure_partitions_multiple_chapter_siblings_within_same_title():
    for raw, revision in (
        (
            LEGACY_MULTIPLE_CHAPTER_SIBLINGS,
            "02016R0399-20170407",
        ),
        (
            ELI_MULTIPLE_CHAPTER_SIBLINGS,
            "02016R0399-20251012",
        ),
    ):
        snapshot = (
            parse_eurlex_full_structure_snapshot(
                raw,
                original_celex=ORIGINAL,
                consolidated_celex=revision,
            )
        )

        assert tuple(
            block.block_id
            for block
            in snapshot.blocks
        ) == (
            "document:header",
            "division:title:II",
            "division:title:II:chapter:I",
            "article:5",
            "division:title:II:chapter:II",
            "article:6",
        )

        chapter_i = snapshot.get(
            "division:title:II:chapter:I"
        )

        chapter_ii = snapshot.get(
            "division:title:II:chapter:II"
        )

        assert chapter_i is not None
        assert chapter_ii is not None

        assert (
            "Vigilancia de fronteras"
            not in chapter_i.content_text
        )

        assert (
            "Cruce de las fronteras exteriores"
            not in chapter_ii.content_text
        )


def test_full_structure_block_identity_is_independent_of_attribute_order():
    raw_id_last = """
    <html>
      <body>
        <div class="eli-container">

          <p class="reference">
            TEST
          </p>

          <div class="eli-subdivision" id="art_1">
            <p class="title-article-norm">
              Artículo 1
            </p>

            <p class="norm">
              Contenido jurídico uno.
            </p>
          </div>

        </div>
      </body>
    </html>
    """.encode("utf-8")

    raw_id_first = """
    <html>
      <body>
        <div class="eli-container">

          <p class="reference">
            TEST
          </p>

          <div id="art_1" class="eli-subdivision">
            <p class="title-article-norm">
              Artículo 1
            </p>

            <p class="norm">
              Contenido jurídico uno.
            </p>
          </div>

        </div>
      </body>
    </html>
    """.encode("utf-8")

    snapshot_id_last = (
        parse_eurlex_full_structure_snapshot(
            raw_id_last,
            original_celex=ORIGINAL,
            consolidated_celex=(
                "02016R0399-20251012"
            ),
        )
    )

    snapshot_id_first = (
        parse_eurlex_full_structure_snapshot(
            raw_id_first,
            original_celex=ORIGINAL,
            consolidated_celex=(
                "02016R0399-20251012"
            ),
        )
    )

    assert (
        snapshot_id_last.blocks
        == snapshot_id_first.blocks
    )


def test_full_structure_annex_identity_is_case_insensitive():
    raw = """
    <html>
      <body>
        <p class="reference">
          02016R0399 - ES - TEST
        </p>

        <p class="title-article-norm">
          Artículo 1
        </p>

        <p class="norm">
          Texto del artículo uno.
        </p>

        <hr class="separator-annex"/>

        <p class="title-annex-1">
          anexo iii
        </p>

        <p class="norm">
          Contenido del anexo tres.
        </p>
      </body>
    </html>
    """.encode("utf-8")

    snapshot = (
        parse_eurlex_full_structure_snapshot(
            raw,
            original_celex=ORIGINAL,
            consolidated_celex=(
                "02016R0399-20170407"
            ),
        )
    )

    annex = snapshot.get(
        "annex:III"
    )

    assert annex is not None

    assert (
        "Contenido del anexo tres."
        in annex.content_text
    )


def test_full_structure_output_is_independent_of_source_whitespace_formatting():
    spaced = """
    <html>
      <body>
        <p class="reference">
          02016R0399 - ES - TEST
        </p>

        <p class="title-division-1">
          TÍTULO I
        </p>

        <p class="title-division-2">
          DISPOSICIONES GENERALES
        </p>

        <p class="title-article-norm">
          Artículo 1
        </p>

        <p class="norm">
          Texto del artículo uno.
        </p>
      </body>
    </html>
    """.encode("utf-8")

    compact = (
        "<html><body>"
        '<p class="reference">02016R0399 - ES - TEST</p>'
        '<p class="title-division-1">TÍTULO I</p>'
        '<p class="title-division-2">DISPOSICIONES GENERALES</p>'
        '<p class="title-article-norm">Artículo 1</p>'
        '<p class="norm">Texto del artículo uno.</p>'
        "</body></html>"
    ).encode("utf-8")

    spaced_snapshot = (
        parse_eurlex_full_structure_snapshot(
            spaced,
            original_celex=ORIGINAL,
            consolidated_celex=(
                "02016R0399-20170407"
            ),
        )
    )

    compact_snapshot = (
        parse_eurlex_full_structure_snapshot(
            compact,
            original_celex=ORIGINAL,
            consolidated_celex=(
                "02016R0399-20170407"
            ),
        )
    )

    assert (
        spaced_snapshot.blocks
        == compact_snapshot.blocks
    )
