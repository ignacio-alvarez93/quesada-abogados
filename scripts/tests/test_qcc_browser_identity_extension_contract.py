from pathlib import Path


ROOT = Path(
    "chrome_extension/qcc"
)

IDENTITY = (
    ROOT
    / "shared"
    / "browser_identity.js"
)

WORKER = (
    ROOT
    / "background"
    / "service_worker.js"
)

HTML = (
    ROOT
    / "sidepanel"
    / "index.html"
)

SIDEPANEL = (
    ROOT
    / "sidepanel"
    / "sidepanel.js"
)


def _read(
    path,
):
    return path.read_text(
        encoding="utf-8"
    )


def test_browser_identity_is_persistent_profile_local_storage():
    text = _read(
        IDENTITY
    )

    assert (
        "QCC_BROWSER_IDENTITY_V1"
        in text
    )

    assert (
        '"qcc:browser-profile-key:v1"'
        in text
    )

    assert (
        ".storage"
        in text
    )

    assert (
        "?.local"
        in text
    )

    assert (
        "async function read()"
        in text
    )

    assert (
        "async function bind("
        in text
    )

    assert (
        "async function clear()"
        in text
    )


def test_browser_identity_does_not_invent_identity():
    text = _read(
        IDENTITY
    )

    assert (
        "randomUUID"
        not in text
    )

    assert (
        "qcc_assisted"
        not in text
    )

    assert (
        "crypto.random"
        not in text
    )

    assert (
        "return null;"
        in text
    )


def test_worker_loads_identity_before_runtime_code():
    text = _read(
        WORKER
    )

    identity_index = text.index(
        '"../shared/browser_identity.js"'
    )

    acquisition_index = text.index(
        '"../shared/acquisition_policy.js"'
    )

    assert (
        identity_index
        < acquisition_index
    )


def test_sidepanel_loads_identity_before_sidepanel_js():
    text = _read(
        HTML
    )

    identity_index = text.index(
        '../shared/browser_identity.js'
    )

    sidepanel_index = text.index(
        'src="sidepanel.js"'
    )

    assert (
        identity_index
        < sidepanel_index
    )


def test_manual_capture_transports_browser_profile_key():
    text = _read(
        SIDEPANEL
    )

    start = text.index(
        "async function "
        "submitSiteArchitectureCapture("
    )

    block = text[
        start:
        start + 900
    ]

    assert (
        "QccBrowserIdentity"
        in block
    )

    assert (
        ".read()"
        in block
    )

    assert (
        "browser_profile_key:"
        in block
    )


def test_automatic_capture_transports_browser_profile_key():
    text = _read(
        WORKER
    )

    start = text.index(
        "async function "
        "qccSubmitAutomaticDomCapture("
    )

    block = text[
        start:
        start + 1400
    ]

    assert (
        "QccBrowserIdentity"
        in block
    )

    assert (
        "browser_profile_key:"
        in block
    )


def test_same_document_observe_transports_browser_profile_key():
    text = _read(
        WORKER
    )

    start = text.index(
        "async function "
        "qccSubmitAutomaticDomObservation("
    )

    block = text[
        start:
        start + 1600
    ]

    assert (
        "QccBrowserIdentity"
        in block
    )

    assert (
        "browser_profile_key:"
        in block
    )


def test_identity_is_transport_metadata_not_capture_data():
    worker = _read(
        WORKER
    )

    sidepanel = _read(
        SIDEPANEL
    )

    assert (
        "capture.browser_profile_key"
        not in worker
    )

    assert (
        "capture.browser_profile_key"
        not in sidepanel
    )
