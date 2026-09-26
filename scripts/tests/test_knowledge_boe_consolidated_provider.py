import json

from backend.knowledge import (
    KnowledgeAuthority,
    KnowledgeItemKind,
    KnowledgeSourceKind,
    get_knowledge_source,
)
from backend.knowledge.boe_consolidated.parser import (
    parse_boe_consolidated_current_text,
)
from backend.knowledge.boe_consolidated.provider import (
    BoeConsolidatedProvider,
)


TARGET = "BOE-A-2024-24099"


TEXT_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<response>
  <status>
    <code>200</code>
    <text>ok</text>
  </status>
  <data>
    <texto>
      <bloque id="a1">
        <version
          id_norma="BOE-A-2024-24099"
          fecha_publicacion="20241120"
          fecha_vigencia="20250520"
        >
          <p>Articulo 1. Texto vigente sin cambios.</p>
        </version>
      </bloque>
      <bloque id="a2">
        <version
          id_norma="BOE-A-2024-24099"
          fecha_publicacion="20241120"
          fecha_vigencia="20250520"
        >
          <p>Articulo 2. Texto antiguo.</p>
        </version>
        <version
          id_norma="BOE-A-2026-8284"
          fecha_publicacion="20260415"
          fecha_vigencia="20260416"
        >
          <p>Articulo 2. Texto vigente reformado.</p>
        </version>
      </bloque>
    </texto>
  </data>
</response>
"""


def _discovery_payload():
    return {
        "status": {
            "code": "200",
            "text": "ok",
        },
        "data": [
            {
                "identificador": TARGET,
                "titulo": (
                    "Real Decreto 1155/2024"
                ),
                "fecha_actualizacion": (
                    "20260605T080848Z"
                ),
                "url_eli": (
                    "https://www.boe.es/eli/"
                    "es/rd/2024/11/19/1155"
                ),
                "url_html_consolidada": (
                    "https://www.boe.es/"
                    "buscar/act.php?id="
                    + TARGET
                ),
            }
        ],
    }


def _metadata_payload():
    return {
        "status": {
            "code": "200",
            "text": "ok",
        },
        "data": [
            {
                "identificador": TARGET,
                "titulo": (
                    "Real Decreto 1155/2024, "
                    "de 19 de noviembre"
                ),
                "fecha_actualizacion": (
                    "20260605T080848Z"
                ),
                "fecha_disposicion": (
                    "20241119"
                ),
                "fecha_publicacion": (
                    "20241120"
                ),
                "fecha_vigencia": (
                    "20250520"
                ),
                "numero_oficial": (
                    "1155/2024"
                ),
                "vigencia_agotada": "N",
                "estatus_derogacion": "N",
                "estatus_anulacion": "N",
                "rango": {
                    "codigo": "1340",
                    "texto": "Real Decreto",
                },
                "ambito": {
                    "codigo": "1",
                    "texto": "Estatal",
                },
                "departamento": {
                    "codigo": "9585",
                    "texto": (
                        "Ministerio de la "
                        "Presidencia"
                    ),
                },
                "estado_consolidacion": {
                    "codigo": "3",
                    "texto": "Finalizado",
                },
                "url_eli": (
                    "https://www.boe.es/eli/"
                    "es/rd/2024/11/19/1155"
                ),
                "url_html_consolidada": (
                    "https://www.boe.es/"
                    "buscar/act.php?id="
                    + TARGET
                ),
            }
        ],
    }


def _analysis_payload():
    return {
        "status": {
            "code": "200",
            "text": "ok",
        },
        "data": [
            {
                "materias": [
                    {
                        "materia": {
                            "codigo": "7155",
                            "texto": "Visados",
                        }
                    }
                ],
                "referencias": {
                    "anteriores": [
                        {
                            "anterior": [
                                {
                                    "id_norma": (
                                        "BOE-A-2000-544"
                                    ),
                                    "relacion": {
                                        "codigo": "490",
                                        "texto": (
                                            "DESARROLLA"
                                        ),
                                    },
                                    "texto": (
                                        "la Ley "
                                        "Organica 4/2000"
                                    ),
                                }
                            ]
                        }
                    ],
                    "posteriores": [
                        {
                            "posterior": [
                                {
                                    "id_norma": (
                                        "BOE-A-2026-8284"
                                    ),
                                    "relacion": {
                                        "codigo": "210",
                                        "texto": (
                                            "SE DEROGA"
                                        ),
                                    },
                                    "texto": (
                                        "modificacion "
                                        "posterior"
                                    ),
                                }
                            ]
                        }
                    ],
                },
            }
        ],
    }


def _index_payload():
    return {
        "status": {
            "code": "200",
            "text": "ok",
        },
        "data": [
            {
                "bloque": [
                    {
                        "id": "a1",
                        "titulo": "Articulo 1",
                        "fecha_actualizacion": (
                            "20241120"
                        ),
                        "url": (
                            "https://example/a1"
                        ),
                    },
                    {
                        "id": "a2",
                        "titulo": "Articulo 2",
                        "fecha_actualizacion": (
                            "20260415"
                        ),
                        "url": (
                            "https://example/a2"
                        ),
                    },
                ]
            }
        ],
    }


class _FakeTransport:
    def discover(
        self,
        *,
        cursor=None,
    ):
        assert cursor == "20260605"
        return _discovery_payload()

    def fetch(
        self,
        external_id,
    ):
        assert external_id == TARGET

        return {
            "id": TARGET,
            "metadata": (
                _metadata_payload()
            ),
            "analysis": (
                _analysis_payload()
            ),
            "index": (
                _index_payload()
            ),
            "text_xml": TEXT_XML,
        }


def test_registry_contains_consolidated_source():
    source = get_knowledge_source(
        "BOE_CONSOLIDATED"
    )

    assert (
        source.source_kind
        is KnowledgeSourceKind.OFFICIAL_LEGISLATION
    )

    assert (
        source.authority
        is KnowledgeAuthority.OFFICIAL_SECONDARY
    )


def test_current_text_uses_latest_version_per_block():
    content, model = (
        parse_boe_consolidated_current_text(
            TARGET,
            TEXT_XML,
        )
    )

    assert (
        "Texto vigente sin cambios"
        in content
    )

    assert (
        "Texto vigente reformado"
        in content
    )

    assert (
        "Texto antiguo"
        not in content
    )

    assert model[
        "block_count"
    ] == 2

    assert model[
        "version_count"
    ] == 3


def test_provider_discovers_consolidated_reference():
    provider = BoeConsolidatedProvider(
        _FakeTransport()
    )

    batch = provider.discover(
        cursor="20260605"
    )

    assert batch.source_key == (
        "BOE_CONSOLIDATED"
    )

    assert len(
        batch.items
    ) == 1

    reference = batch.items[0]

    assert (
        reference.external_id
        == TARGET
    )

    assert (
        reference.canonical_uri
        == (
            "https://www.boe.es/eli/"
            "es/rd/2024/11/19/1155"
        )
    )


def test_provider_builds_legislation_item():
    provider = BoeConsolidatedProvider(
        _FakeTransport()
    )

    reference = provider.discover(
        cursor="20260605"
    ).items[0]

    item = provider.to_knowledge_item(
        reference,
        provider.fetch(
            reference
        ),
    )

    assert (
        item.source_key
        == "BOE_CONSOLIDATED"
    )

    assert (
        item.external_id
        == TARGET
    )

    assert (
        item.item_kind
        is KnowledgeItemKind.LEGISLATION
    )

    assert (
        item.source_revision
        == "20260605T080848Z"
    )

    assert (
        item.published_on.isoformat()
        == "2024-11-20"
    )

    assert (
        "Texto antiguo"
        not in item.content_text
    )

    assert (
        "Texto vigente reformado"
        in item.content_text
    )

    metadata = dict(
        item.metadata
    )

    assert (
        metadata[
            "block_count"
        ]
        == "2"
    )

    assert (
        metadata[
            "version_count"
        ]
        == "3"
    )

    subjects = json.loads(
        metadata[
            "subjects_json"
        ]
    )

    assert subjects == [
        {
            "codigo": "7155",
            "texto": "Visados",
        }
    ]

    relations = json.loads(
        metadata[
            "legal_relations_json"
        ]
    )

    assert len(relations) == 2

    assert {
        relation[
            "target_id"
        ]
        for relation in relations
    } == {
        "BOE-A-2000-544",
        "BOE-A-2026-8284",
    }
