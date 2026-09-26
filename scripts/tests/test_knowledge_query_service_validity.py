from datetime import date

from backend.knowledge import (
    KnowledgeBlock,
    KnowledgeEvidenceHorizonStatus,
    KnowledgeItemKind,
    KnowledgeQueryService,
    KnowledgeStructuredDocument,
    KnowledgeValidityStatus,
    build_knowledge_block_version,
    build_knowledge_item,
)
from backend.knowledge.repository import KnowledgeRevisionSnapshot
from backend.knowledge.revisions import KnowledgeRevisionStatus
from backend.knowledge.boe_consolidated.validity import (
    resolve_boe_consolidated_validity,
)


SOURCE = "BOE_CONSOLIDATED"
EXTERNAL_ID = "BOE-A-2024-24099"


class MemoryStructures:
    def __init__(self, *documents):
        self._documents = {
            (d.source_key, d.external_id): d for d in documents
        }

    def initialize_schema(self):
        pass

    def get_document(self, source_key, external_id):
        return self._documents.get(
            (source_key.strip().upper(), external_id.strip())
        )

    def persist(self, document):
        raise NotImplementedError

    def list_document_identities(self, source_key=None):
        return tuple(sorted(self._documents.keys()))


class MemoryItems:
    def __init__(self, *items, revisions=()):
        self._items = {i.source_identity: i for i in items}
        self._revisions = revisions

    def initialize_schema(self):
        pass

    def get_current(self, source_key, external_id):
        return self._items.get((source_key, external_id))

    def persist(self, item, decision):
        raise NotImplementedError

    def list_revisions(self, source_key, external_id):
        return self._revisions


def _document():
    version = build_knowledge_block_version(
        source_key=SOURCE,
        external_id=EXTERNAL_ID,
        block_id="a1",
        version_position=1,
        content_text="Texto vigente.",
        effective_from=date(2024, 1, 1),
        is_current=True,
    )

    block = KnowledgeBlock(
        source_key=SOURCE,
        external_id=EXTERNAL_ID,
        block_id="a1",
        position=1,
        title="Articulo 1",
    )

    return KnowledgeStructuredDocument(
        source_key=SOURCE,
        external_id=EXTERNAL_ID,
        blocks=(block,),
        versions=(version,),
    )


def _item():
    return build_knowledge_item(
        source_key=SOURCE,
        external_id=EXTERNAL_ID,
        title="Real Decreto 1155/2024",
        item_kind=KnowledgeItemKind.LEGISLATION,
        content_text="Texto vigente.",
        source_revision="rev-1",
        metadata={
            "estatus_derogacion": "N",
            "estatus_anulacion": "N",
            "vigencia_agotada": "N",
            "fecha_vigencia": "20250520",
        },
    )


def _snapshot(observed_at="2026-06-05T08:08:48+00:00"):
    return KnowledgeRevisionSnapshot(
        revision_number=1,
        revision_status=KnowledgeRevisionStatus.NEW,
        item=_item(),
        record_sha256="deadbeef",
        observed_at=observed_at,
    )


# ------------------------------------------------------------
# get_document_validity
# ------------------------------------------------------------


def test_validity_unknown_without_item_repository():
    service = KnowledgeQueryService(MemoryStructures(_document()))

    result = service.get_document_validity(SOURCE, EXTERNAL_ID)

    assert result.status is KnowledgeValidityStatus.UNKNOWN
    assert "item_repository" in result.reason


def test_validity_unknown_when_item_missing():
    service = KnowledgeQueryService(
        MemoryStructures(_document()),
        MemoryItems(),
    )

    result = service.get_document_validity(SOURCE, EXTERNAL_ID)

    assert result.status is KnowledgeValidityStatus.UNKNOWN
    assert "KnowledgeItem" in result.reason


def test_validity_unknown_when_no_resolver_registered():
    service = KnowledgeQueryService(
        MemoryStructures(_document()),
        MemoryItems(_item()),
    )

    result = service.get_document_validity(SOURCE, EXTERNAL_ID)

    assert result.status is KnowledgeValidityStatus.UNKNOWN
    assert "resolutor" in result.reason


def test_validity_resolves_with_registered_resolver():
    service = KnowledgeQueryService(
        MemoryStructures(_document()),
        MemoryItems(_item()),
        validity_resolvers={
            SOURCE: resolve_boe_consolidated_validity,
        },
    )

    result = service.get_document_validity(SOURCE, EXTERNAL_ID)

    assert result.status is KnowledgeValidityStatus.IN_FORCE


# ------------------------------------------------------------
# get_evidence_horizon
# ------------------------------------------------------------


def test_evidence_horizon_unknown_without_item_repository():
    service = KnowledgeQueryService(MemoryStructures(_document()))

    horizon = service.get_evidence_horizon(SOURCE, EXTERNAL_ID)

    assert (
        horizon.status
        is KnowledgeEvidenceHorizonStatus.HORIZON_UNKNOWN
    )


def test_evidence_horizon_never_ingested_when_no_revisions():
    service = KnowledgeQueryService(
        MemoryStructures(_document()),
        MemoryItems(_item(), revisions=()),
    )

    horizon = service.get_evidence_horizon(SOURCE, EXTERNAL_ID)

    assert (
        horizon.status
        is KnowledgeEvidenceHorizonStatus.NEVER_INGESTED
    )


def test_evidence_horizon_checked_reflects_last_observation():
    service = KnowledgeQueryService(
        MemoryStructures(_document()),
        MemoryItems(_item(), revisions=(_snapshot(),)),
    )

    horizon = service.get_evidence_horizon(SOURCE, EXTERNAL_ID)

    assert horizon.status is KnowledgeEvidenceHorizonStatus.CHECKED
    assert horizon.checked_as_of == "2026-06-05T08:08:48+00:00"
