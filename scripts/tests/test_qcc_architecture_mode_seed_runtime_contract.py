from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

WORKER = (
    ROOT
    / "chrome_extension"
    / "qcc"
    / "background"
    / "service_worker.js"
)

SIDEPANEL = (
    ROOT
    / "chrome_extension"
    / "qcc"
    / "sidepanel"
    / "sidepanel.js"
)


def _read(path):
    return path.read_text(
        encoding="utf-8"
    )


def test_worker_mode_bootstrap_exists():
    js = _read(WORKER)

    assert (
        "QCC_ARCHITECTURE_PROFILE_MODE_BOOTSTRAP_V1"
        in js
    )

    assert (
        "async function "
        "qccSeedArchitectureProfileDefaultFromRegistry("
        in js
    )

    assert (
        "QCC_BROWSER_MODE_SEED_BROWSERS_URL"
        in js
    )

    assert (
        "/qcc/browsers"
        in js
    )


def test_worker_checks_initialization_before_registry_fetch():
    js = _read(WORKER)

    start = js.index(
        "async function "
        "qccSeedArchitectureProfileDefaultFromRegistry("
    )

    end = js.index(
        "QCC_ARCHITECTURE_AUTOMATIC_CAPTURE_GATE_V1",
        start,
    )

    block = js[start:end]

    snapshot = block.index(
        "snapshotForProfile("
    )

    initialized = block.index(
        "default_initialized",
        snapshot,
    )

    fetch = block.index(
        "await fetch(",
        initialized,
    )

    assert (
        snapshot
        < initialized
        < fetch
    )


def test_worker_matches_exact_own_profile_and_mode():
    js = _read(WORKER)

    start = js.index(
        "async function "
        "qccSeedArchitectureProfileDefaultFromRegistry("
    )

    end = js.index(
        "QCC_ARCHITECTURE_AUTOMATIC_CAPTURE_GATE_V1",
        start,
    )

    block = js[start:end]

    assert (
        "browser_profile_key"
        in block
    )

    assert (
        "browser_session_mode"
        in block
    )

    assert (
        "normalizeBrowserSessionMode("
        in block
    )

    assert (
        "seedProfileDefaultFromMode("
        in block
    )


def test_worker_bootstrap_contains_no_dom_or_permission_action():
    js = _read(WORKER)

    start = js.index(
        "async function "
        "qccSeedArchitectureProfileDefaultFromRegistry("
    )

    end = js.index(
        "QCC_ARCHITECTURE_AUTOMATIC_CAPTURE_GATE_V1",
        start,
    )

    block = js[start:end]

    for forbidden in (
        "inspectSpecificTabDom(",
        "captureVisibleTab(",
        "pageCapture.saveAsMHTML",
        "permissions.request(",
        "scripting.executeScript(",
    ):
        assert forbidden not in block


def test_gate_bootstraps_before_policy_resolution():
    js = _read(WORKER)

    start = js.index(
        "async function "
        "qccAutomaticArchitectureCaptureDecision("
    )

    end = js.index(
        "async function qccAutomaticCapturePermissions(",
        start,
    )

    block = js[start:end]

    seed = block.index(
        "qccSeedArchitectureProfileDefaultFromRegistry("
    )

    resolve = block.index(
        "await policy.resolve(",
        seed,
    )

    assert seed < resolve


def test_sidepanel_seed_uses_only_own_profile():
    js = _read(SIDEPANEL)

    start = js.index(
        "async function "
        "qccSeedOwnArchitectureProfileDefault("
    )

    end = js.index(
        "async function refreshKnownBrowsers(",
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
        "qccBrowserSummaryFor("
        in block
    )

    assert (
        "browser_session_mode"
        in block
    )

    assert (
        "seedProfileDefaultFromMode("
        in block
    )


def test_known_browser_refresh_can_seed_own_profile():
    js = _read(SIDEPANEL)

    start = js.index(
        "async function refreshKnownBrowsers("
    )

    end = js.index(
        "function qccBrowserOptionLabel(",
        start,
    )

    block = js[start:end]

    inventory = block.index(
        "qccKnownBrowsers ="
    )

    seed = block.index(
        "await qccSeedOwnArchitectureProfileDefault();",
        inventory,
    )

    assert inventory < seed


def test_architecture_manager_seeds_before_snapshot():
    js = _read(SIDEPANEL)

    start = js.index(
        "async function refreshArchitectureManager("
    )

    end = js.index(
        "async function mutateArchitectureOriginPolicy(",
        start,
    )

    block = js[start:end]

    seed = block.index(
        "await qccSeedOwnArchitectureProfileDefault();"
    )

    snapshot = block.index(
        ".snapshotForProfile(",
        seed,
    )

    assert seed < snapshot


def test_runtime_seed_has_no_profile_name_heuristics():
    worker = _read(WORKER)

    start = worker.index(
        "async function "
        "qccSeedArchitectureProfileDefaultFromRegistry("
    )

    end = worker.index(
        "QCC_ARCHITECTURE_AUTOMATIC_CAPTURE_GATE_V1",
        start,
    )

    block = worker[
        start:end
    ].lower()

    for forbidden in (
        "whatsapp",
        "mercurio",
        "instagram",
        "youtube",
        "tiktok",
        "dehu",
    ):
        assert forbidden not in block
