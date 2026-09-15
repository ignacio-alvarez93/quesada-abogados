import json

from backend.knowledge import (
    KnowledgeCatalogTier,
    KnowledgeItemKind,
    KnowledgePromotionAction,
    KnowledgePromotionPolicyService,
    KnowledgePromotionReason,
    build_knowledge_catalog_entry,
    build_knowledge_item,
    classify_knowledge_revision,
    evaluate_catalog_promotion,
)
from backend.knowledge.catalog_seed import (
    seed_core_knowledge_catalog,
)
from backend.knowledge.relation_discovery import (
    KnowledgeRelationDiscoveryService,
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
        "description": "LO 4/2000",
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


def _entry(
    external_id,
    *,
    tier,
    watch,
    priority,
):
    return build_knowledge_catalog_entry(
        source_key=SOURCE_KEY,
        external_id=external_id,
        tier=tier,
        watch_updates=watch,
        priority=priority,
    )


def test_forward_material_change_promotes_discovered():
    source = _entry(
        SOURCE_ID,
        tier=KnowledgeCatalogTier.CORE,
        watch=True,
        priority=100,
    )

    target = _entry(
        "BOE-A-2026-8284",
        tier=(
            KnowledgeCatalogTier.DISCOVERED
        ),
        watch=False,
        priority=20,
    )

    decision = evaluate_catalog_promotion(
        source_entry=source,
        target_entry=target,
        relation={
            "direction": "posteriores",
            "relation_text": "SE MODIFICA",
        },
    )

    assert (
        decision.action
        is KnowledgePromotionAction.PROMOTE_FOLLOWED
    )

    assert (
        decision.reason
        is KnowledgePromotionReason.FORWARD_MATERIAL_CHANGE
    )

    assert (
        decision.resulting_tier
        is KnowledgeCatalogTier.FOLLOWED
    )

    assert (
        decision.recommended_priority
        == 90
    )


def test_historical_relation_stays_discovered():
    source = _entry(
        SOURCE_ID,
        tier=KnowledgeCatalogTier.CORE,
        watch=True,
        priority=100,
    )

    target = _entry(
        "BOE-A-2011-7703",
        tier=(
            KnowledgeCatalogTier.DISCOVERED
        ),
        watch=False,
        priority=20,
    )

    decision = evaluate_catalog_promotion(
        source_entry=source,
        target_entry=target,
        relation={
            "direction": "anteriores",
            "relation_text": "DEROGA",
        },
    )

    assert (
        decision.action
        is KnowledgePromotionAction.KEEP
    )

    assert (
        decision.reason
        is KnowledgePromotionReason.HISTORICAL_RELATION
    )


def test_existing_core_is_never_downgraded():
    source = _entry(
        SOURCE_ID,
        tier=KnowledgeCatalogTier.CORE,
        watch=True,
        priority=100,
    )

    target = _entry(
        "BOE-A-2000-544",
        tier=KnowledgeCatalogTier.CORE,
        watch=True,
        priority=100,
    )

    decision = evaluate_catalog_promotion(
        source_entry=source,
        target_entry=target,
        relation={
            "direction": "anteriores",
            "relation_text": "DESARROLLA",
        },
    )

    assert (
        decision.action
        is KnowledgePromotionAction.KEEP
    )

    assert (
        decision.reason
        is KnowledgePromotionReason.ALREADY_GOVERNED
    )

    assert (
        decision.resulting_tier
        is KnowledgeCatalogTier.CORE
    )


def _repositories(
    tmp_path,
):
    db_path = (
        tmp_path
        / "promotion.db"
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


def _materialize_source(
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
        source_revision="20260605T080848Z",
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

    repository.persist(
        item,
        classify_knowledge_revision(
            previous=None,
            current=item,
        ),
    )


def test_realistic_pipeline_discovers_then_promotes_forward_relations(
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

    _materialize_source(
        knowledge_repository
    )

    discovery = (
        KnowledgeRelationDiscoveryService(
            knowledge_repository=(
                knowledge_repository
            ),
            catalog_repository=(
                catalog_repository
            ),
        )
    )

    discovered = (
        discovery.discover_from_item(
            SOURCE_KEY,
            SOURCE_ID,
        )
    )

    assert (
        discovered.discovered_count
        == 3
    )

    policy = (
        KnowledgePromotionPolicyService(
            knowledge_repository=(
                knowledge_repository
            ),
            catalog_repository=(
                catalog_repository
            ),
        )
    )

    preview = (
        policy.evaluate_from_item(
            SOURCE_KEY,
            SOURCE_ID,
            apply=False,
        )
    )

    assert (
        preview.recommended_count
        == 2
    )

    assert (
        preview.promoted_count
        == 0
    )

    # Preview no debe mutar catálogo.
    assert (
        catalog_repository.get_entry(
            SOURCE_KEY,
            "BOE-A-2026-8284",
        ).tier
        is KnowledgeCatalogTier.DISCOVERED
    )

    applied = (
        policy.evaluate_from_item(
            SOURCE_KEY,
            SOURCE_ID,
            apply=True,
        )
    )

    assert (
        applied.recommended_count
        == 2
    )

    assert (
        applied.promoted_count
        == 2
    )

    rd_316 = (
        catalog_repository.get_entry(
            SOURCE_KEY,
            "BOE-A-2026-8284",
        )
    )

    order_164 = (
        catalog_repository.get_entry(
            SOURCE_KEY,
            "BOE-A-2026-5128",
        )
    )

    old_regulation = (
        catalog_repository.get_entry(
            SOURCE_KEY,
            "BOE-A-2011-7703",
        )
    )

    assert rd_316 is not None
    assert order_164 is not None
    assert old_regulation is not None

    assert (
        rd_316.tier
        is KnowledgeCatalogTier.FOLLOWED
    )

    assert (
        rd_316.priority
        == 90
    )

    assert (
        order_164.tier
        is KnowledgeCatalogTier.FOLLOWED
    )

    assert (
        order_164.priority
        == 80
    )

    assert (
        old_regulation.tier
        is KnowledgeCatalogTier.DISCOVERED
    )


def test_second_policy_pass_is_idempotent(
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

    _materialize_source(
        knowledge_repository
    )

    KnowledgeRelationDiscoveryService(
        knowledge_repository=(
            knowledge_repository
        ),
        catalog_repository=(
            catalog_repository
        ),
    ).discover_from_item(
        SOURCE_KEY,
        SOURCE_ID,
    )

    service = (
        KnowledgePromotionPolicyService(
            knowledge_repository=(
                knowledge_repository
            ),
            catalog_repository=(
                catalog_repository
            ),
        )
    )

    first = service.evaluate_from_item(
        SOURCE_KEY,
        SOURCE_ID,
        apply=True,
    )

    second = service.evaluate_from_item(
        SOURCE_KEY,
        SOURCE_ID,
        apply=True,
    )

    assert first.promoted_count == 2

    assert (
        second.promoted_count
        == 0
    )

    assert (
        second.recommended_count
        == 0
    )

    assert (
        catalog_repository.get_entry(
            SOURCE_KEY,
            "BOE-A-2026-8284",
        ).tier
        is KnowledgeCatalogTier.FOLLOWED
    )

    assert (
        catalog_repository.get_entry(
            SOURCE_KEY,
            "BOE-A-2026-5128",
        ).tier
        is KnowledgeCatalogTier.FOLLOWED
    )
