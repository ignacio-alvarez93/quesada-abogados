import json
from pathlib import Path

import pytest

from backend.automation.mercurio_document_dom_reader import (
    MERCURIO_DOCUMENT_SNAPSHOT_EXPRESSION,
    MercurioDocumentDomReadError,
    read_mercurio_document_snapshot,
    read_mercurio_document_state,
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


class FakeEvaluateBrowser:
    def __init__(
        self,
        payload,
    ):
        self.payload = payload
        self.expressions = []

    def evaluate(
        self,
        expression,
    ):
        self.expressions.append(
            expression
        )

        return self.payload


class FakeWebDriverBrowser:
    def __init__(
        self,
        payload,
    ):
        self.payload = payload
        self.scripts = []

    def execute_script(
        self,
        script,
    ):
        self.scripts.append(
            script
        )

        return self.payload


class UnsupportedBrowser:
    pass


def test_reader_prefers_cdp_evaluate():
    fixture = load_fixture(
        "documents_partial.json"
    )

    browser = FakeEvaluateBrowser(
        fixture
    )

    result = (
        read_mercurio_document_snapshot(
            browser
        )
    )

    assert result == fixture

    assert len(
        browser.expressions
    ) == 1

    assert (
        "#listaIdsDocOb"
        in browser.expressions[0]
    )


def test_reader_supports_execute_script_fallback():
    fixture = load_fixture(
        "documents_complete.json"
    )

    browser = FakeWebDriverBrowser(
        fixture
    )

    result = (
        read_mercurio_document_snapshot(
            browser
        )
    )

    assert result == fixture

    assert len(
        browser.scripts
    ) == 1

    assert (
        browser.scripts[0]
        .lstrip()
        .startswith("return ")
    )


def test_reader_rejects_unsupported_browser():
    with pytest.raises(
        MercurioDocumentDomReadError,
        match=(
            "MERCURIO_DOCUMENT_DOM_"
            "EVALUATION_UNSUPPORTED"
        ),
    ):
        read_mercurio_document_snapshot(
            UnsupportedBrowser()
        )


def test_reader_rejects_non_mapping_payload():
    browser = FakeEvaluateBrowser(
        "unexpected"
    )

    with pytest.raises(
        MercurioDocumentDomReadError,
        match=(
            "MERCURIO_DOCUMENT_DOM_"
            "INVALID_PAYLOAD"
        ),
    ):
        read_mercurio_document_snapshot(
            browser
        )


def test_reader_builds_partial_state():
    browser = FakeEvaluateBrowser(
        load_fixture(
            "documents_partial.json"
        )
    )

    state = (
        read_mercurio_document_state(
            browser
        )
    )

    assert (
        state.contract_compatible
        is True
    )

    assert (
        state.required_count
        == 3
    )

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


def test_reader_builds_complete_state():
    browser = FakeEvaluateBrowser(
        load_fixture(
            "documents_complete.json"
        )
    )

    state = (
        read_mercurio_document_state(
            browser
        )
    )

    assert (
        state.required_count
        == 3
    )

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


def test_dom_expression_contains_observed_contract():
    expression = (
        MERCURIO_DOCUMENT_SNAPSHOT_EXPRESSION
    )

    expected = (
        "#listaIdsDocOb",
        ".listaObligatoria [iddocob]",
        "#docAdjuntarAdjuntos",
        "#tabla_datos_adj tbody tr",
        "#tbAdjuntos input[type='file']",
        "#continuaNot",
    )

    for selector in expected:
        assert (
            selector
            in expression
        )


def test_dom_expression_is_read_only():
    expression = (
        MERCURIO_DOCUMENT_SNAPSHOT_EXPRESSION
    )

    forbidden = (
        ".click(",
        "dispatchEvent(",
        "setAttribute(",
        "removeAttribute(",
        "appendChild(",
        "removeChild(",
        ".submit(",
        ".value =",
        ".checked =",
        "window.location =",
        "location.href =",
    )

    for token in forbidden:
        assert (
            token
            not in expression
        ), token


def test_dom_expression_does_not_use_dynamic_plupload_id():
    expression = (
        MERCURIO_DOCUMENT_SNAPSHOT_EXPRESSION
    )

    assert (
        "html5_1k0"
        not in expression
    )

    assert (
        "#tbAdjuntos input[type='file']"
        in expression
    )


def test_state_confirmation_survives_optional_documents():
    browser = FakeEvaluateBrowser(
        load_fixture(
            "documents_complete.json"
        )
    )

    state = (
        read_mercurio_document_state(
            browser
        )
    )

    assert state.is_uploaded(
        filename="seguro_prueba.pdf",
        code="47",
    )

    assert {
        item.code
        for item
        in state.uploaded_documents
    } == {
        "1",
        "39",
        "47",
        "51",
    }


def test_reader_has_no_forbidden_architectural_imports():
    import ast

    module_path = (
        Path(__file__).parents[2]
        / "backend"
        / "automation"
        / "mercurio_document_dom_reader.py"
    )

    tree = ast.parse(
        module_path.read_text(
            encoding="utf-8"
        )
    )

    imported_modules = []

    for node in ast.walk(tree):
        if isinstance(
            node,
            ast.Import,
        ):
            imported_modules.extend(
                alias.name
                for alias
                in node.names
            )

        elif isinstance(
            node,
            ast.ImportFrom,
        ):
            if node.module:
                imported_modules.append(
                    node.module
                )

    forbidden_prefixes = (
        "seleniumbase",
        "sqlite3",
        "supabase",
        "frontend",
        "backend.qcc",
    )

    assert not any(
        module == prefix
        or module.startswith(
            prefix + "."
        )
        for module
        in imported_modules
        for prefix
        in forbidden_prefixes
    ), imported_modules
