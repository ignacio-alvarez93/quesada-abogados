import pytest

from backend.knowledge.eurlex.parser import (
    consolidated_base_celex,
    consolidated_revision_date,
    is_consolidated_celex,
    normalize_celex,
    parse_tree_notice_eli_uris,
    parse_tree_notice_identifiers,
    select_latest_consolidated_celex,
)


def test_normalizes_supported_original_celex():
    assert (
        normalize_celex(
            " 32016r0399 "
        )
        == "32016R0399"
    )

    assert (
        normalize_celex(
            "12016m/txt"
        )
        == "12016M/TXT"
    )


@pytest.mark.parametrize(
    "value",
    [
        "",
        "BOE-A-2024-24099",
        "NOT-CELEX",
        "22016R0399",
    ],
)
def test_rejects_unsupported_celex(value):
    with pytest.raises(
        ValueError
    ):
        normalize_celex(
            value
        )


def test_derives_consolidated_family_for_legal_act():
    assert (
        consolidated_base_celex(
            "32016R0399"
        )
        == "02016R0399"
    )


def test_derives_consolidated_family_for_treaty():
    assert (
        consolidated_base_celex(
            "12016M/TXT"
        )
        == "02016M/TXT"
    )


def test_recognizes_consolidated_celex():
    assert (
        is_consolidated_celex(
            "02016R0399-20251012"
        )
        is True
    )

    assert (
        is_consolidated_celex(
            "32016R0399"
        )
        is False
    )


def test_extracts_consolidated_revision_date():
    assert (
        consolidated_revision_date(
            "02016R0399-20251012"
        ).isoformat()
        == "2025-10-12"
    )

    assert (
        consolidated_revision_date(
            "02016R0399"
        )
        is None
    )


def test_selects_latest_schengen_revision():
    selected = (
        select_latest_consolidated_celex(
            "32016R0399",
            [
                "02016R0399-20161006",
                "02016R0399-20170407",
                "02016R0399-20240710",
                "02016R0399-20251012",
                "32016R0399",
            ],
        )
    )

    assert (
        selected
        == "02016R0399-20251012"
    )


def test_selects_latest_visa_code_revision():
    selected = (
        select_latest_consolidated_celex(
            "32009R0810",
            [
                "02009R0810-20200202",
                "02009R0810-20240611",
                "02009R0810-20240628",
            ],
        )
    )

    assert (
        selected
        == "02009R0810-20240628"
    )


def test_treaty_revision_date_comes_after_txt_suffix():
    selected = (
        select_latest_consolidated_celex(
            "12016M/TXT",
            [
                "02016M/TXT",
                "02016M/TXT-20250315",
            ],
        )
    )

    assert (
        selected
        == "02016M/TXT-20250315"
    )


def test_tfue_revision_contract():
    selected = (
        select_latest_consolidated_celex(
            "12016E/TXT",
            [
                "02016E/TXT",
                "02016E/TXT-20250315",
            ],
        )
    )

    assert (
        selected
        == "02016E/TXT-20250315"
    )


def test_charter_revision_contract():
    selected = (
        select_latest_consolidated_celex(
            "12016P/TXT",
            [
                "02016P/TXT",
                "02016P/TXT-20091201",
            ],
        )
    )

    assert (
        selected
        == "02016P/TXT-20091201"
    )


def test_single_permit_revision_contract():
    selected = (
        select_latest_consolidated_celex(
            "32024L1233",
            [
                "02024L1233-20240430",
            ],
        )
    )

    assert (
        selected
        == "02024L1233-20240430"
    )


def test_tree_notice_uses_structured_identifier_nodes():
    raw = b"""<?xml version="1.0" encoding="UTF-8"?>
    <NOTICE>
        <WORK>
            <IDENTIFIER>
                <VALUE>32016R0399</VALUE>
            </IDENTIFIER>
            <IDENTIFIER>
                <VALUE>02016R0399-20240710</VALUE>
            </IDENTIFIER>
            <IDENTIFIER>
                <VALUE>02016R0399-20251012</VALUE>
            </IDENTIFIER>
            <IDENTIFIER>
                <VALUE>not-a-celex</VALUE>
            </IDENTIFIER>
        </WORK>
    </NOTICE>
    """

    identifiers = (
        parse_tree_notice_identifiers(
            raw
        )
    )

    assert identifiers == (
        "02016R0399-20240710",
        "02016R0399-20251012",
        "32016R0399",
    )


def test_tree_notice_handles_treaty_celex_correctly():
    raw = b"""<NOTICE>
        <IDENTIFIER>
            <VALUE>12016M/TXT</VALUE>
        </IDENTIFIER>
        <IDENTIFIER>
            <VALUE>02016M/TXT</VALUE>
        </IDENTIFIER>
        <IDENTIFIER>
            <VALUE>02016M/TXT-20250315</VALUE>
        </IDENTIFIER>
    </NOTICE>"""

    identifiers = (
        parse_tree_notice_identifiers(
            raw
        )
    )

    selected = (
        select_latest_consolidated_celex(
            "12016M/TXT",
            identifiers,
        )
    )

    assert (
        selected
        == "02016M/TXT-20250315"
    )


def test_tree_notice_extracts_eli_uris():
    raw = b"""<NOTICE>
        <URI>http://data.europa.eu/eli/reg/2016/399/oj</URI>
        <SAMEAS href="https://data.europa.eu/eli/reg/2016/399/oj" />
        <URI>https://example.test/not-eli</URI>
    </NOTICE>"""

    uris = (
        parse_tree_notice_eli_uris(
            raw
        )
    )

    assert uris == (
        "http://data.europa.eu/eli/reg/2016/399/oj",
        "https://data.europa.eu/eli/reg/2016/399/oj",
    )


def test_invalid_tree_notice_fails_closed():
    with pytest.raises(
        ValueError
    ):
        parse_tree_notice_identifiers(
            b"<broken"
        )


def test_lists_consolidated_revisions_newest_first():
    from backend.knowledge.eurlex.parser import (
        list_consolidated_celex_revisions,
    )

    revisions = (
        list_consolidated_celex_revisions(
            "32016R0399",
            [
                "32016R0399",
                "02016R0399-20170407",
                "02016R0399-20251012",
                "02016R0399-20240710",
            ],
        )
    )

    assert revisions == (
        "02016R0399-20251012",
        "02016R0399-20240710",
        "02016R0399-20170407",
    )


def test_lists_treaty_revisions_newest_first():
    from backend.knowledge.eurlex.parser import (
        list_consolidated_celex_revisions,
    )

    revisions = (
        list_consolidated_celex_revisions(
            "12016M/TXT",
            [
                "02016M/TXT",
                "02016M/TXT-20250315",
            ],
        )
    )

    assert revisions == (
        "02016M/TXT-20250315",
        "02016M/TXT",
    )
