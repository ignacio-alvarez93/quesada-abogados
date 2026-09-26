from datetime import date

import pytest

from backend.knowledge import (
    KnowledgeBlock,
    KnowledgeBlockVersion,
    KnowledgeStructuredDocument,
    build_knowledge_block_version,
)


def _version(
    *,
    block_id,
    position,
    text,
    current,
):
    return build_knowledge_block_version(
        source_key="BOE_CONSOLIDATED",
        external_id="BOE-A-2024-24099",
        block_id=block_id,
        version_position=position,
        content_text=text,
        modifier_external_id=(
            "BOE-A-2024-24099"
        ),
        published_on=date(
            2024,
            11,
            20,
        ),
        effective_from=date(
            2025,
            5,
            20,
        ),
        is_current=current,
    )


def test_structured_document_exposes_current_text():
    a1v1 = _version(
        block_id="a1",
        position=1,
        text="Articulo 1 vigente.",
        current=True,
    )

    a2v1 = _version(
        block_id="a2",
        position=1,
        text="Articulo 2 antiguo.",
        current=False,
    )

    a2v2 = _version(
        block_id="a2",
        position=2,
        text="Articulo 2 vigente.",
        current=True,
    )

    document = KnowledgeStructuredDocument(
        source_key="BOE_CONSOLIDATED",
        external_id="BOE-A-2024-24099",
        blocks=(
            KnowledgeBlock(
                source_key=(
                    "BOE_CONSOLIDATED"
                ),
                external_id=(
                    "BOE-A-2024-24099"
                ),
                block_id="a1",
                position=1,
                title="Articulo 1",
                current_version_key=(
                    a1v1.version_key
                ),
            ),
            KnowledgeBlock(
                source_key=(
                    "BOE_CONSOLIDATED"
                ),
                external_id=(
                    "BOE-A-2024-24099"
                ),
                block_id="a2",
                position=2,
                title="Articulo 2",
                current_version_key=(
                    a2v2.version_key
                ),
            ),
        ),
        versions=(
            a1v1,
            a2v1,
            a2v2,
        ),
    )

    assert (
        document.current_content_text
        == (
            "Articulo 1 vigente.\n\n"
            "Articulo 2 vigente."
        )
    )

    assert (
        len(
            document.versions_for_block(
                "a2"
            )
        )
        == 2
    )


def test_version_key_is_deterministic():
    first = _version(
        block_id="a1",
        position=1,
        text="Texto estable.",
        current=True,
    )

    second = _version(
        block_id="a1",
        position=1,
        text="Texto estable.",
        current=True,
    )

    assert (
        first.version_key
        == second.version_key
    )

    assert (
        first.content_sha256
        == second.content_sha256
    )


def test_version_key_is_independent_from_version_position():
    first = _version(
        block_id="a1",
        position=1,
        text="Texto jurídicamente estable.",
        current=False,
    )

    shifted = _version(
        block_id="a1",
        position=7,
        text="Texto jurídicamente estable.",
        current=False,
    )

    assert (
        first.version_key
        == shifted.version_key
    )

    assert (
        first.version_position
        != shifted.version_position
    )


def test_structure_requires_one_current_version_per_block():
    historical = _version(
        block_id="a1",
        position=1,
        text="Texto antiguo.",
        current=False,
    )

    with pytest.raises(
        ValueError,
        match="exactamente una versión vigente",
    ):
        KnowledgeStructuredDocument(
            source_key="BOE_CONSOLIDATED",
            external_id="BOE-A-2024-24099",
            blocks=(
                KnowledgeBlock(
                    source_key=(
                        "BOE_CONSOLIDATED"
                    ),
                    external_id=(
                        "BOE-A-2024-24099"
                    ),
                    block_id="a1",
                    position=1,
                ),
            ),
            versions=(
                historical,
            ),
        )


def test_version_contract_accepts_empty_text_without_losing_identity():
    version = (
        build_knowledge_block_version(
            source_key=(
                "BOE_CONSOLIDATED"
            ),
            external_id=(
                "BOE-A-2024-24099"
            ),
            block_id="a1",
            version_position=1,
            content_text="",
            modifier_external_id=(
                "BOE-A-2026-00001"
            ),
            is_current=True,
        )
    )

    assert isinstance(
        version,
        KnowledgeBlockVersion,
    )

    assert (
        version.content_text
        == ""
    )

    assert version.version_key
