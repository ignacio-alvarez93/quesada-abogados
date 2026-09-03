from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

JS = (
    ROOT
    / "chrome_extension"
    / "qcc"
    / "sidepanel"
    / "sidepanel.js"
)


def _read():
    return JS.read_text(
        encoding="utf-8"
    )


def _manager_block(js):
    start = js.index(
        "QCC_ARCHITECTURE_MANAGER_RUNTIME_V1"
    )

    end = js.index(
        "function initializeBrowserToolsDialog",
        start,
    )

    return js[start:end]


def test_manager_uses_own_browser_profile_only():
    js = _read()

    start = js.index(
        "async function qccArchitectureActiveTab("
    )

    end = js.index(
        "function initializeBrowserToolsDialog",
        start,
    )

    block = js[start:end]

    assert (
        "qccOwnBrowserProfileKey"
        in block
    )

    assert (
        "qccViewedBrowserProfileKey"
        not in block
    )

    assert (
        "qccViewedSessionId"
        not in block
    )


def test_manager_uses_active_tab_of_current_window():
    block = _manager_block(
        _read()
    )

    assert "chrome.tabs.query({" in block
    assert "active:" in block
    assert "currentWindow:" in block


def test_manager_uses_shared_capture_policy():
    block = _manager_block(
        _read()
    )

    for token in (
        "QccArchitectureCapturePolicy",
        ".snapshotForProfile(",
        ".resolve(",
        ".allowOrigin(",
        ".denyOrigin(",
        ".clearOriginOverride(",
        ".setProfileDefault(",
    ):
        assert token in block


def test_manager_does_not_request_chrome_permissions():
    block = _manager_block(
        _read()
    )

    assert "permissions.request" not in block
    assert "chrome.permissions" not in block


def test_manager_does_not_depend_on_bridge():
    block = _manager_block(
        _read()
    )

    assert "QCC_BRIDGE" not in block
    assert "fetch(" not in block


def test_manager_does_not_start_capture():
    block = _manager_block(
        _read()
    )

    for forbidden in (
        "QCC_DOM_INSPECT",
        "scheduleAutomaticSiteArchitectureCapture",
        "runAutomaticSiteArchitectureCapture",
        "QCC_SITE_ARCHITECTURE_DIRTY",
    ):
        assert forbidden not in block


def test_manager_renders_policy_and_origin_list():
    block = _manager_block(
        _read()
    )

    for token in (
        "architecture-current-profile",
        "architecture-current-origin",
        "architecture-current-policy",
        "architecture-current-source",
        "architecture-origin-list",
        "renderArchitectureOriginList",
    ):
        assert token in block


def test_dialog_open_refreshes_architecture_manager():
    js = _read()

    start = js.index(
        "function initializeBrowserToolsDialog"
    )

    end = js.index(
        "document.addEventListener(",
        start,
    )

    block = js[start:end]

    assert (
        "refreshArchitectureManager()"
        in block
    )


def test_allow_branch_is_structurally_valid():
    js = _read()

    start = js.index(
        "async function mutateArchitectureOriginPolicy("
    )

    end = js.index(
        "async function mutateArchitectureProfileDefault(",
        start,
    )

    block = js[start:end]

    allow_branch = block.index(
        'if (mutation === "ALLOW") {'
    )

    allow_call = block.index(
        "await context.policy.allowOrigin(",
        allow_branch,
    )

    deny_branch = block.index(
        '} else if (mutation === "DENY") {',
        allow_call,
    )

    assert (
        allow_branch
        < allow_call
        < deny_branch
    )


def test_policy_controls_are_wired():
    js = _read()

    start = js.index(
        "function initializeBrowserToolsDialog"
    )

    end = js.index(
        "document.addEventListener(",
        start,
    )

    block = js[start:end]

    for element_id in (
        "architecture-profile-default",
        "architecture-origin-allow",
        "architecture-origin-deny",
        "architecture-origin-inherit",
    ):
        assert element_id in block

    for mutation in (
        '"ALLOW"',
        '"DENY"',
        '"INHERIT"',
    ):
        assert mutation in block
