from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

QCC = (
    ROOT
    / "chrome_extension"
    / "qcc"
)

POLICY = (
    QCC
    / "shared"
    / "architecture_capture_policy.js"
)

WORKER = (
    QCC
    / "background"
    / "service_worker.js"
)

HTML = (
    QCC
    / "sidepanel"
    / "index.html"
)


def _read(path):
    return path.read_text(
        encoding="utf-8"
    )


def test_architecture_capture_policy_exists():
    assert POLICY.is_file()


def test_policy_identity_is_profile_plus_origin():
    js = _read(POLICY)

    assert (
        "browser_profile_key:"
        in js
    )

    assert "origin:" in js

    assert (
        "normalizeProfileKey("
        in js
    )

    assert (
        "normalizeOrigin("
        in js
    )


def test_unknown_profile_defaults_off():
    js = _read(POLICY)

    assert (
        '"PROFILE_DEFAULT_OFF"'
        in js
    )

    assert (
        "automatic_allowed:"
        in js
    )


def test_storage_failure_is_fail_closed():
    js = _read(POLICY)

    start = js.index(
        "async function resolve("
    )

    end = js.index(
        "async function setProfileDefault(",
        start,
    )

    block = js[start:end]

    assert '"STORAGE_ERROR"' in block

    storage_error = block.index(
        '"STORAGE_ERROR"'
    )

    before = block[
        max(
            0,
            storage_error - 350
        ):
        storage_error + 80
    ]

    assert (
        "catch (_)"
        in before
    )

    assert (
        "deniedResolution("
        in before
    )


def test_explicit_deny_precedes_allow_and_default():
    js = _read(POLICY)

    deny = js.index(
        "explicit === ORIGIN_DENY"
    )

    allow = js.index(
        "explicit === ORIGIN_ALLOW"
    )

    default = js.index(
        "PROFILE_DEFAULT_ON",
        allow,
    )

    assert deny < allow < default


def test_profile_default_is_explicit_not_name_heuristic():
    js = _read(POLICY)

    assert (
        "setProfileDefault("
        in js
    )

    resolve_start = js.index(
        "async function resolve("
    )

    resolve_end = js.index(
        "async function setProfileDefault(",
        resolve_start,
    )

    resolve_block = js[
        resolve_start:resolve_end
    ].lower()

    for forbidden in (
        "instagram",
        "youtube",
        "tiktok",
        "whatsapp",
        "mercurio",
    ):
        assert forbidden not in resolve_block

    assert (
        ".automatic_default"
        in resolve_block
    )

    assert (
        '"profile_default_on"'
        in resolve_block
    )

    assert (
        '"profile_default_off"'
        in resolve_block
    )


def test_policy_supports_allow_deny_and_clear():
    js = _read(POLICY)

    for token in (
        "allowOrigin",
        "denyOrigin",
        "clearOriginOverride",
        "ORIGIN_ALLOW",
        "ORIGIN_DENY",
    ):
        assert token in js


def test_policy_is_persistent_local_storage():
    js = _read(POLICY)

    assert (
        ".storage\n"
        "        ?.local"
        in js
    )

    assert (
        "qcc:architecture:capture-policy:v1"
        in js
    )


def test_worker_loads_policy_before_capture_runtime():
    js = _read(WORKER)

    assert (
        '"../shared/architecture_capture_policy.js"'
        in js
    )

    policy_pos = js.index(
        '"../shared/architecture_capture_policy.js"'
    )

    auto_pos = js.index(
        "QCC_AUTOMATIC_SITE_ARCHITECTURE_V1"
    )

    assert policy_pos < auto_pos


def test_sidepanel_loads_same_policy_module():
    html = _read(HTML)

    assert (
        '<script src="../shared/'
        'architecture_capture_policy.js"></script>'
        in html
    )


def test_arch_1a_does_not_yet_gate_automatic_capture():
    worker = _read(WORKER)

    auto_start = worker.index(
        "QCC_AUTOMATIC_SITE_ARCHITECTURE_V1"
    )

    auto_block = worker[
        auto_start:
    ]

    assert (
        ".QccArchitectureCapturePolicy"
        not in auto_block
    )
