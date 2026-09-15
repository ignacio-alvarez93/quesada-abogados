"""Normalización de BOE Legislación Consolidada hacia Knowledge.

Responsabilidades:

- discovery de normas consolidadas;
- validación de metadatos;
- extracción del texto consolidado vigente;
- preservación resumida de versiones y relaciones jurídicas.

No realiza HTTP, persistencia, UI ni procesamiento IA.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
import json
from typing import Any
import xml.etree.ElementTree as ET

from backend.knowledge import (
    KnowledgeItem,
    KnowledgeItemKind,
    KnowledgeItemReference,
    build_knowledge_item,
)


SOURCE_KEY = "BOE_CONSOLIDATED"


def _required_text(
    payload: Mapping[str, object],
    key: str,
) -> str:
    value = str(
        payload.get(key) or ""
    ).strip()

    if not value:
        raise ValueError(
            "BOE Consolidado requiere campo "
            f"no vacío: {key}"
        )

    return value


def _nodes(
    value: object,
    *,
    name: str,
) -> tuple[
    Mapping[str, Any],
    ...,
]:
    if value is None:
        return ()

    if isinstance(
        value,
        Mapping,
    ):
        return (value,)

    if isinstance(
        value,
        list,
    ):
        result = []

        for item in value:
            if not isinstance(
                item,
                Mapping,
            ):
                raise TypeError(
                    "BOE Consolidado nodo "
                    f"{name} debe contener mappings"
                )

            result.append(
                item
            )

        return tuple(
            result
        )

    raise TypeError(
        "BOE Consolidado nodo "
        f"{name} debe ser mapping o lista"
    )


def _single_data_mapping(
    payload: Mapping[str, object],
    *,
    name: str,
) -> Mapping[str, Any]:
    data = _nodes(
        payload.get("data"),
        name=f"{name}.data",
    )

    if len(data) != 1:
        raise ValueError(
            "BOE Consolidado "
            f"{name} requiere exactamente "
            "un elemento data"
        )

    return data[0]


def _parse_yyyymmdd(
    raw: object,
    *,
    field_name: str,
) -> date:
    value = str(
        raw or ""
    ).strip()

    if (
        len(value) != 8
        or not value.isdigit()
    ):
        raise ValueError(
            f"{field_name} debe usar AAAAMMDD"
        )

    try:
        return date(
            int(value[:4]),
            int(value[4:6]),
            int(value[6:8]),
        )
    except ValueError as exc:
        raise ValueError(
            f"{field_name} no es fecha válida"
        ) from exc


def _stable_json(
    value: object,
) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    )


def _local_xml_name(
    tag: object,
) -> str:
    return str(
        tag or ""
    ).split(
        "}",
        1,
    )[-1]


def _clean_xml_text(
    element: object,
) -> str:
    if element is None:
        return ""

    return " ".join(
        part.strip()
        for part in element.itertext()
        if part and part.strip()
    )


def parse_boe_consolidated_discovery_payload(
    payload: Mapping[str, object],
) -> tuple[
    KnowledgeItemReference,
    ...,
]:
    """Extrae referencias desde el listado de normas consolidadas."""

    data = _nodes(
        payload.get("data"),
        name="discovery.data",
    )

    references: list[
        KnowledgeItemReference
    ] = []

    seen_ids: set[str] = set()

    for raw_item in data:
        external_id = _required_text(
            raw_item,
            "identificador",
        )

        if external_id in seen_ids:
            raise ValueError(
                "BOE Consolidado discovery "
                "contiene id duplicado: "
                f"{external_id}"
            )

        seen_ids.add(
            external_id
        )

        canonical_uri = str(
            raw_item.get(
                "url_eli"
            )
            or raw_item.get(
                "url_html_consolidada"
            )
            or ""
        ).strip()

        references.append(
            KnowledgeItemReference(
                source_key=SOURCE_KEY,
                external_id=external_id,
                canonical_uri=canonical_uri,
            )
        )

    return tuple(
        references
    )


def parse_boe_consolidated_current_text(
    external_id: str,
    raw_xml: bytes,
) -> tuple[
    str,
    dict[str, object],
]:
    """Extrae únicamente la versión vigente de cada bloque.

    El XML de legislación consolidada conserva todas las versiones
    históricas dentro de cada bloque. Para ``content_text`` se utiliza
    la última versión de cada bloque en orden documental.

    El histórico no se pierde conceptualmente: se devuelve un
    ``version_manifest`` compacto para metadata y una futura capa
    estructurada de bloques/versiones.
    """

    expected_id = str(
        external_id or ""
    ).strip()

    if not expected_id:
        raise ValueError(
            "BOE Consolidado XML "
            "requiere external_id"
        )

    if not isinstance(
        raw_xml,
        (bytes, bytearray),
    ):
        raise TypeError(
            "BOE Consolidado texto XML "
            "debe recibirse como bytes"
        )

    try:
        root = ET.fromstring(
            bytes(
                raw_xml
            )
        )
    except ET.ParseError as exc:
        raise ValueError(
            "BOE Consolidado devolvió "
            "texto XML no válido"
        ) from exc

    blocks = [
        node
        for node in root.iter()
        if _local_xml_name(
            node.tag
        ) == "bloque"
    ]

    if not blocks:
        raise ValueError(
            "BOE Consolidado texto XML "
            "no contiene bloques"
        )

    current_parts: list[str] = []
    manifest: list[
        dict[str, object]
    ] = []

    total_versions = 0

    for position, block in enumerate(
        blocks,
        start=1,
    ):
        versions = [
            node
            for node in list(
                block
            )
            if _local_xml_name(
                node.tag
            ) == "version"
        ]

        if not versions:
            continue

        total_versions += len(
            versions
        )

        current = versions[-1]

        current_text = (
            _clean_xml_text(
                current
            )
        )

        if current_text:
            current_parts.append(
                current_text
            )

        block_id = str(
            block.attrib.get(
                "id"
            )
            or ""
        ).strip()

        version_entries = []

        for version in versions:
            version_entries.append(
                {
                    str(key): str(
                        value
                    )
                    for key, value
                    in sorted(
                        version.attrib.items()
                    )
                }
            )

        manifest.append(
            {
                "position": position,
                "block_id": block_id,
                "version_count": len(
                    versions
                ),
                "versions": (
                    version_entries
                ),
            }
        )

    content_text = "\n\n".join(
        current_parts
    ).strip()

    if not content_text:
        raise ValueError(
            "BOE Consolidado no produjo "
            "texto vigente"
        )

    return (
        content_text,
        {
            "block_count": len(
                blocks
            ),
            "version_count": (
                total_versions
            ),
            "version_manifest": (
                manifest
            ),
        },
    )


def _parse_subjects(
    analysis: Mapping[str, object],
) -> list[
    dict[str, str]
]:
    result = []

    for wrapper in _nodes(
        analysis.get(
            "materias"
        ),
        name="analisis.materias",
    ):
        materia = wrapper.get(
            "materia"
        )

        if not isinstance(
            materia,
            Mapping,
        ):
            continue

        result.append(
            {
                "codigo": str(
                    materia.get(
                        "codigo"
                    )
                    or ""
                ).strip(),
                "texto": str(
                    materia.get(
                        "texto"
                    )
                    or ""
                ).strip(),
            }
        )

    return result


def _parse_relations(
    analysis: Mapping[str, object],
) -> list[
    dict[str, str]
]:
    references = analysis.get(
        "referencias"
    )

    if not isinstance(
        references,
        Mapping,
    ):
        return []

    result = []

    for (
        direction,
        wrapper_name,
    ) in (
        (
            "anteriores",
            "anterior",
        ),
        (
            "posteriores",
            "posterior",
        ),
    ):
        for wrapper in _nodes(
            references.get(
                direction
            ),
            name=(
                "analisis.referencias."
                f"{direction}"
            ),
        ):
            for relation in _nodes(
                wrapper.get(
                    wrapper_name
                ),
                name=wrapper_name,
            ):
                relation_type = (
                    relation.get(
                        "relacion"
                    )
                )

                if not isinstance(
                    relation_type,
                    Mapping,
                ):
                    relation_type = {}

                result.append(
                    {
                        "direction": (
                            direction
                        ),
                        "target_id": str(
                            relation.get(
                                "id_norma"
                            )
                            or ""
                        ).strip(),
                        "relation_code": str(
                            relation_type.get(
                                "codigo"
                            )
                            or ""
                        ).strip(),
                        "relation_text": str(
                            relation_type.get(
                                "texto"
                            )
                            or ""
                        ).strip(),
                        "description": str(
                            relation.get(
                                "texto"
                            )
                            or ""
                        ).strip(),
                    }
                )

    return result


def _parse_index(
    payload: Mapping[str, object],
) -> list[
    dict[str, str]
]:
    data = _single_data_mapping(
        payload,
        name="indice",
    )

    result = []

    for block in _nodes(
        data.get(
            "bloque"
        ),
        name="indice.bloque",
    ):
        result.append(
            {
                "id": str(
                    block.get(
                        "id"
                    )
                    or ""
                ).strip(),
                "title": str(
                    block.get(
                        "titulo"
                    )
                    or ""
                ).strip(),
                "updated_on": str(
                    block.get(
                        "fecha_actualizacion"
                    )
                    or ""
                ).strip(),
                "url": str(
                    block.get(
                        "url"
                    )
                    or ""
                ).strip(),
            }
        )

    return result


def _nested_descriptor(
    metadata: Mapping[str, object],
    key: str,
) -> tuple[
    str,
    str,
]:
    value = metadata.get(
        key
    )

    if not isinstance(
        value,
        Mapping,
    ):
        return "", ""

    return (
        str(
            value.get(
                "codigo"
            )
            or ""
        ).strip(),
        str(
            value.get(
                "texto"
            )
            or ""
        ).strip(),
    )


def parse_boe_consolidated_document_payload(
    reference: KnowledgeItemReference,
    payload: Mapping[str, object],
) -> KnowledgeItem:
    """Convierte una norma consolidada en KnowledgeItem."""

    payload_id = _required_text(
        payload,
        "id",
    )

    if payload_id != reference.external_id:
        raise ValueError(
            "BOE Consolidado payload "
            "no coincide con referencia"
        )

    metadata_payload = payload.get(
        "metadata"
    )
    analysis_payload = payload.get(
        "analysis"
    )
    index_payload = payload.get(
        "index"
    )
    raw_text_xml = payload.get(
        "text_xml"
    )

    if not isinstance(
        metadata_payload,
        Mapping,
    ):
        raise TypeError(
            "BOE Consolidado metadata "
            "debe ser mapping"
        )

    if not isinstance(
        analysis_payload,
        Mapping,
    ):
        raise TypeError(
            "BOE Consolidado analysis "
            "debe ser mapping"
        )

    if not isinstance(
        index_payload,
        Mapping,
    ):
        raise TypeError(
            "BOE Consolidado index "
            "debe ser mapping"
        )

    if not isinstance(
        raw_text_xml,
        (bytes, bytearray),
    ):
        raise TypeError(
            "BOE Consolidado text_xml "
            "debe ser bytes"
        )

    metadata = _single_data_mapping(
        metadata_payload,
        name="metadatos",
    )

    metadata_id = _required_text(
        metadata,
        "identificador",
    )

    if metadata_id != reference.external_id:
        raise ValueError(
            "BOE Consolidado metadatos "
            "cambiaron identificador"
        )

    title = _required_text(
        metadata,
        "titulo",
    )

    source_revision = (
        _required_text(
            metadata,
            "fecha_actualizacion",
        )
    )

    published_on = _parse_yyyymmdd(
        metadata.get(
            "fecha_publicacion"
        ),
        field_name=(
            "BOE Consolidado "
            "fecha_publicacion"
        ),
    )

    content_text, text_model = (
        parse_boe_consolidated_current_text(
            reference.external_id,
            bytes(
                raw_text_xml
            ),
        )
    )

    analysis = (
        _single_data_mapping(
            analysis_payload,
            name="analisis",
        )
    )

    subjects = _parse_subjects(
        analysis
    )

    relations = _parse_relations(
        analysis
    )

    block_index = _parse_index(
        index_payload
    )

    rango_code, rango_text = (
        _nested_descriptor(
            metadata,
            "rango",
        )
    )

    scope_code, scope_text = (
        _nested_descriptor(
            metadata,
            "ambito",
        )
    )

    (
        department_code,
        department_text,
    ) = _nested_descriptor(
        metadata,
        "departamento",
    )

    (
        consolidation_code,
        consolidation_text,
    ) = _nested_descriptor(
        metadata,
        "estado_consolidacion",
    )

    canonical_uri = str(
        metadata.get(
            "url_eli"
        )
        or reference.canonical_uri
        or metadata.get(
            "url_html_consolidada"
        )
        or ""
    ).strip()

    knowledge_metadata = {
        "provider": (
            "BOE_CONSOLIDATED"
        ),
        "numero_oficial": (
            metadata.get(
                "numero_oficial"
            )
            or ""
        ),
        "fecha_disposicion": (
            metadata.get(
                "fecha_disposicion"
            )
            or ""
        ),
        "fecha_vigencia": (
            metadata.get(
                "fecha_vigencia"
            )
            or ""
        ),
        "vigencia_agotada": (
            metadata.get(
                "vigencia_agotada"
            )
            or ""
        ),
        "estatus_derogacion": (
            metadata.get(
                "estatus_derogacion"
            )
            or ""
        ),
        "estatus_anulacion": (
            metadata.get(
                "estatus_anulacion"
            )
            or ""
        ),
        "rango_codigo": rango_code,
        "rango_texto": rango_text,
        "ambito_codigo": scope_code,
        "ambito_texto": scope_text,
        "departamento_codigo": (
            department_code
        ),
        "departamento_texto": (
            department_text
        ),
        "estado_consolidacion_codigo": (
            consolidation_code
        ),
        "estado_consolidacion_texto": (
            consolidation_text
        ),
        "url_html_consolidada": (
            metadata.get(
                "url_html_consolidada"
            )
            or ""
        ),
        "block_count": (
            text_model[
                "block_count"
            ]
        ),
        "version_count": (
            text_model[
                "version_count"
            ]
        ),
        "subjects_json": (
            _stable_json(
                subjects
            )
        ),
        "legal_relations_json": (
            _stable_json(
                relations
            )
        ),
        "block_index_json": (
            _stable_json(
                block_index
            )
        ),
        "version_manifest_json": (
            _stable_json(
                text_model[
                    "version_manifest"
                ]
            )
        ),
    }

    return build_knowledge_item(
        source_key=SOURCE_KEY,
        external_id=(
            reference.external_id
        ),
        title=title,
        item_kind=(
            KnowledgeItemKind.LEGISLATION
        ),
        content_text=content_text,
        canonical_uri=canonical_uri,
        source_revision=source_revision,
        published_on=published_on,
        language="es",
        metadata=knowledge_metadata,
    )
