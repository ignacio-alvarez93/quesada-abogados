from datetime import date

import pytest

from backend.knowledge import (
    KnowledgeItemKind,
    KnowledgeValidityStatus,
    build_knowledge_item,
    unknown_validity,
)
from backend.knowledge.boe_consolidated.validity import (
    resolve_boe_consolidated_validity,
)
from backend.knowledge.eurlex.validity import (
    resolve_eurlex_validity,
)


def _boe_item(**metadata_overrides):
    metadata = {
        "estatus_derogacion": "N",
        "estatus_anulacion": "N",
        "vigencia_agotada": "N",
        "fecha_vigencia": "20250520",
        "legal_relations_json": "[]",
    }

    metadata.update(metadata_overrides)

    return build_knowledge_item(
        source_key="BOE_CONSOLIDATED",
        external_id="BOE-A-2024-24099",
        title="Real Decreto 1155/2024",
        item_kind=KnowledgeItemKind.LEGISLATION,
        content_text="Texto vigente.",
        source_revision="20260605T080848Z",
        metadata=metadata,
    )


def test_unknown_validity_is_explicit_and_never_positive():
    result = unknown_validity(
        source_key="BOE_CONSOLIDATED",
        external_id="X",
        reason="sin evidencia",
    )

    assert result.status is KnowledgeValidityStatus.UNKNOWN
    assert result.in_force is False
    assert result.end_date is None
    assert result.evidence == ()


def test_boe_all_flags_negative_confirms_in_force():
    item = _boe_item()

    result = resolve_boe_consolidated_validity(item)

    assert result.status is KnowledgeValidityStatus.IN_FORCE
    assert result.in_force is True
    assert result.end_date is None
    assert result.has_evidence is True

    fields = {evidence.field for evidence in result.evidence}
    assert "estatus_derogacion" in fields
    assert "estatus_anulacion" in fields
    assert "vigencia_agotada" in fields


def test_boe_repeal_flag_yields_repealed_with_end_date():
    item = _boe_item(
        estatus_derogacion="S",
        fecha_vigencia="20260416",
        legal_relations_json=(
            '[{"direction": "posteriores", '
            '"target_id": "BOE-A-2026-8284", '
            '"relation_code": "210", '
            '"relation_text": "SE DEROGA"}]'
        ),
    )

    result = resolve_boe_consolidated_validity(item)

    assert result.status is KnowledgeValidityStatus.REPEALED
    assert result.end_date == date(2026, 4, 16)
    assert result.repealed_by_external_id == "BOE-A-2026-8284"
    assert result.in_force is False


def test_boe_repeal_ignores_unrelated_relation_codes():
    item = _boe_item(
        estatus_derogacion="S",
        legal_relations_json=(
            '[{"direction": "posteriores", '
            '"target_id": "BOE-A-2026-9999", '
            '"relation_code": "999", '
            '"relation_text": "OTRA RELACION"}]'
        ),
    )

    result = resolve_boe_consolidated_validity(item)

    assert result.status is KnowledgeValidityStatus.REPEALED
    assert result.repealed_by_external_id == ""


def test_boe_annulment_flag_also_yields_repealed():
    item = _boe_item(estatus_anulacion="S")

    result = resolve_boe_consolidated_validity(item)

    assert result.status is KnowledgeValidityStatus.REPEALED
    assert "anulacion" in result.reason


def test_boe_exhausted_validity_without_repeal_is_explicit_end_of_validity():
    item = _boe_item(vigencia_agotada="S")

    result = resolve_boe_consolidated_validity(item)

    assert (
        result.status
        is KnowledgeValidityStatus.EXPLICIT_END_OF_VALIDITY
    )
    assert result.end_date == date(2025, 5, 20)


def test_boe_missing_flags_is_unknown_not_in_force():
    item = _boe_item(
        estatus_derogacion="",
        estatus_anulacion="",
        vigencia_agotada="",
        fecha_vigencia="",
    )

    result = resolve_boe_consolidated_validity(item)

    assert result.status is KnowledgeValidityStatus.UNKNOWN
    assert result.evidence == ()


def test_boe_malformed_fecha_vigencia_fails_closed():
    item = _boe_item(fecha_vigencia="2025-05")

    with pytest.raises(ValueError):
        resolve_boe_consolidated_validity(item)


def test_boe_resolver_rejects_foreign_source():
    item = build_knowledge_item(
        source_key="EUR_LEX_CONSOLIDATED",
        external_id="32016R0679",
        title="Reglamento",
        item_kind=KnowledgeItemKind.LEGISLATION,
        content_text="x",
    )

    with pytest.raises(ValueError):
        resolve_boe_consolidated_validity(item)


def test_eurlex_resolver_is_always_unknown():
    item = build_knowledge_item(
        source_key="EUR_LEX_CONSOLIDATED",
        external_id="32016R0679",
        title="Reglamento General de Protección de Datos",
        item_kind=KnowledgeItemKind.LEGISLATION,
        content_text="x",
    )

    result = resolve_eurlex_validity(item)

    assert result.status is KnowledgeValidityStatus.UNKNOWN
    assert result.source_key == "EUR_LEX_CONSOLIDATED"
    assert result.external_id == "32016R0679"


def test_eurlex_resolver_rejects_foreign_source():
    item = _boe_item()

    with pytest.raises(ValueError):
        resolve_eurlex_validity(item)
