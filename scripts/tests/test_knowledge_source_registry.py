import pytest

from backend.knowledge import (
    KnowledgeAuthority,
    KnowledgeSourceKind,
    get_knowledge_source,
    knowledge_source_exists,
    list_knowledge_sources,
    normalize_source_key,
)


def test_boe_is_registered_as_official_primary_legislation_source():
    source = get_knowledge_source("BOE")

    assert source.key == "BOE"
    assert source.provider == "BOE"
    assert source.display_name == "Boletín Oficial del Estado"
    assert (
        source.source_kind
        is KnowledgeSourceKind.OFFICIAL_GAZETTE
    )
    assert (
        source.authority
        is KnowledgeAuthority.OFFICIAL_PRIMARY
    )
    assert source.enabled is True


def test_source_lookup_normalizes_user_input():
    assert get_knowledge_source(" boe ").key == "BOE"
    assert normalize_source_key(" boe ") == "BOE"


def test_unknown_source_is_rejected():
    with pytest.raises(
        KeyError,
        match="Fuente Knowledge no registrada",
    ):
        get_knowledge_source("UNKNOWN")


def test_empty_source_key_is_rejected():
    with pytest.raises(ValueError):
        normalize_source_key("   ")


def test_source_exists_is_safe_for_unknown_or_empty_values():
    assert knowledge_source_exists("BOE") is True
    assert knowledge_source_exists("boe") is True
    assert knowledge_source_exists("UNKNOWN") is False
    assert knowledge_source_exists("") is False


def test_registry_has_unique_stable_keys():
    sources = list_knowledge_sources()

    keys = [source.key for source in sources]

    assert keys == sorted(keys)
    assert len(keys) == len(set(keys))
    assert "BOE" in keys
