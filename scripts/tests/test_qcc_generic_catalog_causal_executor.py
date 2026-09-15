from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

WORKER = (
    ROOT
    / "chrome_extension"
    / "qcc"
    / "background"
    / "service_worker.js"
)


def source():
    return WORKER.read_text(
        encoding="utf-8"
    )


def executor_block():
    text = source()

    start = text.index(
        "QCC_GENERIC_CATALOG_CAUSAL_EXECUTOR_V1"
    )

    end = text.index(
        "function setCatalogSelectionInPage(",
        start,
    )

    return text[
        start:end
    ]


def test_generic_executor_supports_native_and_custom():
    text = executor_block()

    assert '"native_select"' in text
    assert '"custom_select"' in text

    assert (
        "qccGenericCatalogPageSetSelection"
        in text
    )

    assert (
        "qccGenericCatalogPageRestoreSelection"
        in text
    )


def test_generic_executor_uses_double_gate():
    text = executor_block()

    assert (
        "QccAcquisitionPolicy"
        in text
    )

    assert (
        "HARVEST_ALLOWED"
        in text
    )

    assert (
        "QccBrowserIdentity"
        in text
    )

    assert (
        "/qcc/auto-twin/catalog-probe-decision"
        in text
    )

    assert (
        "decision.allowed !== true"
        in text
    )


def test_generic_executor_fails_closed_when_bridge_unavailable():
    text = executor_block()

    assert (
        "QCC_GENERIC_CATALOG_PROBE_AUTHORITY_UNAVAILABLE"
        in text
    )

    assert (
        "AbortController"
        in text
    )


def test_custom_executor_uses_open_shadow_aria_surfaces():
    text = executor_block()

    assert (
        '[role="combobox"][aria-haspopup="listbox"]'
        in text
    )

    assert (
        '[role="option"]'
        in text
    )

    assert (
        'target.surface.click()'
        in text
    )


def test_custom_executor_falls_back_to_label_identity():
    text = executor_block()

    assert (
        "wantedLabel"
        in text
    )

    assert (
        "option.label"
        in text
    )

    assert (
        "=== wantedLabel"
        in text
    )


def test_custom_empty_restoration_uses_generic_aria_clear():
    text = executor_block()

    assert (
        '\'[role="button"][aria-label]\''
        in text
    )

    assert (
        '"ARIA_CLEAR_CLICK"'
        in text
    )

    assert (
        "clearControls.length"
        in text
    )


def test_executor_restores_inside_finally():
    text = executor_block()

    assert "finally {" in text

    finally_pos = text.index(
        "finally {"
    )

    restore_pos = text.index(
        "qccGenericCatalogPageRestoreSelection",
        finally_pos,
    )

    assert restore_pos > finally_pos

    assert (
        "compareMainCatalogCaptures("
        in text[
            finally_pos:
        ]
    )


def test_executor_does_not_submit_or_navigate():
    text = executor_block()

    assert ".submit(" not in text
    assert "requestSubmit(" not in text
    assert "location.href =" not in text
    assert "location.assign(" not in text
    assert "location.replace(" not in text


def test_executor_is_provider_neutral():
    text = executor_block().lower()

    assert "red_sara" not in text
    assert "redsara" not in text
    assert "mercurio" not in text
    assert "dnt-select" not in text
    assert "dnt-option" not in text


def test_message_surface_is_explicit():
    text = source()

    assert (
        "QCC_GENERIC_CATALOG_CAUSAL_PROBE_MESSAGE_V1"
        in text
    )

    assert (
        'message.type\n'
        '        !== "QCC_GENERIC_CATALOG_CAUSAL_PROBE"'
        in text
    )

    assert (
        "runGenericCatalogCausalProbe("
        in text
    )
