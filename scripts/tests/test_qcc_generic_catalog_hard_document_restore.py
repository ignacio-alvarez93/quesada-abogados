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


def hard_restore_block():
    text = source()

    start = text.index(
        "QCC_GENERIC_CATALOG_HARD_DOCUMENT_RESTORE_V1"
    )

    end = text.index(
        "async function runGenericCatalogCausalProbe(",
        start,
    )

    return text[start:end]


def executor_block():
    text = source()

    start = text.index(
        "async function runGenericCatalogCausalProbe("
    )

    end = text.index(
        "function setCatalogSelectionInPage(",
        start,
    )

    return text[start:end]


def test_hard_restore_requires_discovery_policy():
    text = hard_restore_block()

    assert (
        "active_discovery"
        in text
    )

    assert (
        "active_catalog_probe"
        in text
    )

    assert (
        "decision?.allowed !== true"
        in text
    )


def test_hard_restore_requires_same_physical_context():
    text = hard_restore_block()

    assert (
        "QCC_GENERIC_CATALOG_HARD_RESTORE_TAB_CHANGED"
        in text
    )

    assert (
        "QCC_GENERIC_CATALOG_HARD_RESTORE_URL_CHANGED"
        in text
    )

    assert (
        "QCC_GENERIC_CATALOG_HARD_RESTORE_PROFILE_CHANGED"
        in text
    )

    assert (
        "QCC_GENERIC_CATALOG_HARD_RESTORE_TWIN_CHANGED"
        in text
    )


def test_hard_restore_uses_tab_reload_not_page_script_reload():
    text = hard_restore_block()

    assert (
        "chrome.tabs.reload("
        in text
    )

    assert (
        "location.reload("
        not in text
    )

    assert (
        "window.location.reload("
        not in text
    )


def test_hard_restore_waits_for_complete_document():
    text = hard_restore_block()

    assert (
        'current.status\n'
        '        === "complete"'
        in text
    )

    assert (
        "QCC_GENERIC_CATALOG_HARD_RESTORE_DOCUMENT_TIMEOUT"
        in text
    )


def test_executor_uses_hard_restore_only_after_soft_mismatch():
    text = executor_block()

    soft = text.index(
        "qccGenericCatalogPageRestoreSelection"
    )

    mismatch = text.index(
        "restorationVerification\n"
        "          ?.exact !== true",
        soft,
    )

    hard = text.index(
        "qccGenericCatalogHardDocumentRestore(",
        mismatch,
    )

    assert (
        soft
        < mismatch
        < hard
    )


def test_executor_recompares_before_after_hard_restore():
    text = executor_block()

    hard = text.index(
        "qccGenericCatalogHardDocumentRestore("
    )

    compare = text.index(
        "compareMainCatalogCaptures(",
        hard,
    )

    assert compare > hard


def test_hard_restore_is_provider_neutral():
    text = hard_restore_block().lower()

    assert "red_sara" not in text
    assert "redsara" not in text
    assert "mercurio" not in text
    assert "dnt-select" not in text
    assert "dnt-option" not in text


def test_result_exposes_hard_restore_evidence():
    text = executor_block()

    assert (
        "hard_document_restore:"
        in text
    )

    assert (
        "hardDocumentRestore"
        in text
    )
