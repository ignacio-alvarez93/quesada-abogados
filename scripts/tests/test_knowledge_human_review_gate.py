import pytest

from backend.knowledge import (
    KnowledgeCatalogTier,
    KnowledgeHumanReviewGateService,
    KnowledgePromotionReviewOutcome,
    KnowledgePromotionReviewState,
    build_knowledge_catalog_entry,
    evaluate_catalog_promotion,
)
from backend.knowledge.sqlite_catalog_repository import (
    SQLiteKnowledgeCatalogRepository,
)
from backend.knowledge.sqlite_promotion_review_repository import (
    SQLiteKnowledgePromotionReviewRepository,
)


SOURCE_KEY = "BOE_CONSOLIDATED"
SOURCE_ID = "BOE-A-2024-24099"
TARGET_ID = "BOE-A-2026-8284"


def _repositories(tmp_path):
    db_path = tmp_path / "human_review.db"

    catalog_repository = SQLiteKnowledgeCatalogRepository(
        db_path
    )

    review_repository = SQLiteKnowledgePromotionReviewRepository(
        db_path
    )

    catalog_repository.initialize_schema()
    review_repository.initialize_schema()

    return catalog_repository, review_repository


def _seed_discovered_pair(catalog_repository):
    source_entry = build_knowledge_catalog_entry(
        source_key=SOURCE_KEY,
        external_id=SOURCE_ID,
        tier=KnowledgeCatalogTier.CORE,
        watch_updates=True,
        priority=100,
    )

    target_entry = build_knowledge_catalog_entry(
        source_key=SOURCE_KEY,
        external_id=TARGET_ID,
        tier=KnowledgeCatalogTier.DISCOVERED,
        watch_updates=False,
        priority=20,
    )

    catalog_repository.upsert(source_entry)
    catalog_repository.upsert(target_entry)

    return source_entry, target_entry


def _promote_decision(source_entry, target_entry):
    return evaluate_catalog_promotion(
        source_entry=source_entry,
        target_entry=target_entry,
        relation={
            "direction": "posteriores",
            "relation_text": "SE MODIFICA",
        },
    )


def test_submit_for_review_creates_pending_without_mutating_catalog(
    tmp_path,
):
    catalog_repository, review_repository = _repositories(
        tmp_path
    )

    source_entry, target_entry = _seed_discovered_pair(
        catalog_repository
    )

    decision = _promote_decision(
        source_entry, target_entry
    )

    gate = KnowledgeHumanReviewGateService(
        catalog_repository=catalog_repository,
        review_repository=review_repository,
    )

    review = gate.submit_for_review(decision)

    assert (
        review.state
        is KnowledgePromotionReviewState.PENDING_REVIEW
    )

    assert review.reviewer_ref is None
    assert review.reviewed_at is None

    assert (
        review.outcome
        is KnowledgePromotionReviewOutcome.NOT_PROMOTED
    )

    assert (
        catalog_repository.get_entry(
            SOURCE_KEY, TARGET_ID
        ).tier
        is KnowledgeCatalogTier.DISCOVERED
    )


def test_approve_with_reviewer_ref_promotes_to_followed(
    tmp_path,
):
    catalog_repository, review_repository = _repositories(
        tmp_path
    )

    source_entry, target_entry = _seed_discovered_pair(
        catalog_repository
    )

    decision = _promote_decision(
        source_entry, target_entry
    )

    gate = KnowledgeHumanReviewGateService(
        catalog_repository=catalog_repository,
        review_repository=review_repository,
    )

    review = gate.submit_for_review(decision)

    approved = gate.approve(
        review.review_id,
        reviewer_ref="reviewer:nacho",
    )

    assert (
        approved.state
        is KnowledgePromotionReviewState.APPROVED
    )

    assert approved.reviewer_ref == "reviewer:nacho"
    assert approved.reviewed_at is not None

    assert (
        approved.outcome
        is KnowledgePromotionReviewOutcome.PROMOTED_FOLLOWED
    )

    promoted_entry = catalog_repository.get_entry(
        SOURCE_KEY, TARGET_ID
    )

    assert promoted_entry.tier is KnowledgeCatalogTier.FOLLOWED
    assert promoted_entry.watch_updates is True
    assert promoted_entry.priority == 90


def test_reject_leaves_catalog_discovered(
    tmp_path,
):
    catalog_repository, review_repository = _repositories(
        tmp_path
    )

    source_entry, target_entry = _seed_discovered_pair(
        catalog_repository
    )

    decision = _promote_decision(
        source_entry, target_entry
    )

    gate = KnowledgeHumanReviewGateService(
        catalog_repository=catalog_repository,
        review_repository=review_repository,
    )

    review = gate.submit_for_review(decision)

    rejected = gate.reject(
        review.review_id,
        reviewer_ref="reviewer:nacho",
    )

    assert (
        rejected.state
        is KnowledgePromotionReviewState.REJECTED
    )

    assert (
        rejected.outcome
        is KnowledgePromotionReviewOutcome.NOT_PROMOTED
    )

    assert (
        catalog_repository.get_entry(
            SOURCE_KEY, TARGET_ID
        ).tier
        is KnowledgeCatalogTier.DISCOVERED
    )


def test_missing_reviewer_fails_closed(
    tmp_path,
):
    catalog_repository, review_repository = _repositories(
        tmp_path
    )

    source_entry, target_entry = _seed_discovered_pair(
        catalog_repository
    )

    decision = _promote_decision(
        source_entry, target_entry
    )

    gate = KnowledgeHumanReviewGateService(
        catalog_repository=catalog_repository,
        review_repository=review_repository,
    )

    review = gate.submit_for_review(decision)

    with pytest.raises(ValueError):
        gate.approve(
            review.review_id,
            reviewer_ref="",
        )

    with pytest.raises(ValueError):
        gate.approve(
            review.review_id,
            reviewer_ref="   ",
        )

    assert (
        catalog_repository.get_entry(
            SOURCE_KEY, TARGET_ID
        ).tier
        is KnowledgeCatalogTier.DISCOVERED
    )

    assert (
        review_repository.get_review(
            review.review_id
        ).state
        is KnowledgePromotionReviewState.PENDING_REVIEW
    )


def test_double_approve_is_idempotent(
    tmp_path,
):
    catalog_repository, review_repository = _repositories(
        tmp_path
    )

    source_entry, target_entry = _seed_discovered_pair(
        catalog_repository
    )

    decision = _promote_decision(
        source_entry, target_entry
    )

    gate = KnowledgeHumanReviewGateService(
        catalog_repository=catalog_repository,
        review_repository=review_repository,
    )

    review = gate.submit_for_review(decision)

    first = gate.approve(
        review.review_id,
        reviewer_ref="reviewer:nacho",
    )

    second = gate.approve(
        review.review_id,
        reviewer_ref="reviewer:nacho",
    )

    assert first == second

    promoted_entry = catalog_repository.get_entry(
        SOURCE_KEY, TARGET_ID
    )

    assert promoted_entry.tier is KnowledgeCatalogTier.FOLLOWED
    assert promoted_entry.priority == 90


def test_reject_after_approve_is_rejected(
    tmp_path,
):
    catalog_repository, review_repository = _repositories(
        tmp_path
    )

    source_entry, target_entry = _seed_discovered_pair(
        catalog_repository
    )

    decision = _promote_decision(
        source_entry, target_entry
    )

    gate = KnowledgeHumanReviewGateService(
        catalog_repository=catalog_repository,
        review_repository=review_repository,
    )

    review = gate.submit_for_review(decision)

    gate.approve(
        review.review_id,
        reviewer_ref="reviewer:nacho",
    )

    with pytest.raises(ValueError):
        gate.reject(
            review.review_id,
            reviewer_ref="reviewer:other",
        )

    assert (
        catalog_repository.get_entry(
            SOURCE_KEY, TARGET_ID
        ).tier
        is KnowledgeCatalogTier.FOLLOWED
    )


def test_submit_rejects_non_discovered_target(
    tmp_path,
):
    catalog_repository, review_repository = _repositories(
        tmp_path
    )

    source_entry = build_knowledge_catalog_entry(
        source_key=SOURCE_KEY,
        external_id=SOURCE_ID,
        tier=KnowledgeCatalogTier.CORE,
        watch_updates=True,
        priority=100,
    )

    core_target_entry = build_knowledge_catalog_entry(
        source_key=SOURCE_KEY,
        external_id=TARGET_ID,
        tier=KnowledgeCatalogTier.CORE,
        watch_updates=True,
        priority=100,
    )

    catalog_repository.upsert(source_entry)
    catalog_repository.upsert(core_target_entry)

    decision = evaluate_catalog_promotion(
        source_entry=source_entry,
        target_entry=core_target_entry,
        relation={
            "direction": "posteriores",
            "relation_text": "SE MODIFICA",
        },
    )

    gate = KnowledgeHumanReviewGateService(
        catalog_repository=catalog_repository,
        review_repository=review_repository,
    )

    with pytest.raises(ValueError):
        gate.submit_for_review(decision)
