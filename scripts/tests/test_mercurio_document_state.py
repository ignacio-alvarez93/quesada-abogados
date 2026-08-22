import json
from pathlib import Path

from backend.automation.mercurio_document_state import (
    build_mercurio_document_state,
    parse_required_codes,
)


FIXTURES = (
    Path(__file__).parent
    / "fixtures"
    / "mercurio"
)


def load_fixture(
    filename,
):
    return json.loads(
        (
            FIXTURES
            / filename
        ).read_text(
            encoding="utf-8"
        )
    )


def test_parse_required_codes_preserves_order():
    assert (
        parse_required_codes(
            "1|39|47"
        )
        == (
            "1",
            "39",
            "47",
        )
    )


def test_parse_required_codes_ignores_empty_and_duplicates():
    assert (
        parse_required_codes(
            "1||39|1|47|"
        )
        == (
            "1",
            "39",
            "47",
        )
    )


def test_empty_document_page_detects_all_required_as_missing():
    state = (
        build_mercurio_document_state(
            load_fixture(
                "documents_empty.json"
            )
        )
    )

    assert state.page_detected is True
    assert (
        state.contract_compatible
        is True
    )

    assert state.required_count == 3
    assert (
        state.uploaded_required_count
        == 0
    )

    assert (
        state.missing_required_codes
        == (
            "1",
            "39",
            "47",
        )
    )

    assert (
        state.documentation_complete
        is False
    )


def test_partial_document_page_distinguishes_optional_uploads():
    state = (
        build_mercurio_document_state(
            load_fixture(
                "documents_partial.json"
            )
        )
    )

    assert state.required_count == 3

    assert (
        state.uploaded_required_count
        == 2
    )

    assert (
        state.missing_required_codes
        == (
            "47",
        )
    )

    assert (
        state.documentation_complete
        is False
    )

    assert {
        item.code
        for item
        in state.uploaded_documents
    } == {
        "1",
        "39",
        "51",
    }


def test_complete_document_page_is_complete():
    state = (
        build_mercurio_document_state(
            load_fixture(
                "documents_complete.json"
            )
        )
    )

    assert state.required_count == 3

    assert (
        state.uploaded_required_count
        == 3
    )

    assert (
        state.missing_required_codes
        == ()
    )

    assert (
        state.documentation_complete
        is True
    )


def test_zero_required_documents_is_valid_complete_state():
    state = (
        build_mercurio_document_state(
            load_fixture(
                "documents_zero_required.json"
            )
        )
    )

    assert state.required_count == 0

    assert (
        state.missing_required_codes
        == ()
    )

    assert (
        state.documentation_complete
        is True
    )


def test_upload_confirmation_uses_filename_code_and_hash():
    state = (
        build_mercurio_document_state(
            load_fixture(
                "documents_complete.json"
            )
        )
    )

    assert state.is_uploaded(
        filename=(
            r"C:\fake\path"
            r"\seguro_prueba.pdf"
        ),
        code="47",
    )

    assert not state.is_uploaded(
        filename="seguro_prueba.pdf",
        code="39",
    )

    assert not state.is_uploaded(
        filename="archivo_inexistente.pdf",
        code="47",
    )


def test_upload_without_hash_is_not_confirmed_by_default():
    snapshot = load_fixture(
        "documents_complete.json"
    )

    snapshot[
        "uploaded_rows"
    ][1][
        "hash"
    ] = ""

    state = (
        build_mercurio_document_state(
            snapshot
        )
    )

    assert not state.is_uploaded(
        filename="seguro_prueba.pdf",
        code="47",
    )

    assert state.is_uploaded(
        filename="seguro_prueba.pdf",
        code="47",
        require_hash=False,
    )


def test_incompatible_dom_never_claims_documentation_complete():
    snapshot = load_fixture(
        "documents_complete.json"
    )

    snapshot[
        "markers"
    ][
        "uploaded_table"
    ] = False

    state = (
        build_mercurio_document_state(
            snapshot
        )
    )

    assert (
        state.contract_compatible
        is False
    )

    assert (
        state.documentation_complete
        is False
    )


def test_required_labels_follow_dynamic_mercurio_codes():
    state = (
        build_mercurio_document_state(
            load_fixture(
                "documents_complete.json"
            )
        )
    )

    labels = {
        item.code:
            item.label
        for item
        in state.required_documents
    }

    assert labels == {
        "1":
            "Pasaporte",
        "39":
            "Recursos económicos",
        "47":
            "Seguro de enfermedad",
    }


def test_state_is_serializable_for_future_qcc_reporting():
    state = (
        build_mercurio_document_state(
            load_fixture(
                "documents_complete.json"
            )
        )
    )

    payload = state.as_dict()

    assert (
        payload[
            "documentation_complete"
        ]
        is True
    )

    assert (
        payload[
            "required_count"
        ]
        == 3
    )

    assert (
        payload[
            "uploaded_required_count"
        ]
        == 3
    )

    assert (
        payload[
            "missing_required_codes"
        ]
        == []
    )
