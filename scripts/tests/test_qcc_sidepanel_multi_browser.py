from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

JS = (
    ROOT
    / "chrome_extension"
    / "qcc"
    / "sidepanel"
    / "sidepanel.js"
)

HTML = (
    ROOT
    / "chrome_extension"
    / "qcc"
    / "sidepanel"
    / "index.html"
)


def _read(path):
    return path.read_text(
        encoding="utf-8"
    )


def test_multi_browser_surface_exists():
    html = _read(
        HTML
    )

    for element_id in (
        "browser-profile-selector",
        "browser-view-mode",
        "browser-profile-bind-input",
        "browser-profile-bind",
        "browser-context-note",
    ):
        assert (
            f'id="{element_id}"'
            in html
        )


def test_sidepanel_declares_own_and_viewed_identity():
    js = _read(
        JS
    )

    for token in (
        "qccOwnBrowserProfileKey",
        "qccViewedBrowserProfileKey",
        "qccOwnSessionId",
        "qccViewedSessionId",
        "qccKnownBrowsers",
    ):
        assert token in js


def test_multi_browser_read_endpoints_are_known():
    js = _read(
        JS
    )

    assert (
        "/qcc/browsers"
        in js
    )

    assert (
        "?browser_profile_key="
        in js
    )

    assert (
        "encodeURIComponent("
        in js
    )


def test_own_view_comparison_is_explicit():
    js = _read(
        JS
    )

    start = js.index(
        "function qccIsOwnBrowserView("
    )

    end = js.index(
        "function qccBrowserSummaryFor(",
        start,
    )

    block = js[
        start:end
    ]

    assert (
        "qccOwnBrowserProfileKey"
        in block
    )

    assert (
        "qccViewedBrowserProfileKey"
        in block
    )

    assert (
        "==="
        in block
    )


def test_browser_summary_lookup_uses_profile_key():
    js = _read(
        JS
    )

    start = js.index(
        "function qccBrowserSummaryFor("
    )

    end = js.index(
        "function showEmptyContext(",
        start,
    )

    block = js[
        start:end
    ]

    assert (
        "qccKnownBrowsers.find("
        in block
    )

    assert (
        "browser_profile_key"
        in block
    )


def test_h2c_action_authority_is_named_own_session():
    js = _read(
        JS
    )

    start = js.index(
        "async function submitSessionAction("
    )

    end = js.index(
        "function setBridgeState(",
        start,
    )

    block = js[
        start:end
    ]

    assert (
        "qccOwnSessionId"
        in block
    )

    assert (
        "qccActiveSessionId"
        not in block
    )


def test_h2d1_render_session_cannot_set_own_session():
    js = _read(
        JS
    )

    start = js.index(
        "function renderSession("
    )

    end = js.index(
        "function hideLiveNavigation(",
        start,
    )

    block = js[
        start:end
    ]

    assert (
        "qccViewedSessionId ="
        in block
    )

    assert (
        "qccOwnSessionId ="
        not in block
    )


def test_h2d1_own_session_comes_from_profile_scoped_context():
    js = _read(
        JS
    )

    start = js.index(
        "async function checkContext("
    )

    end = js.index(
        "async function checkBridgeHealth(",
        start,
    )

    block = js[
        start:end
    ]

    assert (
        "qccBrowserContextUrl("
        in block
    )

    assert (
        "qccOwnBrowserProfileKey"
        in block
    )

    assert (
        "qccOwnSessionId ="
        in block
    )

    assert (
        "ownContext"
        in block
    )


def test_h2d1_initialization_reads_persistent_browser_identity():
    js = _read(
        JS
    )

    assert (
        "async function initializeQccShell("
        in js
    )

    assert (
        ".QccBrowserIdentity"
        in js
    )

    assert (
        ".read()"
        in js
    )


def test_h2d2a_registry_profiles_are_projected():
    js = _read(
        JS
    )

    start = js.index(
        "function renderOwnBrowserBinding("
    )

    end = js.index(
        "async function handleBrowserProfileBind(",
        start,
    )

    block = js[
        start:end
    ]

    assert (
        "qccKnownBrowsers.map("
        in block
    )

    assert (
        "browser_profile_key"
        in block
    )

    assert (
        "qccBrowserOptionLabel("
        in block
    )

    assert (
        "qccOwnBrowserProfileKey"
        in block
    )

    # D2-B será quien active el cambio remoto.
    assert (
        "profileKeys.length <= 1"
        in block
    )


def test_h2d2a_own_profile_is_sorted_first():
    js = _read(
        JS
    )

    start = js.index(
        "function renderOwnBrowserBinding("
    )

    end = js.index(
        "async function handleBrowserProfileBind(",
        start,
    )

    block = js[
        start:end
    ]

    assert (
        "left === qccOwnBrowserProfileKey"
        in block
    )

    assert (
        "right === qccOwnBrowserProfileKey"
        in block
    )


def test_h2d2a_unbound_browser_does_not_adopt_registry_identity():
    js = _read(
        JS
    )

    start = js.index(
        "function renderOwnBrowserBinding("
    )

    end = js.index(
        "async function handleBrowserProfileBind(",
        start,
    )

    block = js[
        start:end
    ]

    assert (
        "qccOwnBrowserProfileKey\n"
        "      ? Array.from("
        in block
    )




def test_h2d2b_selector_handler_changes_only_viewed_profile():
    js = _read(
        JS
    )

    start = js.index(
        "async function "
        "handleBrowserProfileSelection("
    )

    end = js.index(
        "async function "
        "handleBrowserProfileBind(",
        start,
    )

    block = js[
        start:end
    ]

    assert (
        "qccViewedBrowserProfileKey ="
        in block
    )

    assert (
        "qccOwnBrowserProfileKey ="
        not in block
    )

    assert (
        ".bind("
        not in block
    )


def test_h2d2b_own_context_and_viewed_context_are_separate():
    js = _read(
        JS
    )

    start = js.index(
        "async function checkContext("
    )

    end = js.index(
        "async function checkBridgeHealth(",
        start,
    )

    block = js[
        start:end
    ]

    assert "ownContext" in block
    assert "viewedContext" in block

    assert (
        "qccOwnSessionId ="
        in block
    )

    assert (
        "qccViewedBrowserProfileKey"
        in block
    )

    assert (
        "qccBrowserContextUrl("
        in block
    )


def test_h2d2b_remote_submit_has_hard_guard():
    js = _read(
        JS
    )

    start = js.index(
        "async function submitSessionAction("
    )

    end = js.index(
        "function setBridgeState(",
        start,
    )

    block = js[
        start:end
    ]

    assert (
        "qccOwnSessionId"
        in block
    )

    assert (
        "qccViewedSessionId"
        in block
    )

    assert (
        "qccIsOwnBrowserView()"
        in block
    )

    assert (
        "QCC_REMOTE_VIEW_READ_ONLY"
        in block
    )


def test_h2d2b_selector_remains_disabled_until_ui_guard():
    js = _read(
        JS
    )

    start = js.index(
        "function renderOwnBrowserBinding("
    )

    end = js.index(
        "async function "
        "handleBrowserProfileSelection(",
        start,
    )

    block = js[
        start:end
    ]

    assert (
        "profileKeys.length <= 1"
        in block
    )



def test_h2d2c_remote_view_is_visually_explicit():
    js = _read(JS)

    assert '"VISTA REMOTA"' in js
    assert "Solo lectura." in js
    assert (
        "qcc-browser-view-mode--remote"
        in js
    )


def test_h2d2c_selector_is_wired_to_view_handler():
    js = _read(JS)

    start = js.index(
        "async function initializeQccShell("
    )

    end = js.index(
        "const QCC_CATALOG_HARVEST_MAX_VALUES",
        start,
    )

    block = js[
        start:end
    ]

    assert (
        '"browser-profile-selector"'
        in block
    )

    assert (
        'addEventListener(\n'
        '      "change"'
        in block
    )

    assert (
        "handleBrowserProfileSelection("
        in block
    )

    assert (
        "browserSelector.value"
        in block
    )

def test_h2d2c_remote_document_actions_are_hidden():
    js = _read(JS)

    start = js.index(
        "function renderSession("
    )

    end = js.index(
        "function hideLiveNavigation(",
        start,
    )

    block = js[start:end]

    assert "ownInteractiveSession" in block
    assert "qccIsOwnBrowserView()" in block
    assert "qccOwnSessionId" in block

    start_actions = block[
        block.index(
            "const canStartDocuments"
        ):
        block.index(
            "const documentIndex"
        )
    ]

    review_actions = block[
        block.index(
            "const canReviewDocument"
        ):
    ]

    assert (
        "ownInteractiveSession"
        in start_actions
    )

    assert (
        "ownInteractiveSession"
        in review_actions
    )


def test_h2d2c_remote_submit_still_has_second_guard():
    js = _read(JS)

    start = js.index(
        "async function submitSessionAction("
    )

    end = js.index(
        "function setBridgeState(",
        start,
    )

    block = js[start:end]

    assert "QCC_REMOTE_VIEW_READ_ONLY" in block
    assert "qccIsOwnBrowserView()" in block
    assert "qccViewedSessionId" in block
    assert "qccOwnSessionId" in block


def test_h2d2c_bridge_down_clears_action_authority():
    js = _read(JS)

    start = js.index(
        "async function checkBridgeHealth("
    )

    end = js.index(
        "async function handleDocumentsStart(",
        start,
    )

    block = js[start:end]

    assert "qccOwnSessionId =" in block
    assert "qccViewedSessionId =" in block
