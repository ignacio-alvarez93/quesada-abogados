from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

POLICY = (
    ROOT
    / "chrome_extension"
    / "qcc"
    / "shared"
    / "architecture_capture_policy.js"
)


def _read():
    return POLICY.read_text(
        encoding="utf-8"
    )


def test_mode_seed_contract_exists():
    js = _read()

    assert (
        "QCC_ARCHITECTURE_PROFILE_MODE_SEED_V1"
        in js
    )

    assert (
        "async function seedProfileDefaultFromMode("
        in js
    )


def test_mode_mapping_is_explicit():
    js = _read()

    start = js.index(
        "async function seedProfileDefaultFromMode("
    )

    end = js.index(
        "async function setOriginMode(",
        start,
    )

    block = js[start:end]

    assert (
        'normalizedMode === "ASSISTED"'
        in block
    )

    assert (
        'normalizedMode === "PERSISTENT"'
        in block
    )

    # EPHEMERAL is therefore false, not inferred
    # from profile names or providers.
    assert (
        'profile.automatic_default ='
        in block
    )

    for forbidden in (
        "whatsapp",
        "mercurio",
        "instagram",
        "youtube",
        "tiktok",
    ):
        assert forbidden not in block.lower()


def test_seed_refuses_to_overwrite_initialized_profile():
    js = _read()

    start = js.index(
        "async function seedProfileDefaultFromMode("
    )

    end = js.index(
        "async function setOriginMode(",
        start,
    )

    block = js[start:end]

    initialized = block.index(
        "?.default_initialized"
    )

    early_return = block.index(
        "seeded:",
        initialized,
    )

    ensure = block.index(
        "ensureProfile(",
        early_return,
    )

    assert (
        initialized
        < early_return
        < ensure
    )


def test_manual_default_marks_profile_initialized():
    js = _read()

    start = js.index(
        "async function setProfileDefault("
    )

    end = js.index(
        "QCC_ARCHITECTURE_PROFILE_MODE_SEED_V1",
        start,
    )

    block = js[start:end]

    assert (
        "profile.default_initialized"
        in block
    )

    assert (
        '"MANUAL"'
        in block
    )


def test_legacy_profiles_are_protected():
    js = _read()

    start = js.index(
        "function sanitizeState("
    )

    end = js.index(
        "async function readState(",
        start,
    )

    block = js[start:end]

    assert (
        "hasInitializationMarker"
        in block
    )

    assert (
        '"LEGACY"'
        in block
    )

    assert (
        "defaultInitialized"
        in block
    )


def test_new_profiles_are_uninitialized():
    js = _read()

    start = js.index(
        "function ensureProfile("
    )

    end = js.index(
        "function deniedResolution(",
        start,
    )

    block = js[start:end]

    assert (
        "default_initialized:"
        in block
    )

    assert (
        "false"
        in block
    )

    assert (
        '"UNINITIALIZED"'
        in block

    )

def test_snapshot_exposes_seed_state():
    js = _read()

    start = js.index(
        "async function snapshotForProfile("
    )

    block = js[start:]

    assert (
        "default_initialized:"
        in block
    )

    assert (
        "default_source:"
        in block
    )


def test_seed_api_is_public():
    js = _read()

    assert (
        "seedProfileDefaultFromMode,"
        in js
    )

    assert (
        "normalizeBrowserSessionMode,"
        in js
    )
