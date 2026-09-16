"""Estructura documental completa de EUR-Lex consolidado.

Responsabilidad de esta capa:

    XHTML EUR-Lex
        -> header
        -> divisiones
        -> artículos
        -> fórmula final
        -> anexos

El parser produce una representación canónica completa y ordenada.

No realiza:

- HTTP;
- persistencia;
- integración con KnowledgeStructuredProvider;
- interpretación jurídica;
- IA.

La identidad semántica nunca depende de UUID físicos del renderer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from html.parser import HTMLParser
import re

from .article_structure import (
    normalize_eurlex_article_identifier,
)
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

_DIVISION_HEADING_CLASS = (
    "title-division-1"
)

_DIVISION_SUBTITLE_CLASSES = {
    "title-division-2",
    "stitle-division-1",
}

_ARTICLE_HEADING_CLASS = (
    "title-article-norm"
)

_ARTICLE_SUBTITLE_CLASS = (
    "stitle-article-norm"
)

_ANNEX_HEADING_CLASS = (
    "title-annex-1"
)

_FINAL_FORMULA_PREFIX = (
    "El presente Reglamento será obligatorio "
    "en todos sus elementos"
)

_EDITORIAL_MARKER_CLASSES = {
    "arrow",
    "modref",
}

_MODERN_ARTICLE_ID_RE = re.compile(
    r"^art_[A-Za-z0-9]+$"
)

_MODERN_FINAL_FORMULA_ID_RE = re.compile(
    r"^fnp_[A-Za-z0-9]+$"
)

_ROMAN_RE = re.compile(
    r"^[IVXLCDM]+$"
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


def _roman_from_label(
    value: str,
    prefix: str,
) -> str:
    normalized = (
        _normalize_space(
            value
        ).upper()
    )

    expected = (
        prefix.upper()
        + " "
    )

    if not normalized.startswith(
        expected
    ):
        raise ValueError(
            f"Rótulo EUR-Lex no es {prefix}: "
            f"{normalized!r}"
        )

    roman = normalized[
        len(
            expected
        ):
    ].strip()

    if not _ROMAN_RE.fullmatch(
        roman
    ):
        raise ValueError(
            "Número romano EUR-Lex "
            f"no reconocido: {roman!r}"
        )

    return roman


class EurLexFullBlockKind(
    str,
    Enum,
):
    HEADER = "HEADER"
    DIVISION = "DIVISION"
    ARTICLE = "ARTICLE"
    EDITORIAL = "EDITORIAL"
    FINAL_FORMULA = "FINAL_FORMULA"
    ANNEX = "ANNEX"


@dataclass(
    frozen=True,
    slots=True,
)
class EurLexFullBlock:
    block_id: str
    kind: EurLexFullBlockKind
    position: int

    content_text: str

    heading: str = ""
    title: str = ""

    native_structural_id: str = ""

    def __post_init__(
        self,
    ) -> None:
        block_id = str(
            self.block_id or ""
        ).strip()

        if not block_id:
            raise ValueError(
                "EurLexFullBlock requiere block_id"
            )

        if not isinstance(
            self.kind,
            EurLexFullBlockKind,
        ):
            raise TypeError(
                "kind debe ser EurLexFullBlockKind"
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

        content_text = str(
            self.content_text or ""
        ).strip()

        if not content_text:
            raise ValueError(
                "EurLexFullBlock requiere contenido"
            )

        object.__setattr__(
            self,
            "block_id",
            block_id,
        )

        object.__setattr__(
            self,
            "content_text",
            content_text,
        )

        object.__setattr__(
            self,
            "heading",
            _normalize_space(
                self.heading
            ),
        )

        object.__setattr__(
            self,
            "title",
            _normalize_space(
                self.title
            ),
        )

        object.__setattr__(
            self,
            "native_structural_id",
            str(
                self.native_structural_id
                or ""
            ).strip(),
        )


@dataclass(
    frozen=True,
    slots=True,
)
class EurLexFullStructureSnapshot:
    original_celex: str
    consolidated_celex: str

    effective_from: date
    renderer: str

    blocks: tuple[
        EurLexFullBlock,
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

        if is_consolidated_celex(
            original
        ):
            raise ValueError(
                "original_celex no puede ser sector 0"
            )

        if not is_consolidated_celex(
            consolidated
        ):
            raise ValueError(
                "consolidated_celex debe ser sector 0"
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
                "original_celex y consolidado "
                "no pertenecen a la misma familia"
            )

        expected_date = (
            consolidated_revision_date(
                consolidated
            )
        )

        if (
            expected_date is None
            or expected_date
            != self.effective_from
        ):
            raise ValueError(
                "effective_from no coincide "
                "con revisión sector 0"
            )

        renderer = str(
            self.renderer or ""
        ).strip().upper()

        if renderer not in {
            "LEGACY",
            "ELI",
        }:
            raise ValueError(
                "renderer EUR-Lex desconocido"
            )

        if not self.blocks:
            raise ValueError(
                "Full structure requiere bloques"
            )

        expected_position = 1
        seen = set()

        for block in self.blocks:
            if not isinstance(
                block,
                EurLexFullBlock,
            ):
                raise TypeError(
                    "blocks debe contener "
                    "EurLexFullBlock"
                )

            if (
                block.position
                != expected_position
            ):
                raise ValueError(
                    "Posiciones full structure "
                    "no son contiguas"
                )

            if block.block_id in seen:
                raise ValueError(
                    "block_id duplicado: "
                    f"{block.block_id}"
                )

            seen.add(
                block.block_id
            )

            expected_position += 1

        if (
            self.blocks[0].block_id
            != "document:header"
        ):
            raise ValueError(
                "Primer bloque debe ser document:header"
            )

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

        object.__setattr__(
            self,
            "renderer",
            renderer,
        )

    def get(
        self,
        block_id: str,
    ) -> EurLexFullBlock | None:
        identifier = str(
            block_id or ""
        ).strip()

        for block in self.blocks:
            if (
                block.block_id
                == identifier
            ):
                return block

        return None

    @property
    def current_content_text(
        self,
    ) -> str:
        return "\n\n".join(
            block.content_text
            for block
            in self.blocks
        ).strip()


@dataclass
class _BlockDraft:
    kind: EurLexFullBlockKind
    block_id: str = ""

    heading: str = ""
    title: str = ""

    native_structural_id: str = ""

    container_depth: int | None = None

    parts: list[str] | None = None

    def __post_init__(
        self,
    ) -> None:
        if self.parts is None:
            self.parts = []


class _EurLexFullStructureParser(
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

        self._blocks: list[
            EurLexFullBlock
        ] = []

        self._seen_block_ids: set[
            str
        ] = set()

        self._current = _BlockDraft(
            kind=(
                EurLexFullBlockKind.HEADER
            ),
            block_id="document:header",
        )

        self._heading_capture = False
        self._heading_buffer: list[str] = []

        self._title_capture = False
        self._title_buffer: list[str] = []

        self._current_title_roman = ""

        self._editorial_counts: dict[
            str,
            int,
        ] = {}

        self._saw_eli = False

    @staticmethod
    def _attrs(
        attrs,
    ) -> dict[str, str]:
        return {
            str(
                key or ""
            ).lower():
            str(
                value or ""
            )
            for key, value
            in attrs
        }

    @staticmethod
    def _classes(
        attrs,
    ) -> frozenset[str]:
        return frozenset(
            token
            for token
            in attrs.get(
                "class",
                "",
            ).split()
            if token
        )

    def _nearest_native_id(
        self,
        *,
        prefix: str = "",
    ) -> str:
        for (
            _name,
            identifier,
            _classes,
        ) in reversed(
            self._stack
        ):
            if not identifier:
                continue

            if (
                not prefix
                or identifier.startswith(
                    prefix
                )
            ):
                return identifier

        return ""

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

    @staticmethod
    def _render_parts(
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

        content_text = (
            self._render_parts(
                current.parts
            )
        )

        if not content_text:
            self._current = None
            return

        block_id = str(
            current.block_id or ""
        ).strip()

        if not block_id:
            raise ValueError(
                "Bloque EUR-Lex completo "
                "sin identidad"
            )

        if block_id in self._seen_block_ids:
            raise ValueError(
                "Bloque EUR-Lex completo "
                f"duplicado: {block_id}"
            )

        block = EurLexFullBlock(
            block_id=block_id,
            kind=current.kind,
            position=(
                len(
                    self._blocks
                )
                + 1
            ),
            content_text=content_text,
            heading=current.heading,
            title=current.title,
            native_structural_id=(
                current.native_structural_id
            ),
        )

        self._blocks.append(
            block
        )

        self._seen_block_ids.add(
            block_id
        )

        self._current = None

    def _start_block(
        self,
        *,
        kind: EurLexFullBlockKind,
        block_id: str = "",
        native_structural_id: str = "",
        container_depth: int | None = None,
    ) -> None:
        self._finish_current()

        self._current = _BlockDraft(
            kind=kind,
            block_id=block_id,
            native_structural_id=(
                native_structural_id
            ),
            container_depth=(
                container_depth
            ),
        )

    def _start_editorial_after_previous(
        self,
    ) -> None:
        if not self._blocks:
            raise ValueError(
                "Editorial EUR-Lex sin bloque "
                "estructural precedente"
            )

        anchor = self._blocks[
            -1
        ].block_id

        count = (
            self._editorial_counts.get(
                anchor,
                0,
            )
            + 1
        )

        self._editorial_counts[
            anchor
        ] = count

        block_id = (
            "editorial:after:"
            + anchor
        )

        if count > 1:
            block_id = (
                block_id
                + ":"
                + str(
                    count
                )
            )

        self._current = _BlockDraft(
            kind=(
                EurLexFullBlockKind.EDITORIAL
            ),
            block_id=block_id,
        )

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

        if (
            "eli-subdivision"
            in classes
        ):
            self._saw_eli = True

        if name in _IGNORED_TAGS:
            self._ignored_depth += 1
            return

        if self._ignored_depth:
            return

        # ----------------------------------------------
        # Modern ELI physical ownership.
        #
        # article_structure.py already proved that art_*
        # physically owns exactly one legal article.
        # The full parser must preserve that same boundary.
        # ----------------------------------------------

        if (
            name == "div"
            and "eli-subdivision"
            in classes
            and _MODERN_ARTICLE_ID_RE.fullmatch(
                identifier
            )
        ):
            self._start_block(
                kind=(
                    EurLexFullBlockKind.ARTICLE
                ),
                native_structural_id=(
                    identifier
                ),
                container_depth=(
                    len(
                        self._stack
                    )
                ),
            )

        elif (
            name == "div"
            and "eli-subdivision"
            in classes
            and _MODERN_FINAL_FORMULA_ID_RE.fullmatch(
                identifier
            )
        ):
            self._start_block(
                kind=(
                    EurLexFullBlockKind.FINAL_FORMULA
                ),
                block_id=(
                    "document:final-formula"
                ),
                native_structural_id=(
                    identifier
                ),
                container_depth=(
                    len(
                        self._stack
                    )
                ),
            )

        if (
            name == "p"
            and _DIVISION_HEADING_CLASS
            in classes
        ):
            self._start_block(
                kind=(
                    EurLexFullBlockKind.DIVISION
                ),
                native_structural_id=(
                    identifier
                ),
            )

            self._heading_capture = True
            self._heading_buffer = []

        elif (
            name == "p"
            and _ARTICLE_HEADING_CLASS
            in classes
        ):
            if not (
                self._current
                is not None
                and self._current.kind
                is EurLexFullBlockKind.ARTICLE
                and self._current.container_depth
                is not None
            ):
                # LEGACY has no physical art_* container.
                self._start_block(
                    kind=(
                        EurLexFullBlockKind.ARTICLE
                    ),
                    native_structural_id=(
                        identifier
                    ),
                )

            self._heading_capture = True
            self._heading_buffer = []

        elif (
            name == "p"
            and _ANNEX_HEADING_CLASS
            in classes
        ):
            self._start_block(
                kind=(
                    EurLexFullBlockKind.ANNEX
                ),
                native_structural_id=(
                    identifier
                ),
            )

            self._heading_capture = True
            self._heading_buffer = []

        elif (
            name == "p"
            and (
                classes
                & _DIVISION_SUBTITLE_CLASSES
            )
            and self._current
            is not None
            and self._current.kind
            is EurLexFullBlockKind.DIVISION
        ):
            self._title_capture = True
            self._title_buffer = []

        elif (
            name == "p"
            and _ARTICLE_SUBTITLE_CLASS
            in classes
            and self._current
            is not None
            and self._current.kind
            is EurLexFullBlockKind.ARTICLE
        ):
            self._title_capture = True
            self._title_buffer = []

        if (
            self._current is not None
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
                        "Heading sin bloque activo"
                    )

                self._current.heading = (
                    heading
                )

                if (
                    self._current.kind
                    is EurLexFullBlockKind.ARTICLE
                ):
                    legal_identifier = (
                        normalize_eurlex_article_identifier(
                            heading
                        )
                    )

                    self._current.block_id = (
                        "article:"
                        + legal_identifier
                    )

                elif (
                    self._current.kind
                    is EurLexFullBlockKind.ANNEX
                ):
                    roman = _roman_from_label(
                        heading,
                        "ANEXO",
                    )

                    self._current.block_id = (
                        "annex:"
                        + roman
                    )

                elif (
                    self._current.kind
                    is EurLexFullBlockKind.DIVISION
                ):
                    upper = heading.upper()

                    if upper.startswith(
                        "TÍTULO "
                    ):
                        roman = (
                            _roman_from_label(
                                heading,
                                "TÍTULO",
                            )
                        )

                        self._current_title_roman = (
                            roman
                        )

                        self._current.block_id = (
                            "division:title:"
                            + roman
                        )

                    elif upper.startswith(
                        "CAPÍTULO "
                    ):
                        if not (
                            self._current_title_roman
                        ):
                            raise ValueError(
                                "CAPÍTULO sin TÍTULO padre"
                            )

                        chapter = (
                            _roman_from_label(
                                heading,
                                "CAPÍTULO",
                            )
                        )

                        self._current.block_id = (
                            "division:title:"
                            f"{self._current_title_roman}"
                            ":chapter:"
                            f"{chapter}"
                        )

                    else:
                        raise ValueError(
                            "División EUR-Lex desconocida: "
                            f"{heading!r}"
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
            not self._ignored_depth
            and self._current
            is not None
            and self._current.container_depth
            is not None
            and name == "div"
            and (
                self._current.container_depth
                == len(
                    self._stack
                )
            )
            and self._current.kind
            in {
                EurLexFullBlockKind.ARTICLE,
                EurLexFullBlockKind.FINAL_FORMULA,
            }
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

        active_classes = frozenset(
            class_name
            for _tag, _identifier, classes
            in self._stack
            for class_name
            in classes
        )

        # Amendment/base markers can live outside the ELI
        # article container and their semantic class may sit
        # on an ancestor <p> while the text itself lives in
        # a nested <a>/<span>.
        #
        # Detect by DOM ownership, never by the glyph alone.
        if (
            self._current is None
            and (
                active_classes
                & _EDITORIAL_MARKER_CLASSES
            )
        ):
            self._start_editorial_after_previous()

        # LEGACY exposes no physical fnp_* wrapper.
        # Its final-formula boundary therefore remains
        # semantic, as already audited in C3B.
        if (
            self._current
            is not None
            and self._current.kind
            is EurLexFullBlockKind.ARTICLE
            and self._current.container_depth
            is None
            and normalized.startswith(
                _FINAL_FORMULA_PREFIX
            )
        ):
            self._start_block(
                kind=(
                    EurLexFullBlockKind.FINAL_FORMULA
                ),
                block_id=(
                    "document:final-formula"
                ),
            )

        if self._heading_capture:
            self._heading_buffer.append(
                normalized
            )

        if self._title_capture:
            self._title_buffer.append(
                normalized
            )

        if self._current is not None:
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
    def renderer(
        self,
    ) -> str:
        return (
            "ELI"
            if self._saw_eli
            else "LEGACY"
        )

    @property
    def blocks(
        self,
    ) -> tuple[
        EurLexFullBlock,
        ...,
    ]:
        return tuple(
            self._blocks
        )


def parse_eurlex_full_structure_snapshot(
    raw_xhtml: bytes,
    *,
    original_celex: str,
    consolidated_celex: str,
) -> EurLexFullStructureSnapshot:
    """Parsea la estructura completa de una revisión EUR-Lex."""

    if not isinstance(
        raw_xhtml,
        (
            bytes,
            bytearray,
        ),
    ):
        raise TypeError(
            "EUR-Lex XHTML debe recibirse como bytes"
        )

    consolidated = normalize_celex(
        consolidated_celex
    )

    effective_from = (
        consolidated_revision_date(
            consolidated
        )
    )

    if effective_from is None:
        raise ValueError(
            "Full structure requiere "
            "revisión consolidada fechada"
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

    parser = (
        _EurLexFullStructureParser()
    )

    try:
        parser.feed(
            decoded
        )

        parser.close()

    except Exception as exc:
        raise ValueError(
            "EUR-Lex full structure "
            "no pudo procesarse"
        ) from exc

    return EurLexFullStructureSnapshot(
        original_celex=(
            original_celex
        ),
        consolidated_celex=(
            consolidated
        ),
        effective_from=(
            effective_from
        ),
        renderer=(
            parser.renderer
        ),
        blocks=(
            parser.blocks
        ),
    )
