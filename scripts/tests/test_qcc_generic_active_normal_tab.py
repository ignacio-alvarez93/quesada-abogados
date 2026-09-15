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


def resolver_block():
    text = source()

    start = text.index(
        "QCC_GENERIC_ACTIVE_NORMAL_WEB_TAB_V1"
    )

    end = text.index(
        "async function inspectActiveTabDom()",
        start,
    )

    return text[
        start:end
    ]


def test_resolver_uses_normal_browser_window():
    text = resolver_block()

    assert (
        "chrome.windows.getLastFocused"
        in text
    )

    assert (
        '"normal"'
        in text
    )

    assert (
        "candidate?.active === true"
        in text
    )


def test_resolver_does_not_depend_on_last_focused_tab_query():
    text = resolver_block()

    assert (
        "lastFocusedWindow:"
        not in text
    )

    assert (
        "chrome.tabs.query({"
        not in text
    )


def test_resolver_can_observe_location_href():
    text = resolver_block()

    assert (
        "chrome.scripting.executeScript"
        in text
    )

    assert (
        "globalThis.location?.href"
        in text
    )

    assert (
        'world:\n            "ISOLATED"'
        in text
    )


def test_resolver_accepts_only_http_web_pages():
    text = resolver_block()

    assert (
        'parsed.protocol !== "http:"'
        in text
    )

    assert (
        'parsed.protocol !== "https:"'
        in text
    )


def test_generic_harvest_uses_shared_resolver():
    text = source()

    start = text.index(
        "async function qccGenericHarvestActiveTab()"
    )

    end = text.index(
        "async function resolveGenericHarvestActivePolicy()",
        start,
    )

    block = text[
        start:end
    ]

    assert (
        "qccResolveActiveNormalWebTab()"
        in block
    )

    assert (
        "lastFocusedWindow:"
        not in block
    )


def test_dom_inspector_uses_shared_resolver():
    text = source()

    start = text.index(
        "async function inspectActiveTabDom()"
    )

    end = text.index(
        "function normalizedCatalogSelector(",
        start,
    )

    block = text[
        start:end
    ]

    assert (
        "qccResolveActiveNormalWebTab()"
        in block
    )

    assert (
        "lastFocusedWindow:"
        not in block
    )
