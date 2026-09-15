import json

import pytest

from backend.knowledge import (
    KnowledgeCatalogTier,
    KnowledgeItemKind,
    KnowledgeRelationDiscoveryService,
    build_knowledge_item,
    classify_knowledge_revision,
    resolve_relation_identity,
    resolve_relation_source_key,
)
from backend.knowledge.catalog_seed import (
    seed_core_knowledge_catalog,
)
from backend.knowledge.sqlite_catalog_repository import (
    SQLiteKnowledgeCatalogRepository,
)
from backend.knowledge.sqlite_repository import (
    SQLiteKnowledgeRepository,
)


SOURCE_KEY = "BOE_CONSOLIDATED"
SOURCE_ID = "BOE-A-2024-24099"


RELATIONS = [
    {
        "direction": "anteriores",
        "target_id": "BOE-A-2000-544",
        "relation_code": "490",
        "relation_text": "DESARROLLA",
        "description": "Ley Organica 4/2000",
    },
    {
        "direction": "anteriores",
        "target_id": "BOE-A-2011-7703",
        "relation_code": "210",
        "relation_text": "DEROGA",
        "description": "Reglamento anterior",
    },
    {
        "direction": "posteriores",
        "target_id": "BOE-A-2026-8284",
        "relation_code": "210",
        "relation_text": "SE DEROGA",
        "description": "Reforma posterior",
    },
    {
        "direction": "posteriores",
        "target_id": "BOE-A-2026-5128",
        "relation_code": "440",
        "relation_text": (
            "SE DICTA DE CONFORMIDAD"
        ),
        "description": "Orden posterior",
    },
    {
        "direction": "anteriores",
        "target_id": "DOUE-L-2024-80617",
        "relation_code": "426",
        "relation_text": "TRANSPONE",
        "description": "Directiva UE",
    },
]


def _repositories(
    tmp_path,
):
    db_path = (
        tmp_path
        / "knowledge_relations.db"
    )

    knowledge_repository = (
        SQLiteKnowledgeRepository(
            db_path
        )
    )

    catalog_repository = (
        SQLiteKnowledgeCatalogRepository(
            db_path
        )
    )

    knowledge_repository.initialize_schema()
    catalog_repository.initialize_schema()

    return (
        knowledge_repository,
        catalog_repository,
    )


def _materialize_source_item(
    repository,
):
    item = build_knowledge_item(
        source_key=SOURCE_KEY,
        external_id=SOURCE_ID,
        title="Real Decreto 1155/2024",
        item_kind=(
            KnowledgeItemKind.LEGISLATION
        ),
        content_text=(
            "Contenido consolidado de prueba."
        ),
        canonical_uri=(
            "https://www.boe.es/eli/"
            "es/rd/2024/11/19/1155"
        ),
        source_revision=(
            "20260605T080848Z"
        ),
        metadata={
            "legal_relations_json": (
                json.dumps(
                    RELATIONS,
                    ensure_ascii=False,
                    sort_keys=True,
                )
            ),
        },
    )

    decision = classify_knowledge_revision(
        previous=None,
        current=item,
    )

    repository.persist(
        item,
        decision,
    )


def test_relation_source_resolution_is_fail_closed():
    assert (
        resolve_relation_source_key(
            "BOE-A-2026-8284"
        )
        == "BOE_CONSOLIDATED"
    )

    assert (
        resolve_relation_source_key(
            "DOUE-L-2024-80617"
        )
        == "EUR_LEX"
    )

    resolved = (
        resolve_relation_identity(
            "DOUE-L-2024-80617"
        )
    )

    assert resolved is not None

    assert (
        resolved.external_id
        == "32024L1233"
    )

    assert (
        resolve_relation_source_key(
            "UNKNOWN-123"
        )
        is None
    )


def test_relations_discover_unknown_norms_without_downgrading_core(
    tmp_path,
):
    (
        knowledge_repository,
        catalog_repository,
    ) = _repositories(
        tmp_path
    )

    seed_core_knowledge_catalog(
        catalog_repository
    )

    _materialize_source_item(
        knowledge_repository
    )

    service = (
        KnowledgeRelationDiscoveryService(
            knowledge_repository=(
                knowledge_repository
            ),
            catalog_repository=(
                catalog_repository
            ),
        )
    )

    result = service.discover_from_item(
        SOURCE_KEY,
        SOURCE_ID,
    )

    assert (
        result.relation_count
        == 5
    )

    assert (
        result.discovered_count
        == 4
    )

    assert (
        result.existing_count
        == 1
    )

    assert (
        result.unsupported_count
        == 0
    )

    assert set(
        result.discovered_keys
    ) == {
        (
            "BOE_CONSOLIDATED:"
            "BOE-A-2011-7703"
        ),
        (
            "BOE_CONSOLIDATED:"
            "BOE-A-2026-8284"
        ),
        (
            "BOE_CONSOLIDATED:"
            "BOE-A-2026-5128"
        ),
        "EUR_LEX:32024L1233",
    }

    assert (
        result.unsupported_external_ids
        == ()
    )

    eu_target = (
        catalog_repository.get_entry(
            "EUR_LEX",
            "32024L1233",
        )
    )

    assert eu_target is not None

    assert (
        eu_target.tier
        is KnowledgeCatalogTier.DISCOVERED
    )

    assert (
        catalog_repository.get_entry(
            "EUR_LEX",
            "DOUE-L-2024-80617",
        )
        is None
    )

    # LO 4/2000 ya era CORE.
    # Discovery no puede degradarla.
    lo_4_2000 = (
        catalog_repository.get_entry(
            SOURCE_KEY,
            "BOE-A-2000-544",
        )
    )

    assert lo_4_2000 is not None

    assert (
        lo_4_2000.tier
        is KnowledgeCatalogTier.CORE
    )

    assert (
        lo_4_2000.watch_updates
        is True
    )

    discovered = (
        catalog_repository.get_entry(
            SOURCE_KEY,
            "BOE-A-2026-8284",
        )
    )

    assert discovered is not None

    assert (
        discovered.tier
        is KnowledgeCatalogTier.DISCOVERED
    )

    assert (
        discovered.watch_updates
        is False
    )

    assert (
        discovered.priority
        == 20
    )


def test_relation_discovery_is_idempotent(
    tmp_path,
):
    (
        knowledge_repository,
        catalog_repository,
    ) = _repositories(
        tmp_path
    )

    seed_core_knowledge_catalog(
        catalog_repository
    )

    _materialize_source_item(
        knowledge_repository
    )

    service = (
        KnowledgeRelationDiscoveryService(
            knowledge_repository=(
                knowledge_repository
            ),
            catalog_repository=(
                catalog_repository
            ),
        )
    )

    first = service.discover_from_item(
        SOURCE_KEY,
        SOURCE_ID,
    )

    second = service.discover_from_item(
        SOURCE_KEY,
        SOURCE_ID,
    )

    assert (
        first.discovered_count
        == 4
    )

    assert (
        second.discovered_count
        == 0
    )

    # Las tres descubiertas más LO 4/2000
    # ya existen en la segunda observación.
    assert (
        second.existing_count
        == 5
    )

    assert (
        second.unsupported_count
        == 0
    )

    entries = (
        catalog_repository.list_entries()
    )

    # 4 CORE iniciales + 4 nuevas DISCOVERED,
    # incluida EUR_LEX:32024L1233.
    assert len(entries) == 8


def test_missing_materialized_source_fails_closed(
    tmp_path,
):
    (
        knowledge_repository,
        catalog_repository,
    ) = _repositories(
        tmp_path
    )

    service = (
        KnowledgeRelationDiscoveryService(
            knowledge_repository=(
                knowledge_repository
            ),
            catalog_repository=(
                catalog_repository
            ),
        )
    )

    with pytest.raises(
        LookupError,
    ):
        service.discover_from_item(
            SOURCE_KEY,
            SOURCE_ID,
        )
