from backend.knowledge import (
    VERIFIED_RELATION_ALIASES,
    get_verified_relation_alias,
    list_relation_aliases_for_identity,
    resolve_relation_identity,
)


def test_verified_doue_2024_resolves_to_single_permit_celex():
    resolved = resolve_relation_identity(
        "DOUE-L-2024-80617"
    )

    assert resolved is not None

    assert (
        resolved.source_key
        == "EUR_LEX"
    )

    assert (
        resolved.external_id
        == "32024L1233"
    )

    assert (
        resolved.canonical_key
        == "EUR_LEX:32024L1233"
    )

    assert (
        resolved.used_alias
        is True
    )


def test_verified_doue_2011_resolves_to_previous_single_permit_celex():
    resolved = resolve_relation_identity(
        "DOUE-L-2011-82719"
    )

    assert resolved is not None

    assert (
        resolved.source_key
        == "EUR_LEX"
    )

    assert (
        resolved.external_id
        == "32011L0098"
    )


def test_crosswalk_supports_reverse_lookup():
    assert (
        list_relation_aliases_for_identity(
            "EUR_LEX",
            "32024L1233",
        )
        == (
            "DOUE-L-2024-80617",
        )
    )

    assert (
        list_relation_aliases_for_identity(
            "EUR_LEX",
            "32011L0098",
        )
        == (
            "DOUE-L-2011-82719",
        )
    )


def test_unknown_doue_fails_closed():
    assert (
        resolve_relation_identity(
            "DOUE-L-2099-99999"
        )
        is None
    )


def test_boe_identity_remains_direct():
    resolved = resolve_relation_identity(
        "BOE-A-2026-8284"
    )

    assert resolved is not None

    assert (
        resolved.source_key
        == "BOE_CONSOLIDATED"
    )

    assert (
        resolved.external_id
        == "BOE-A-2026-8284"
    )

    assert (
        resolved.used_alias
        is False
    )


def test_alias_registry_preserves_official_evidence():
    assert (
        len(
            VERIFIED_RELATION_ALIASES
        )
        >= 2
    )

    entry = get_verified_relation_alias(
        "DOUE-L-2024-80617"
    )

    assert entry is not None

    assert (
        "boe.es"
        in entry.alias_evidence_uri
    )

    assert (
        "eur-lex.europa.eu"
        in entry.target_evidence_uri
    )
