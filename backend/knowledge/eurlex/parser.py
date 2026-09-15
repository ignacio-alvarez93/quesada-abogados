"""Contratos puros de identidad CELEX y metadata Cellar.

Responsabilidades V1.4B1:

- normalizar y validar identificadores CELEX;
- distinguir acto original y consolidado;
- derivar la familia consolidada de un acto;
- seleccionar de forma determinista la revisión consolidada más reciente;
- extraer CELEX y ELI desde un ``tree notice`` XML estructurado.

No realiza HTTP, persistencia, UI ni IA.
"""

from __future__ import annotations

from datetime import date
import re
import xml.etree.ElementTree as ET


EUR_LEX_SOURCE_KEY = "EUR_LEX"
EUR_LEX_CONSOLIDATED_SOURCE_KEY = (
    "EUR_LEX_CONSOLIDATED"
)


# Cobertura deliberadamente gobernada para V1:
#
#   12016M/TXT
#   12016E/TXT
#   12016P/TXT
#   32016R0399
#   32024L1233
#   02016R0399-20251012
#   02016M/TXT-20250315
#
# No intentamos representar aquí toda la gramática histórica
# posible de CELEX. El parser es fail-closed.
_CELEX_PATTERN = re.compile(
    r"^"
    r"(?P<sector>[0136])"
    r"(?P<body>[0-9]{4}[A-Z][A-Z0-9]*)"
    r"(?P<suffix>/[A-Z0-9]+)?"
    r"(?P<revision>-[0-9]{8})?"
    r"$"
)


def normalize_celex(
    value: str,
) -> str:
    """Normaliza y valida un identificador CELEX soportado."""

    celex = str(
        value or ""
    ).strip().upper()

    if not celex:
        raise ValueError(
            "CELEX no puede estar vacío"
        )

    if not _CELEX_PATTERN.fullmatch(
        celex
    ):
        raise ValueError(
            "Formato CELEX no soportado: "
            f"{celex}"
        )

    return celex


def celex_sector(
    value: str,
) -> str:
    """Devuelve el sector CELEX como carácter."""

    return normalize_celex(
        value
    )[0]


def is_consolidated_celex(
    value: str,
) -> bool:
    """Indica si la identidad pertenece al sector 0."""

    return (
        celex_sector(
            value
        )
        == "0"
    )


def consolidated_base_celex(
    original_celex: str,
) -> str:
    """Deriva la familia sector-0 de una identidad original.

    Ejemplos:

        32016R0399
        -> 02016R0399

        12016M/TXT
        -> 02016M/TXT

    La fecha de revisión no forma parte de la identidad estable
    de la norma en Knowledge.
    """

    celex = normalize_celex(
        original_celex
    )

    sector = celex[0]

    if sector not in {
        "1",
        "3",
    }:
        raise ValueError(
            "Solo actos CELEX sector 1 o 3 "
            "pueden originar familia consolidada"
        )

    if re.search(
        r"-[0-9]{8}$",
        celex,
    ):
        raise ValueError(
            "original_celex no debe contener "
            "fecha de revisión"
        )

    return (
        "0"
        + celex[1:]
    )


def consolidated_revision_date(
    consolidated_celex: str,
) -> date | None:
    """Extrae fecha de revisión de un CELEX consolidado."""

    celex = normalize_celex(
        consolidated_celex
    )

    if not is_consolidated_celex(
        celex
    ):
        raise ValueError(
            "Se requiere CELEX sector 0"
        )

    match = re.search(
        r"-([0-9]{8})$",
        celex,
    )

    if match is None:
        return None

    raw = match.group(1)

    try:
        return date(
            int(raw[:4]),
            int(raw[4:6]),
            int(raw[6:8]),
        )
    except ValueError as exc:
        raise ValueError(
            "CELEX contiene fecha de revisión inválida"
        ) from exc


def _is_consolidated_candidate(
    *,
    base: str,
    candidate: str,
) -> bool:
    if candidate == base:
        return True

    pattern = re.compile(
        re.escape(
            base
        )
        + r"-[0-9]{8}$"
    )

    return bool(
        pattern.fullmatch(
            candidate
        )
    )


def list_consolidated_celex_revisions(
    original_celex: str,
    identifiers: tuple[str, ...] | list[str],
) -> tuple[str, ...]:
    """Devuelve revisiones sector-0 en orden más reciente -> más antigua.

    La ordenación es deliberadamente independiente de idioma.

    Que una revisión exista NO implica que exista una expresión
    española para esa revisión. Esa segunda decisión corresponde
    al transport/provider.
    """

    base = consolidated_base_celex(
        original_celex
    )

    dated: list[
        tuple[
            date,
            str,
        ]
    ] = []

    undated: set[str] = set()

    for raw in identifiers:
        try:
            candidate = normalize_celex(
                raw
            )
        except ValueError:
            continue

        if not _is_consolidated_candidate(
            base=base,
            candidate=candidate,
        ):
            continue

        revision = (
            consolidated_revision_date(
                candidate
            )
        )

        if revision is None:
            undated.add(
                candidate
            )
        else:
            dated.append(
                (
                    revision,
                    candidate,
                )
            )

    dated.sort(
        key=lambda item: (
            item[0],
            item[1],
        ),
        reverse=True,
    )

    result = [
        candidate
        for _, candidate
        in dated
    ]

    # Una identidad sector-0 sin fecha es menos específica
    # que una revisión fechada.
    result.extend(
        sorted(
            undated,
            reverse=True,
        )
    )

    return tuple(
        result
    )


def select_latest_consolidated_celex(
    original_celex: str,
    identifiers: tuple[str, ...] | list[str],
) -> str | None:
    """Selecciona la revisión sector-0 más reciente.

    Importante para tratados:

        base:
        02016M/TXT

        revisión:
        02016M/TXT-20250315

    La fecha está DESPUÉS de ``/TXT``.
    """

    base = consolidated_base_celex(
        original_celex
    )

    candidates: set[str] = set()

    for raw in identifiers:
        try:
            candidate = normalize_celex(
                raw
            )
        except ValueError:
            continue

        if not _is_consolidated_candidate(
            base=base,
            candidate=candidate,
        ):
            continue

        candidates.add(
            candidate
        )

    if not candidates:
        return None

    dated: list[
        tuple[
            date,
            str,
        ]
    ] = []

    for candidate in candidates:
        revision_date = (
            consolidated_revision_date(
                candidate
            )
        )

        if revision_date is not None:
            dated.append(
                (
                    revision_date,
                    candidate,
                )
            )

    if dated:
        dated.sort(
            key=lambda item: (
                item[0],
                item[1],
            )
        )

        return dated[-1][1]

    if base in candidates:
        return base

    return None


def _local_name(
    tag: object,
) -> str:
    return str(
        tag or ""
    ).split(
        "}",
        1,
    )[-1]


def _candidate_texts(
    element: ET.Element,
) -> tuple[str, ...]:
    """Textos estructurados potencialmente útiles de un nodo."""

    values: list[str] = []

    own = str(
        element.text or ""
    ).strip()

    if own:
        values.append(
            own
        )

    for node in element.iter():
        if (
            node is element
            or _local_name(
                node.tag
            )
            != "VALUE"
        ):
            continue

        value = str(
            node.text or ""
        ).strip()

        if value:
            values.append(
                value
            )

    for node in element.iter():
        for raw_value in (
            node.attrib.values()
        ):
            value = str(
                raw_value or ""
            ).strip()

            if value:
                values.append(
                    value
                )

    return tuple(
        values
    )


def parse_tree_notice_identifiers(
    raw_xml: bytes,
) -> tuple[str, ...]:
    """Extrae CELEX desde nodos IDENTIFIER de Cellar.

    No escanea el XML completo mediante regex.
    """

    if not isinstance(
        raw_xml,
        (
            bytes,
            bytearray,
        ),
    ):
        raise TypeError(
            "Cellar tree notice debe recibirse como bytes"
        )

    try:
        root = ET.fromstring(
            bytes(
                raw_xml
            )
        )
    except ET.ParseError as exc:
        raise ValueError(
            "Cellar tree notice XML inválido"
        ) from exc

    result: set[str] = set()

    for node in root.iter():
        if _local_name(
            node.tag
        ) != "IDENTIFIER":
            continue

        for candidate in _candidate_texts(
            node
        ):
            try:
                celex = normalize_celex(
                    candidate
                )
            except ValueError:
                continue

            result.add(
                celex
            )

    return tuple(
        sorted(
            result
        )
    )


def parse_tree_notice_eli_uris(
    raw_xml: bytes,
) -> tuple[str, ...]:
    """Extrae URIs ELI explícitas de un tree notice."""

    if not isinstance(
        raw_xml,
        (
            bytes,
            bytearray,
        ),
    ):
        raise TypeError(
            "Cellar tree notice debe recibirse como bytes"
        )

    try:
        root = ET.fromstring(
            bytes(
                raw_xml
            )
        )
    except ET.ParseError as exc:
        raise ValueError(
            "Cellar tree notice XML inválido"
        ) from exc

    result: set[str] = set()

    prefixes = (
        "http://data.europa.eu/eli/",
        "https://data.europa.eu/eli/",
    )

    for node in root.iter():
        values = []

        text = str(
            node.text or ""
        ).strip()

        if text:
            values.append(
                text
            )

        values.extend(
            str(
                value or ""
            ).strip()
            for value
            in node.attrib.values()
        )

        for value in values:
            if value.startswith(
                prefixes
            ):
                result.add(
                    value
                )

    return tuple(
        sorted(
            result
        )
    )


# ============================================================
# DOCUMENT CANONICALIZATION
# ============================================================

from html.parser import HTMLParser
import json

from backend.knowledge import (
    KnowledgeItem,
    KnowledgeItemKind,
    KnowledgeItemReference,
    build_knowledge_item,
)


def _stable_json(
    value: object,
) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _normalize_space(
    value: object,
) -> str:
    return " ".join(
        str(
            value or ""
        ).split()
    )


def _parse_possible_date(
    value: object,
) -> date | None:
    raw = str(
        value or ""
    ).strip()

    if not raw:
        return None

    formats = (
        "%Y-%m-%d",
        "%Y%m%d",
    )

    from datetime import datetime

    for fmt in formats:
        try:
            return datetime.strptime(
                raw,
                fmt,
            ).date()
        except ValueError:
            pass

    return None


def _iter_primary_notice(
    element: ET.Element,
):
    """Recorre el notice principal sin entrar en notices relacionados.

    Cellar incluye gran cantidad de ``EMBEDDED_NOTICE`` de otras
    normas. Para título/fecha/canonical URI necesitamos únicamente
    la observación principal.
    """

    yield element

    for child in list(
        element
    ):
        if (
            _local_name(
                child.tag
            )
            == "EMBEDDED_NOTICE"
        ):
            continue

        yield from _iter_primary_notice(
            child
        )


def _node_values(
    element: ET.Element,
) -> tuple[str, ...]:
    values = []

    text = _normalize_space(
        element.text
    )

    if text:
        values.append(
            text
        )

    for node in element.iter():
        if (
            node is element
            or _local_name(
                node.tag
            )
            != "VALUE"
        ):
            continue

        value = _normalize_space(
            node.text
        )

        if value:
            values.append(
                value
            )

    return tuple(
        values
    )


def parse_tree_notice_primary_metadata(
    raw_xml: bytes,
    *,
    external_id: str,
) -> dict[str, object]:
    """Extrae metadata principal de un tree notice Cellar.

    No confunde títulos/fechas de normas relacionadas embebidas.
    """

    identifier = normalize_celex(
        external_id
    )

    if not isinstance(
        raw_xml,
        (
            bytes,
            bytearray,
        ),
    ):
        raise TypeError(
            "EUR-Lex metadata XML debe recibirse como bytes"
        )

    try:
        root = ET.fromstring(
            bytes(
                raw_xml
            )
        )
    except ET.ParseError as exc:
        raise ValueError(
            "EUR-Lex metadata XML inválido"
        ) from exc

    all_identifiers = (
        parse_tree_notice_identifiers(
            bytes(
                raw_xml
            )
        )
    )

    if identifier not in all_identifiers:
        raise ValueError(
            "EUR-Lex tree notice no contiene "
            f"la identidad esperada {identifier}"
        )

    primary_nodes = tuple(
        _iter_primary_notice(
            root
        )
    )

    title_candidates = []

    preferred_title_tags = {
        "EXPRESSION_TITLE",
        "WORK_TITLE",
    }

    fallback_title_tags = {
        "TITLE",
    }

    for node in primary_nodes:
        local = _local_name(
            node.tag
        )

        if local not in (
            preferred_title_tags
            | fallback_title_tags
        ):
            continue

        for value in _node_values(
            node
        ):
            if len(value) < 8:
                continue

            title_candidates.append(
                (
                    0
                    if local
                    in preferred_title_tags
                    else 1,
                    value,
                )
            )

    if not title_candidates:
        raise ValueError(
            "EUR-Lex tree notice no contiene "
            "título principal utilizable"
        )

    title_candidates.sort(
        key=lambda item: (
            item[0],
            -len(
                item[1]
            ),
            item[1],
        )
    )

    title = title_candidates[
        0
    ][1]

    published_on = None

    for node in primary_nodes:
        if (
            _local_name(
                node.tag
            )
            != "WORK_DATE_DOCUMENT"
        ):
            continue

        for value in _node_values(
            node
        ):
            parsed = (
                _parse_possible_date(
                    value
                )
            )

            if parsed is not None:
                published_on = parsed
                break

        if published_on is not None:
            break

    eli_uris: set[str] = set()

    for node in primary_nodes:
        values = []

        text = str(
            node.text or ""
        ).strip()

        if text:
            values.append(
                text
            )

        values.extend(
            str(
                raw or ""
            ).strip()
            for raw
            in node.attrib.values()
        )

        for value in values:
            if value.startswith(
                (
                    "http://data.europa.eu/eli/",
                    "https://data.europa.eu/eli/",
                )
            ):
                eli_uris.add(
                    value
                )

    original_eli = ""

    oj_candidates = sorted(
        uri
        for uri in eli_uris
        if uri.rstrip(
            "/"
        ).endswith(
            "/oj"
        )
    )

    if oj_candidates:
        original_eli = (
            oj_candidates[0]
        )

    return {
        "title": title,
        "published_on": published_on,
        "identifiers": (
            all_identifiers
        ),
        "eli_uris": tuple(
            sorted(
                eli_uris
            )
        ),
        "original_eli": (
            original_eli
        ),
    }


class _EurLexTextExtractor(
    HTMLParser
):
    """Extracción conservadora de texto visible XHTML/HTML."""

    _IGNORED = {
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
        "p",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
        "ol",
    }

    def __init__(
        self,
    ) -> None:
        super().__init__(
            convert_charrefs=True
        )

        self._ignored_depth = 0
        self._parts: list[
            str
        ] = []

    def handle_starttag(
        self,
        tag,
        attrs,
    ):
        name = str(
            tag or ""
        ).lower()

        if name in self._IGNORED:
            self._ignored_depth += 1
            return

        if (
            self._ignored_depth == 0
            and name
            in self._BLOCK_TAGS
        ):
            self._parts.append(
                "\n"
            )

    def handle_endtag(
        self,
        tag,
    ):
        name = str(
            tag or ""
        ).lower()

        if name in self._IGNORED:
            if self._ignored_depth:
                self._ignored_depth -= 1
            return

        if (
            self._ignored_depth == 0
            and name
            in self._BLOCK_TAGS
        ):
            self._parts.append(
                "\n"
            )

    def handle_data(
        self,
        data,
    ):
        if self._ignored_depth:
            return

        value = _normalize_space(
            data
        )

        if value:
            self._parts.append(
                value
            )

    def text(
        self,
    ) -> str:
        raw = "".join(
            self._parts
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


def parse_eurlex_document_text(
    raw_xhtml: bytes,
) -> str:
    """Convierte XHTML/HTML oficial en texto canónico."""

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

    parser = _EurLexTextExtractor()

    try:
        parser.feed(
            decoded
        )
        parser.close()
    except Exception as exc:
        raise ValueError(
            "EUR-Lex XHTML no pudo procesarse"
        ) from exc

    content = parser.text()

    if not content:
        raise ValueError(
            "EUR-Lex no produjo contenido textual"
        )

    return content


def build_consolidated_eli_uri(
    original_eli: str,
    consolidated_celex: str,
) -> str:
    """Deriva URI ELI legible para una revisión consolidada."""

    base = str(
        original_eli or ""
    ).strip()

    if not base:
        return ""

    revision = (
        consolidated_revision_date(
            consolidated_celex
        )
    )

    if revision is None:
        return base

    normalized = base.rstrip(
        "/"
    )

    if normalized.endswith(
        "/oj"
    ):
        normalized = normalized[
            :-3
        ]

    return (
        normalized.rstrip(
            "/"
        )
        + "/"
        + revision.isoformat()
    )


def _payload_bytes(
    payload,
    key,
) -> bytes:
    value = payload.get(
        key
    )

    if not isinstance(
        value,
        (
            bytes,
            bytearray,
        ),
    ):
        raise TypeError(
            "EUR-Lex payload requiere bytes en "
            f"{key}"
        )

    return bytes(
        value
    )


def _payload_id(
    payload,
) -> str:
    return normalize_celex(
        str(
            payload.get(
                "id"
            )
            or ""
        )
    )


def parse_eurlex_original_document_payload(
    reference: KnowledgeItemReference,
    payload,
) -> KnowledgeItem:
    """Canonicaliza un acto EUR-Lex original."""

    payload_id = _payload_id(
        payload
    )

    if (
        payload_id
        != reference.external_id
    ):
        raise ValueError(
            "EUR-Lex payload cambió external_id"
        )

    metadata_xml = _payload_bytes(
        payload,
        "metadata_xml",
    )

    content_xhtml = _payload_bytes(
        payload,
        "content_xhtml",
    )

    metadata = (
        parse_tree_notice_primary_metadata(
            metadata_xml,
            external_id=payload_id,
        )
    )

    content_text = (
        parse_eurlex_document_text(
            content_xhtml
        )
    )

    canonical_uri = str(
        metadata[
            "original_eli"
        ]
        or reference.canonical_uri
        or payload.get(
            "content_final_url"
        )
        or ""
    ).strip()

    knowledge_metadata = {
        "provider": "EUR_LEX",
        "celex_sector": (
            payload_id[0]
        ),
        "content_transport": (
            payload.get(
                "content_transport"
            )
            or ""
        ),
        "metadata_final_url": (
            payload.get(
                "metadata_final_url"
            )
            or ""
        ),
        "content_final_url": (
            payload.get(
                "content_final_url"
            )
            or ""
        ),
        "celex_identifiers_json": (
            _stable_json(
                metadata[
                    "identifiers"
                ]
            )
        ),
        "eli_uris_json": (
            _stable_json(
                metadata[
                    "eli_uris"
                ]
            )
        ),
    }

    return build_knowledge_item(
        source_key=(
            EUR_LEX_SOURCE_KEY
        ),
        external_id=payload_id,
        title=str(
            metadata[
                "title"
            ]
        ),
        item_kind=(
            KnowledgeItemKind.LEGISLATION
        ),
        content_text=content_text,
        canonical_uri=canonical_uri,
        source_revision=payload_id,
        published_on=metadata[
            "published_on"
        ],
        language="es",
        metadata=knowledge_metadata,
    )


def parse_eurlex_consolidated_document_payload(
    reference: KnowledgeItemReference,
    payload,
) -> KnowledgeItem:
    """Canonicaliza la última revisión española utilizable."""

    payload_id = _payload_id(
        payload
    )

    if (
        payload_id
        != reference.external_id
    ):
        raise ValueError(
            "EUR-Lex Consolidado payload "
            "cambió external_id"
        )

    consolidated = normalize_celex(
        str(
            payload.get(
                "consolidated_celex"
            )
            or ""
        )
    )

    if not is_consolidated_celex(
        consolidated
    ):
        raise ValueError(
            "EUR-Lex Consolidado requiere "
            "source revision sector 0"
        )

    metadata_xml = _payload_bytes(
        payload,
        "metadata_xml",
    )

    content_xhtml = _payload_bytes(
        payload,
        "content_xhtml",
    )

    metadata = (
        parse_tree_notice_primary_metadata(
            metadata_xml,
            external_id=payload_id,
        )
    )

    content_text = (
        parse_eurlex_document_text(
            content_xhtml
        )
    )

    canonical_uri = (
        build_consolidated_eli_uri(
            str(
                metadata[
                    "original_eli"
                ]
            ),
            consolidated,
        )
    )

    if not canonical_uri:
        canonical_uri = str(
            payload.get(
                "content_final_url"
            )
            or reference.canonical_uri
            or ""
        ).strip()

    skipped = tuple(
        payload.get(
            "skipped_unavailable_revisions"
        )
        or ()
    )

    knowledge_metadata = {
        "provider": (
            "EUR_LEX_CONSOLIDATED"
        ),
        "celex_sector": (
            payload_id[0]
        ),
        "consolidated_celex": (
            consolidated
        ),
        "content_transport": (
            payload.get(
                "content_transport"
            )
            or ""
        ),
        "metadata_final_url": (
            payload.get(
                "metadata_final_url"
            )
            or ""
        ),
        "content_final_url": (
            payload.get(
                "content_final_url"
            )
            or ""
        ),
        "celex_identifiers_json": (
            _stable_json(
                metadata[
                    "identifiers"
                ]
            )
        ),
        "eli_uris_json": (
            _stable_json(
                metadata[
                    "eli_uris"
                ]
            )
        ),
        "skipped_unavailable_revisions_json": (
            _stable_json(
                skipped
            )
        ),
    }

    return build_knowledge_item(
        source_key=(
            EUR_LEX_CONSOLIDATED_SOURCE_KEY
        ),
        external_id=payload_id,
        title=str(
            metadata[
                "title"
            ]
        ),
        item_kind=(
            KnowledgeItemKind.LEGISLATION
        ),
        content_text=content_text,
        canonical_uri=canonical_uri,
        source_revision=(
            consolidated
        ),
        published_on=metadata[
            "published_on"
        ],
        language="es",
        metadata=knowledge_metadata,
    )
