from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

QCC = (
    ROOT
    / "chrome_extension"
    / "qcc"
)

CORE = (
    QCC
    / "sidepanel"
    / "sidepanel.js"
)

HTML = (
    QCC
    / "sidepanel"
    / "index.html"
)

WORKER = (
    QCC
    / "background"
    / "service_worker.js"
)

POLICY = (
    QCC
    / "shared"
    / "acquisition_policy.js"
)

MERCURIO_POLICY = (
    QCC
    / "shared"
    / "providers"
    / "mercurio_acquisition.js"
)

MERCURIO_UI = (
    QCC
    / "sidepanel"
    / "providers"
    / "mercurio.js"
)


def test_acquisition_policy_is_shared_artifact():
    assert POLICY.is_file()

    text = POLICY.read_text(
        encoding="utf-8"
    )

    required = (
        "QCC_ACQUISITION_POLICY_V1",
        '"SNAPSHOT_ONLY"',
        '"HARVEST_ALLOWED"',
        "globalThis.QccAcquisitionPolicy",
        "async function resolve(",
        "async function enableHarvestForUrl(",
        "async function disableHarvestForUrl(",
    )

    for literal in required:
        assert literal in text


def test_sidepanel_loads_policy_before_core():
    html = HTML.read_text(
        encoding="utf-8"
    )

    policy_position = html.index(
        'src="../shared/acquisition_policy.js"'
    )

    provider_position = html.index(
        'src="../shared/providers/mercurio_acquisition.js"'
    )

    core_position = html.index(
        'src="sidepanel.js"'
    )

    mercurio_ui_position = html.index(
        'src="providers/mercurio.js"'
    )

    assert (
        policy_position
        < provider_position
        < core_position
        < mercurio_ui_position
    )

def test_service_worker_loads_same_policy():
    worker = WORKER.read_text(
        encoding="utf-8"
    )

    assert (
        "QCC_SHARED_ACQUISITION_POLICY_WORKER_V1"
        in worker
    )

    assert (
        '"../shared/acquisition_policy.js"'
        in worker
    )

    assert (
        '"../shared/providers/mercurio_acquisition.js"'
        in worker
    )


def test_unknown_sites_default_to_snapshot_only():
    text = POLICY.read_text(
        encoding="utf-8"
    )

    assert (
        'mode:\n        SNAPSHOT_ONLY'
        in text
        or
        'mode:\n          SNAPSHOT_ONLY'
        in text
    )

    assert (
        'source:\n        "DEFAULT"'
        in text
        or
        'source:\n          "DEFAULT"'
        in text
    )


def test_harvest_opt_in_uses_session_storage():
    text = POLICY.read_text(
        encoding="utf-8"
    )

    required = (
        "chrome",
        "storage",
        "session",
        "SESSION_STORAGE_KEY",
        "SESSION_OPT_IN",
        "readSessionOrigins",
        "writeSessionOrigins",
    )

    for literal in required:
        assert literal in text

    assert "storage.local" not in text

    assert "localStorage" not in text


def test_policy_has_no_bridge_or_crm_runtime_dependency():
    text = POLICY.read_text(
        encoding="utf-8"
    )

    forbidden = (
        "fetch(",
        "QCC_BRIDGE_BASE_URL",
        "/qcc/",
        "chrome.runtime.sendMessage",
    )

    for literal in forbidden:
        assert literal not in text


def test_mercurio_lock_is_shared_provider_policy():
    assert MERCURIO_POLICY.is_file()

    text = MERCURIO_POLICY.read_text(
        encoding="utf-8"
    )

    assert (
        "QCC_MERCURIO_ACQUISITION_POLICY_V1"
        in text
    )

    assert (
        "https://mercurio.delegaciondelgobierno.gob.es"
        in text
    )

    assert (
        "policy.SNAPSHOT_ONLY"
        in text
    )

    assert (
        "locked:\n      true"
        in text
    )


def test_mercurio_ui_provider_does_not_own_acquisition_policy():
    text = MERCURIO_UI.read_text(
        encoding="utf-8"
    )

    assert (
        "QCC_MERCURIO_ACQUISITION_POLICY_V1"
        not in text
    )


def test_sidepanel_core_does_not_own_policy_implementation():
    core = CORE.read_text(
        encoding="utf-8"
    )

    assert (
        "QCC_ACQUISITION_POLICY_V1"
        not in core
    )

    assert (
        "qccAcquisitionProviderPolicies"
        not in core
    )

    assert (
        "qccAcquisitionSessionHarvestOrigins"
        not in core
    )


def test_storage_failure_is_fail_closed():
    text = POLICY.read_text(
        encoding="utf-8"
    )

    assert (
        "QCC_ACQUISITION_SESSION_STORAGE_UNAVAILABLE"
        in text
    )

    assert (
        "Fail-closed:"
        in text
    )
