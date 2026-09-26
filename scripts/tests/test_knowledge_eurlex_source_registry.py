from backend.knowledge import (
    KnowledgeAuthority,
    KnowledgeSourceKind,
    get_knowledge_source,
    list_knowledge_sources,
)


def test_eurlex_original_is_registered_as_primary():
    source = get_knowledge_source(
        "EUR_LEX"
    )

    assert (
        source.provider
        == "EUR_LEX"
    )

    assert (
        source.source_kind
        is KnowledgeSourceKind.OFFICIAL_LEGISLATION
    )

    assert (
        source.authority
        is KnowledgeAuthority.OFFICIAL_PRIMARY
    )


def test_eurlex_consolidated_is_registered_as_secondary():
    source = get_knowledge_source(
        "EUR_LEX_CONSOLIDATED"
    )

    assert (
        source.provider
        == "EUR_LEX"
    )

    assert (
        source.source_kind
        is KnowledgeSourceKind.OFFICIAL_LEGISLATION
    )

    assert (
        source.authority
        is KnowledgeAuthority.OFFICIAL_SECONDARY
    )


def test_both_eurlex_sources_are_listed():
    keys = {
        source.key
        for source
        in list_knowledge_sources()
    }

    assert {
        "EUR_LEX",
        "EUR_LEX_CONSOLIDATED",
    }.issubset(
        keys
    )
