"""Normalización del BOE oficial hacia Knowledge.

Este parser modela la estructura JSON documentada por la AEBOE para:

    /datosabiertos/api/boe/sumario/{fecha}

No realiza HTTP, persistencia, UI ni procesamiento IA.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from backend.knowledge import (
    KnowledgeItem,
    KnowledgeItemKind,
    KnowledgeItemReference,
    build_knowledge_item,
)


def _required_text(
    payload: Mapping[str, object],
    key: str,
) -> str:
    value = str(payload.get(key) or "").strip()

    if not value:
        raise ValueError(
            f"BOE payload requiere campo no vacío: {key}"
        )

    return value


def _nodes(
    value: object,
    *,
    name: str,
) -> tuple[Mapping[str, Any], ...]:
    """Normaliza nodo JSON BOE singular/lista a secuencia estable."""

    if value is None:
        return ()

    if isinstance(value, Mapping):
        return (value,)

    if isinstance(value, list):
        result = []

        for item in value:
            if not isinstance(item, Mapping):
                raise TypeError(
                    f"BOE nodo {name} debe contener mappings"
                )
            result.append(item)

        return tuple(result)

    raise TypeError(
        f"BOE nodo {name} debe ser mapping o lista"
    )


def _summary(
    payload: Mapping[str, object],
) -> Mapping[str, Any]:
    data = payload.get("data")

    if not isinstance(data, Mapping):
        raise ValueError(
            "BOE payload requiere objeto 'data'"
        )

    summary = data.get("sumario")

    if not isinstance(summary, Mapping):
        raise ValueError(
            "BOE payload requiere objeto 'data.sumario'"
        )

    return summary


def parse_boe_publication_date(
    payload: Mapping[str, object],
) -> date:
    """Extrae la fecha oficial del sumario BOE."""

    summary = _summary(payload)

    metadata = summary.get("metadatos")

    if not isinstance(metadata, Mapping):
        raise ValueError(
            "BOE sumario requiere objeto 'metadatos'"
        )

    publication = str(
        metadata.get("publicacion") or ""
    ).strip()

    if publication != "BOE":
        raise ValueError(
            "BOE sumario tiene publicación inesperada"
        )

    raw_date = str(
        metadata.get("fecha_publicacion") or ""
    ).strip()

    if len(raw_date) != 8 or not raw_date.isdigit():
        raise ValueError(
            "BOE fecha_publicacion debe usar AAAAMMDD"
        )

    try:
        return date(
            int(raw_date[0:4]),
            int(raw_date[4:6]),
            int(raw_date[6:8]),
        )
    except ValueError as exc:
        raise ValueError(
            "BOE fecha_publicacion no es una fecha válida"
        ) from exc


def _iter_summary_items(
    payload: Mapping[str, object],
):
    """Recorre items con independencia de epígrafe opcional."""

    summary = _summary(payload)

    for diario in _nodes(
        summary.get("diario"),
        name="diario",
    ):
        for section in _nodes(
            diario.get("seccion"),
            name="seccion",
        ):
            for department in _nodes(
                section.get("departamento"),
                name="departamento",
            ):
                # Algunas secciones pueden publicar items
                # directamente bajo departamento.
                for item in _nodes(
                    department.get("item"),
                    name="item",
                ):
                    yield item

                for heading in _nodes(
                    department.get("epigrafe"),
                    name="epigrafe",
                ):
                    for item in _nodes(
                        heading.get("item"),
                        name="item",
                    ):
                        yield item


def parse_boe_discovery_payload(
    payload: Mapping[str, object],
) -> tuple[KnowledgeItemReference, ...]:
    """Extrae referencias BOE-A desde el sumario oficial."""

    # Valida primero metadatos fundamentales.
    parse_boe_publication_date(payload)

    references: list[KnowledgeItemReference] = []
    seen_ids: set[str] = set()

    for raw_item in _iter_summary_items(payload):
        external_id = _required_text(
            raw_item,
            "identificador",
        )

        if external_id in seen_ids:
            raise ValueError(
                f"BOE discovery contiene id duplicado: {external_id}"
            )

        seen_ids.add(external_id)

        canonical_uri = str(
            raw_item.get("url_html")
            or raw_item.get("url_xml")
            or ""
        ).strip()

        references.append(
            KnowledgeItemReference(
                source_key="BOE",
                external_id=external_id,
                canonical_uri=canonical_uri,
            )
        )

    return tuple(references)


def parse_boe_document_payload(
    reference: KnowledgeItemReference,
    payload: Mapping[str, object],
) -> KnowledgeItem:
    """Convierte documento obtenido del BOE a KnowledgeItem.

    La publicación diaria se conserva de forma neutral como
    OFFICIAL_PUBLICATION. Una capa posterior podrá clasificarla como
    legislación, resolución, anuncio u otra naturaleza sin alterar
    la provenance original.
    """

    payload_external_id = _required_text(
        payload,
        "id",
    )

    if payload_external_id != reference.external_id:
        raise ValueError(
            "BOE document payload no coincide con "
            "la referencia solicitada"
        )

    title = _required_text(
        payload,
        "title",
    )
    content_text = _required_text(
        payload,
        "text",
    )
    published_raw = _required_text(
        payload,
        "published_on",
    )

    try:
        published_on = date.fromisoformat(
            published_raw
        )
    except ValueError as exc:
        raise ValueError(
            "BOE published_on debe tener formato ISO YYYY-MM-DD"
        ) from exc

    metadata = payload.get("metadata")

    if metadata is None:
        metadata = {}

    if not isinstance(metadata, Mapping):
        raise TypeError(
            "BOE document metadata debe ser mapping"
        )

    canonical_uri = str(
        payload.get("url")
        or reference.canonical_uri
        or ""
    ).strip()

    return build_knowledge_item(
        source_key="BOE",
        external_id=reference.external_id,
        title=title,
        item_kind=KnowledgeItemKind.OFFICIAL_PUBLICATION,
        content_text=content_text,
        canonical_uri=canonical_uri,
        source_revision=str(
            payload.get("source_revision") or ""
        ),
        published_on=published_on,
        language=str(
            payload.get("language") or "es"
        ),
        metadata=metadata,
    )


def _local_xml_name(tag: object) -> str:
    value = str(tag or "")
    return value.split("}", 1)[-1]


def _xml_clean_text(element: object) -> str:
    if element is None:
        return ""

    return " ".join(
        part.strip()
        for part in element.itertext()
        if part and part.strip()
    )


def _xml_direct_child(
    parent: object,
    name: str,
):
    if parent is None:
        return None

    for child in list(parent):
        if _local_xml_name(child.tag) == name:
            return child

    return None


def _xml_metadata_field(
    metadata: object,
    name: str,
) -> tuple[str, dict[str, str]]:
    node = _xml_direct_child(
        metadata,
        name,
    )

    if node is None:
        return "", {}

    return (
        _xml_clean_text(node),
        {
            str(key): str(value)
            for key, value in node.attrib.items()
        },
    )


def parse_boe_xml_document_payload(
    external_id: str,
    raw_xml: bytes,
) -> dict[str, object]:
    """Convierte el XML oficial BOE en payload nativo normalizado.

    Esta función conserva únicamente estructura BOE.
    La conversión final a KnowledgeItem sigue correspondiendo
    a ``parse_boe_document_payload``.
    """

    import xml.etree.ElementTree as ET

    expected_id = str(
        external_id or ""
    ).strip()

    if not expected_id:
        raise ValueError(
            "BOE XML requiere external_id esperado"
        )

    if not isinstance(
        raw_xml,
        (bytes, bytearray),
    ):
        raise TypeError(
            "BOE XML debe recibirse como bytes"
        )

    try:
        root = ET.fromstring(
            bytes(raw_xml)
        )
    except ET.ParseError as exc:
        raise ValueError(
            "BOE devolvió XML no válido"
        ) from exc

    if _local_xml_name(root.tag) != "documento":
        raise ValueError(
            "BOE XML requiere raíz 'documento'"
        )

    metadata_node = _xml_direct_child(
        root,
        "metadatos",
    )

    if metadata_node is None:
        raise ValueError(
            "BOE XML requiere nodo 'metadatos'"
        )

    identifier, _ = _xml_metadata_field(
        metadata_node,
        "identificador",
    )

    if not identifier:
        raise ValueError(
            "BOE XML requiere identificador"
        )

    if identifier != expected_id:
        raise ValueError(
            "BOE XML identificador no coincide "
            "con referencia solicitada"
        )

    title, _ = _xml_metadata_field(
        metadata_node,
        "titulo",
    )
    publication_raw, _ = _xml_metadata_field(
        metadata_node,
        "fecha_publicacion",
    )

    if len(publication_raw) != 8 or not publication_raw.isdigit():
        raise ValueError(
            "BOE XML fecha_publicacion debe usar AAAAMMDD"
        )

    try:
        publication_date = date(
            int(publication_raw[0:4]),
            int(publication_raw[4:6]),
            int(publication_raw[6:8]),
        )
    except ValueError as exc:
        raise ValueError(
            "BOE XML fecha_publicacion no es válida"
        ) from exc

    text_node = _xml_direct_child(
        root,
        "texto",
    )

    if text_node is None:
        raise ValueError(
            "BOE XML requiere nodo 'texto'"
        )

    # Conservamos bloques en lugar de aplanarlo todo en una línea.
    text_blocks: list[str] = []

    for child in list(text_node):
        block = _xml_clean_text(child)

        if block:
            text_blocks.append(block)

    if text_blocks:
        content_text = "\n\n".join(
            text_blocks
        )
    else:
        content_text = _xml_clean_text(
            text_node
        )

    if not content_text:
        raise ValueError(
            "BOE XML no contiene texto utilizable"
        )

    fields = (
        "origen_legislativo",
        "departamento",
        "rango",
        "fecha_disposicion",
        "numero_oficial",
        "diario_numero",
        "seccion",
        "subseccion",
        "pagina_inicial",
        "pagina_final",
        "estatus_legislativo",
        "fecha_vigencia",
        "estatus_derogacion",
        "fecha_derogacion",
        "judicialmente_anulada",
        "fecha_anulacion",
        "vigencia_agotada",
        "estado_consolidacion",
        "url_pdf",
        "url_eli",
        "url_epub",
    )

    normalized_metadata: dict[str, str] = {}

    for field_name in fields:
        value, attributes = _xml_metadata_field(
            metadata_node,
            field_name,
        )

        if value:
            normalized_metadata[
                field_name
            ] = value

        for attribute_name, attribute_value in attributes.items():
            normalized_metadata[
                f"{field_name}_{attribute_name}"
            ] = attribute_value

    normalized_metadata[
        "boe_xml_url"
    ] = (
        "https://www.boe.es/diario_boe/"
        f"xml.php?id={identifier}"
    )

    normalized_metadata[
        "boe_html_url"
    ] = (
        "https://www.boe.es/diario_boe/"
        f"txt.php?id={identifier}"
    )

    updated_at = str(
        root.attrib.get(
            "fecha_actualizacion",
            "",
        )
    ).strip()

    if updated_at:
        normalized_metadata[
            "boe_source_updated_at"
        ] = updated_at

    eli_uri = normalized_metadata.get(
        "url_eli",
        "",
    )

    canonical_uri = (
        eli_uri
        or (
            "https://www.boe.es/diario_boe/"
            f"txt.php?id={identifier}"
        )
    )

    return {
        "id": identifier,
        "title": title,
        "text": content_text,
        "published_on": publication_date.isoformat(),
        "url": canonical_uri,
        "source_revision": updated_at,
        "language": "es",
        "metadata": normalized_metadata,
    }
