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
