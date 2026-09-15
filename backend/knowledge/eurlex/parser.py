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
