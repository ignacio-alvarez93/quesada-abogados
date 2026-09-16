"""Estructura canónica de artículos EUR-Lex.

Normaliza dos generaciones XHTML observadas:

LEGACY
    <p class="title-article-norm">Artículo 1</p>

ELI
    <div class="eli-subdivision" id="art_1">
        <p class="title-article-norm">Artículo 1</p>
        ...
    </div>

La identidad jurídica NO depende del id físico del renderer.

Ejemplo:

    Artículo 6 bis
        -> block_id = article:6bis

El id upstream moderno ``art_6a`` se conserva únicamente
como provenance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from html.parser import HTMLParser
import re

from .parser import (
    consolidated_base_celex,
    consolidated_revision_date,
    is_consolidated_celex,
    normalize_celex,
)


_IGNORED_TAGS = {
    "script",
    "style",
    "noscript",
}

_BLOCK_TAGS = {
    "article",
    "blockquote",
    "br",
    "dd",
    "div",
    "dl",
    "dt",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "ol",
    "p",
    "section",
    "table",
    "td",
    "th",
    "tr",
    "ul",
}

_ARTICLE_HEADING_CLASS = (
    "title-article-norm"
)

_ARTICLE_SUBTITLE_CLASS = (
    "stitle-article-norm"
)

_ANNEX_BOUNDARY_CLASSES = {
    "separator-annex",
    "title-annex-1",
}

_STRUCTURAL_DIVISION_CLASSES = {
    "title-division-1",
}

# Fórmula final estándar observada en reglamentos consolidados.
#
# En renderer ELI vive físicamente fuera del último artículo:
#
#   div.eli-subdivision#art_45
#   div.eli-subdivision#fnp_1
#
# LEGACY no expone esa frontera física y, sin esta señal,
# la fórmula termina absorbida por el último artículo.
#
# Esta regla solo afecta al parser ARTICLES_ONLY.
# El futuro full-document parser conservará la fórmula como
# contenido estructural independiente.
_REGULATION_FINAL_FORMULA_PREFIX = (
    "El presente Reglamento será obligatorio "
    "en todos sus elementos"
)

_MODERN_ARTICLE_ID_RE = re.compile(
    r"^art_[A-Za-z0-9]+$"
)

_ARTICLE_LABEL_RE = re.compile(
    r"^art[íi]culo\s+"
    r"(?P<number>\d+)"
    r"(?:\s*(?P<letter>[a-z]))?"
    r"(?:\s+(?P<latin>"
    r"bis|ter|quater|quinquies|sexies|"
    r"septies|octies|nonies|decies"
    r"))?"
    r"\s*$",
    re.IGNORECASE,
)


def _normalize_space(
    value,
) -> str:
    return " ".join(
        str(
            value or ""
        )
        .replace(
            "\xa0",
            " ",
        )
        .split()
    )


def normalize_eurlex_article_semantic_text(
    value: str,
) -> str:
    """Normaliza únicamente whitespace para comparación jurídica.

    No altera ``content_text`` almacenado. Su finalidad es impedir
    que diferencias de serialización LEGACY/ELI creen versiones
    jurídicas falsas.
    """

    return _normalize_space(
        value
    )


def compute_eurlex_article_semantic_sha256(
    value: str,
) -> str:
    """Fingerprint semántico de contenido de artículo EUR-Lex."""

    normalized = (
        normalize_eurlex_article_semantic_text(
            value
        )
    )

    return sha256(
        normalized.encode(
            "utf-8"
        )
    ).hexdigest()


def normalize_eurlex_article_identifier(
    heading: str,
) -> str:
    """Convierte el rótulo jurídico en identidad semántica estable."""

    normalized = _normalize_space(
        heading
    )

    match = _ARTICLE_LABEL_RE.fullmatch(
        normalized
    )

    if match is None:
        raise ValueError(
            "Encabezado EUR-Lex no reconocido "
            f"como artículo: {normalized!r}"
        )

    number = match.group(
        "number"
    )

    letter = (
        match.group(
            "letter"
        )
        or ""
    ).lower()

    latin = (
        match.group(
            "latin"
        )
        or ""
    ).lower()

    if letter and latin:
        raise ValueError(
            "Artículo EUR-Lex contiene "
            "dos sufijos incompatibles"
        )

    legal_identifier = (
        number
        + (
            latin
            or letter
        )
    )

    return legal_identifier


def build_eurlex_article_block_id(
    heading: str,
) -> str:
    return (
        "article:"
        + normalize_eurlex_article_identifier(
            heading
        )
    )


@dataclass(
    frozen=True,
    slots=True,
)
class EurLexArticleBlock:
    """Artículo observado en una expresión consolidada EUR-Lex."""

    block_id: str
    legal_identifier: str
    position: int

    heading: str
    title: str
    content_text: str

    renderer: str

    native_structural_id: str = ""
    heading_source_id: str = ""

    def __post_init__(
        self,
    ) -> None:
        block_id = _normalize_space(
            self.block_id
        )

        legal_identifier = (
            _normalize_space(
                self.legal_identifier
            )
            .lower()
        )

        heading = _normalize_space(
            self.heading
        )

        title = _normalize_space(
            self.title
        )

        content_text = (
            str(
                self.content_text
                or ""
            ).strip()
        )

        renderer = (
            _normalize_space(
                self.renderer
            )
            .upper()
        )

        if (
            block_id
            != (
                "article:"
                + legal_identifier
            )
        ):
            raise ValueError(
                "block_id EUR-Lex no coincide "
                "con legal_identifier"
            )

        if (
            not isinstance(
                self.position,
                int,
            )
            or isinstance(
                self.position,
                bool,
            )
            or self.position < 1
        ):
            raise ValueError(
                "position debe ser entero >= 1"
            )

        if not heading:
            raise ValueError(
                "Artículo EUR-Lex sin heading"
            )

        if not content_text:
            raise ValueError(
                "Artículo EUR-Lex sin contenido"
            )

        if renderer not in {
            "LEGACY",
            "ELI",
        }:
            raise ValueError(
                "renderer EUR-Lex desconocido"
            )

        object.__setattr__(
            self,
            "block_id",
            block_id,
        )
        object.__setattr__(
            self,
            "legal_identifier",
            legal_identifier,
        )
        object.__setattr__(
            self,
            "heading",
            heading,
        )
        object.__setattr__(
            self,
            "title",
            title,
        )
        object.__setattr__(
            self,
            "content_text",
            content_text,
        )
        object.__setattr__(
            self,
            "renderer",
            renderer,
        )
        object.__setattr__(
            self,
            "native_structural_id",
            _normalize_space(
                self.native_structural_id
            ),
        )
        object.__setattr__(
            self,
            "heading_source_id",
            _normalize_space(
                self.heading_source_id
            ),
        )


@dataclass(
    frozen=True,
    slots=True,
)
class EurLexArticleSnapshot:
    """Fotografía estructural de artículos para una revisión sector 0."""

    original_celex: str
    consolidated_celex: str

    effective_from: date

    articles: tuple[
        EurLexArticleBlock,
        ...,
    ]

    def __post_init__(
        self,
    ) -> None:
        original = normalize_celex(
            self.original_celex
        )

        consolidated = normalize_celex(
            self.consolidated_celex
        )

        if not is_consolidated_celex(
            consolidated
        ):
            raise ValueError(
                "EurLexArticleSnapshot requiere "
                "CELEX consolidado sector 0"
            )

        expected_family = (
            consolidated_base_celex(
                original
            )
        )

        actual_family = re.sub(
            r"-[0-9]{8}$",
            "",
            consolidated,
        )

        if (
            expected_family
            != actual_family
        ):
            raise ValueError(
                "original_celex no pertenece "
                "a la familia consolidada"
            )

        expected_date = (
            consolidated_revision_date(
                consolidated
            )
        )

        if (
            expected_date is None
            or self.effective_from
            != expected_date
        ):
            raise ValueError(
                "effective_from no coincide "
                "con fecha sector 0"
            )

        if not self.articles:
            raise ValueError(
                "Snapshot EUR-Lex requiere artículos"
            )

        ids = set()

        expected_position = 1

        for article in self.articles:
            if not isinstance(
                article,
                EurLexArticleBlock,
            ):
                raise TypeError(
                    "articles debe contener "
                    "EurLexArticleBlock"
                )

            if (
                article.block_id
                in ids
            ):
                raise ValueError(
                    "Artículo EUR-Lex duplicado: "
                    f"{article.block_id}"
                )

            if (
                article.position
                != expected_position
            ):
                raise ValueError(
                    "Posiciones EUR-Lex "
                    "no son contiguas"
                )

            ids.add(
                article.block_id
            )

            expected_position += 1

        object.__setattr__(
            self,
            "original_celex",
            original,
        )
        object.__setattr__(
            self,
            "consolidated_celex",
            consolidated,
        )

    def get(
        self,
        block_id: str,
    ) -> EurLexArticleBlock | None:
        identifier = _normalize_space(
            block_id
        )

        for article in self.articles:
            if (
                article.block_id
                == identifier
            ):
                return article

        return None


@dataclass
class _ArticleDraft:
    renderer: str

    native_structural_id: str = ""
    heading_source_id: str = ""

    heading: str = ""
    title: str = ""

    parts: list[str] = None

    container_depth: int | None = None

    def __post_init__(
        self,
    ):
        if self.parts is None:
            self.parts = []


class _EurLexArticleParser(
    HTMLParser
):
    def __init__(
        self,
    ) -> None:
        super().__init__(
            convert_charrefs=True
        )

        self._stack: list[
            tuple[
                str,
                str,
                frozenset[str],
            ]
        ] = []

        self._ignored_depth = 0

        self._current: (
            _ArticleDraft
            | None
        ) = None

        self._articles: list[
            EurLexArticleBlock
        ] = []

        self._heading_capture = False
        self._heading_buffer: list[str] = []

        self._title_capture = False
        self._title_buffer: list[str] = []

        self._pending_legacy_heading_id = ""

        self._seen_block_ids: set[str] = set()

    @staticmethod
    def _attrs(
        attrs,
    ):
        result = {}

        for key, value in attrs:
            result[
                str(
                    key or ""
                ).lower()
            ] = str(
                value or ""
            )

        return result

    @staticmethod
    def _classes(
        attrs,
    ) -> frozenset[str]:
        value = attrs.get(
            "class",
            "",
        )

        return frozenset(
            token
            for token
            in value.split()
            if token
        )

    def _append_boundary(
        self,
    ) -> None:
        if (
            self._current is not None
            and self._current.parts
        ):
            self._current.parts.append(
                "\n"
            )

    def _render_parts(
        self,
        parts,
    ) -> str:
        raw = "".join(
            parts
        )

        lines = []

        for line in raw.splitlines():
            normalized = (
                _normalize_space(
                    line
                )
            )

            if normalized:
                lines.append(
                    normalized
                )

        return "\n".join(
            lines
        ).strip()

    def _finish_current(
        self,
    ) -> None:
        current = self._current

        if current is None:
            return

        heading = _normalize_space(
            current.heading
        )

        if not heading:
            raise ValueError(
                "Artículo EUR-Lex "
                "sin heading capturado"
            )

        legal_identifier = (
            normalize_eurlex_article_identifier(
                heading
            )
        )

        block_id = (
            "article:"
            + legal_identifier
        )

        if block_id in self._seen_block_ids:
            raise ValueError(
                "Artículo EUR-Lex duplicado: "
                f"{block_id}"
            )

        content_text = (
            self._render_parts(
                current.parts
            )
        )

        if not content_text:
            raise ValueError(
                "Artículo EUR-Lex "
                f"sin texto: {block_id}"
            )

        article = EurLexArticleBlock(
            block_id=block_id,
            legal_identifier=(
                legal_identifier
            ),
            position=(
                len(
                    self._articles
                )
                + 1
            ),
            heading=heading,
            title=current.title,
            content_text=(
                content_text
            ),
            renderer=(
                current.renderer
            ),
            native_structural_id=(
                current.native_structural_id
            ),
            heading_source_id=(
                current.heading_source_id
            ),
        )

        self._articles.append(
            article
        )

        self._seen_block_ids.add(
            block_id
        )

        self._current = None

    def handle_starttag(
        self,
        tag,
        attrs,
    ):
        name = str(
            tag or ""
        ).lower()

        attributes = self._attrs(
            attrs
        )

        classes = self._classes(
            attributes
        )

        identifier = str(
            attributes.get(
                "id",
                "",
            )
            or ""
        ).strip()

        self._stack.append(
            (
                name,
                identifier,
                classes,
            )
        )

        if name in _IGNORED_TAGS:
            self._ignored_depth += 1
            return

        if self._ignored_depth:
            return

        # ----------------------------------------------
        # Legacy structural division boundary.
        #
        # LEGACY no envuelve cada artículo en un contenedor
        # físico. Sin esta frontera, TÍTULO/CAPÍTULO que
        # aparecen después de un artículo terminan siendo
        # absorbidos por el artículo precedente.
        #
        # ELI no necesita esta regla porque eli-subdivision
        # delimita físicamente el artículo.
        # ----------------------------------------------

        if (
            self._current is not None
            and self._current.renderer
            == "LEGACY"
            and (
                classes
                & _STRUCTURAL_DIVISION_CLASSES
            )
        ):
            self._finish_current()

        # ----------------------------------------------
        # Modern ELI article container.
        # ----------------------------------------------

        if (
            name == "div"
            and (
                "eli-subdivision"
                in classes
            )
            and _MODERN_ARTICLE_ID_RE.fullmatch(
                identifier
            )
        ):
            if self._current is not None:
                self._finish_current()

            self._current = (
                _ArticleDraft(
                    renderer="ELI",
                    native_structural_id=(
                        identifier
                    ),
                    container_depth=(
                        len(
                            self._stack
                        )
                    ),
                )
            )

        # ----------------------------------------------
        # Actual article heading.
        # Tables use tbl-norm and therefore never enter.
        # ----------------------------------------------

        if (
            name == "p"
            and (
                _ARTICLE_HEADING_CLASS
                in classes
            )
        ):
            if (
                self._current is None
            ):
                # Legacy article starts here.
                self._finish_current()

                self._current = (
                    _ArticleDraft(
                        renderer="LEGACY",
                        heading_source_id=(
                            identifier
                        ),
                    )
                )

            elif (
                self._current.renderer
                == "LEGACY"
                and self._current.heading
            ):
                # New legacy article.
                self._finish_current()

                self._current = (
                    _ArticleDraft(
                        renderer="LEGACY",
                        heading_source_id=(
                            identifier
                        ),
                    )
                )

            else:
                # Modern article: preserve the UUID heading
                # separately from native art_* identity.
                self._current.heading_source_id = (
                    identifier
                )

            self._heading_capture = True
            self._heading_buffer = []

        if (
            name == "p"
            and (
                _ARTICLE_SUBTITLE_CLASS
                in classes
            )
            and self._current
            is not None
        ):
            self._title_capture = True
            self._title_buffer = []

        # Annex means no article can continue into annex content
        # in legacy renderer.
        if (
            self._current
            is not None
            and self._current.renderer
            == "LEGACY"
            and (
                classes
                & _ANNEX_BOUNDARY_CLASSES
            )
        ):
            self._finish_current()

        if (
            self._current
            is not None
            and name
            in _BLOCK_TAGS
        ):
            self._append_boundary()

    def handle_endtag(
        self,
        tag,
    ):
        name = str(
            tag or ""
        ).lower()

        if name in _IGNORED_TAGS:
            if self._ignored_depth:
                self._ignored_depth -= 1

            if self._stack:
                self._stack.pop()

            return

        if not self._ignored_depth:
            if (
                name == "p"
                and self._heading_capture
            ):
                heading = _normalize_space(
                    " ".join(
                        self._heading_buffer
                    )
                )

                if (
                    self._current
                    is None
                ):
                    raise ValueError(
                        "Heading EUR-Lex "
                        "sin artículo activo"
                    )

                self._current.heading = (
                    heading
                )

                # Legacy empezó antes de tener el texto.
                if (
                    self._current.renderer
                    == "LEGACY"
                    and heading
                ):
                    self._current.parts.append(
                        heading
                    )
                    self._current.parts.append(
                        "\n"
                    )

                self._heading_capture = False
                self._heading_buffer = []

            if (
                name == "p"
                and self._title_capture
            ):
                title = _normalize_space(
                    " ".join(
                        self._title_buffer
                    )
                )

                if (
                    self._current
                    is not None
                ):
                    self._current.title = (
                        title
                    )

                self._title_capture = False
                self._title_buffer = []

            if (
                self._current
                is not None
                and name
                in _BLOCK_TAGS
            ):
                self._append_boundary()

            if (
                self._current
                is not None
                and self._current.renderer
                == "ELI"
                and name == "div"
                and (
                    self._current.container_depth
                    == len(
                        self._stack
                    )
                )
            ):
                self._finish_current()

        if self._stack:
            self._stack.pop()

    def handle_startendtag(
        self,
        tag,
        attrs,
    ):
        self.handle_starttag(
            tag,
            attrs,
        )

        self.handle_endtag(
            tag
        )

    def handle_data(
        self,
        data,
    ):
        if self._ignored_depth:
            return

        normalized = _normalize_space(
            data
        )

        if not normalized:
            return

        # ----------------------------------------------
        # Legacy regulation final-formula boundary.
        #
        # ELI delimita físicamente la fórmula final en un
        # eli-subdivision independiente (fnp_*). LEGACY no
        # proporciona esa envoltura, por lo que debemos cerrar
        # el último artículo antes de absorber la fórmula.
        #
        # La fórmula no se pierde: este parser es ARTICLES_ONLY;
        # full_structure.py será responsable de conservarla.
        # ----------------------------------------------

        if (
            self._current is not None
            and self._current.renderer
            == "LEGACY"
            and normalized.startswith(
                _REGULATION_FINAL_FORMULA_PREFIX
            )
        ):
            self._finish_current()
            return

        if self._heading_capture:
            self._heading_buffer.append(
                normalized
            )

        if self._title_capture:
            self._title_buffer.append(
                normalized
            )

        if (
            self._current
            is not None
            and (
                self._current.renderer
                == "ELI"
                or not self._heading_capture
            )
        ):
            self._current.parts.append(
                normalized
            )
            self._current.parts.append(
                " "
            )

    def close(
        self,
    ):
        super().close()

        self._finish_current()

    @property
    def articles(
        self,
    ) -> tuple[
        EurLexArticleBlock,
        ...,
    ]:
        return tuple(
            self._articles
        )


def parse_eurlex_article_snapshot(
    raw_xhtml: bytes,
    *,
    original_celex: str,
    consolidated_celex: str,
) -> EurLexArticleSnapshot:
    """Parsea artículos de cualquier renderer consolidado observado."""

    if not isinstance(
        raw_xhtml,
        (
            bytes,
            bytearray,
        ),
    ):
        raise TypeError(
            "EUR-Lex XHTML debe recibirse "
            "como bytes"
        )

    consolidated = normalize_celex(
        consolidated_celex
    )

    if not is_consolidated_celex(
        consolidated
    ):
        raise ValueError(
            "Se requiere CELEX consolidado "
            "sector 0"
        )

    effective_from = (
        consolidated_revision_date(
            consolidated
        )
    )

    if effective_from is None:
        raise ValueError(
            "CELEX consolidado sin fecha"
        )

    raw = bytes(
        raw_xhtml
    )

    try:
        decoded = raw.decode(
            "utf-8-sig"
        )
    except UnicodeDecodeError:
        decoded = raw.decode(
            "utf-8",
            errors="replace",
        )

    parser = _EurLexArticleParser()

    try:
        parser.feed(
            decoded
        )

        parser.close()

    except Exception as exc:
        if isinstance(
            exc,
            (
                TypeError,
                ValueError,
            ),
        ):
            raise

        raise ValueError(
            "EUR-Lex article XHTML "
            "no pudo procesarse"
        ) from exc

    articles = parser.articles

    if not articles:
        raise ValueError(
            "EUR-Lex no produjo "
            "artículos estructurados"
        )

    return EurLexArticleSnapshot(
        original_celex=(
            original_celex
        ),
        consolidated_celex=(
            consolidated
        ),
        effective_from=(
            effective_from
        ),
        articles=articles,
    )
