from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

WORKER = (
    ROOT
    / "chrome_extension"
    / "qcc"
    / "background"
    / "service_worker.js"
)


def _read():
    return WORKER.read_text(
        encoding="utf-8"
    )


def _function_block(
    js,
    start_marker,
    end_marker,
):
    start = js.index(
        start_marker
    )

    end = js.index(
        end_marker,
        start,
    )

    return js[start:end]


def test_capture_gate_has_explicit_marker():
    js = _read()

    assert (
        "QCC_ARCHITECTURE_AUTOMATIC_CAPTURE_GATE_V1"
        in js
    )


def test_gate_reads_persistent_browser_identity():
    js = _read()

    start = js.index(
        "async function "
        "qccAutomaticArchitectureCaptureDecision("
    )

    end = js.index(
        "async function "
        "qccAutomaticCapturePermissions()",
        start,
    )

    block = js[start:end]

    assert (
        "QccBrowserIdentity"
        in block
    )

    assert (
        "await identity.read()"
        in block
    )


def test_gate_resolves_profile_plus_url_policy():
    js = _read()

    start = js.index(
        "async function "
        "qccAutomaticArchitectureCaptureDecision("
    )

    end = js.index(
        "async function "
        "qccAutomaticCapturePermissions()",
        start,
    )

    block = js[start:end]

    assert (
        "QccArchitectureCapturePolicy"
        in block
    )

    assert (
        "await policy.resolve("
        in block
    )

    assert "profileKey" in block
    assert "url" in block


def test_gate_is_fail_closed():
    js = _read()

    start = js.index(
        "async function "
        "qccAutomaticArchitectureCaptureDecision("
    )

    end = js.index(
        "async function "
        "qccAutomaticCapturePermissions()",
        start,
    )

    block = js[start:end]

    for source in (
        "POLICY_RUNTIME_UNAVAILABLE",
        "IDENTITY_STORAGE_ERROR",
        "PROFILE_UNBOUND",
        "POLICY_RESOLUTION_ERROR",
    ):
        assert source in block

    assert (
        "automatic_allowed:"
        in block
    )

    assert (
        "false"
        in block
    )


def test_navigation_capture_checks_gate_before_permissions_and_dom():
    js = _read()

    block = _function_block(
        js,
        "async function "
        "runAutomaticSiteArchitectureCapture(",
        "function "
        "scheduleAutomaticSiteArchitectureCapture(",
    )

    gate = block.index(
        "qccAutomaticArchitectureCaptureDecision("
    )

    permissions = block.index(
        "qccAutomaticCapturePermissions()"
    )

    dom = block.index(
        "inspectSpecificTabDom("
    )

    assert gate < permissions < dom

    assert (
        "ARCHITECTURE_CAPTURE_NOT_AUTHORIZED"
        in block
    )


def test_same_document_checks_gate_before_permissions_and_dom():
    js = _read()

    block = _function_block(
        js,
        "async function "
        "runAutomaticSameDocumentObservation(",
        "async function "
        "runAutomaticSiteArchitectureCapture(",
    )

    gate = block.index(
        "qccAutomaticArchitectureCaptureDecision("
    )

    permissions = block.index(
        "qccAutomaticCapturePermissions()"
    )

    dom = block.index(
        "inspectSpecificTabDom("
    )

    assert gate < permissions < dom

    assert (
        "ARCHITECTURE_CAPTURE_NOT_AUTHORIZED"
        in block
    )


def test_unauthorized_navigation_returns_before_observer_install():
    js = _read()

    block = _function_block(
        js,
        "async function "
        "runAutomaticSiteArchitectureCapture(",
        "function "
        "scheduleAutomaticSiteArchitectureCapture(",
    )

    deny = block.index(
        "ARCHITECTURE_CAPTURE_NOT_AUTHORIZED"
    )

    observer = block.index(
        "qccInstallAutomaticMutationObservers("
    )

    assert deny < observer


def test_gate_is_used_only_by_two_automatic_execution_paths():
    js = _read()

    # definición + VIS-2B + VIS-2A
    assert (
        js.count(
            "qccAutomaticArchitectureCaptureDecision("
        )
        == 3
    )


def test_force_capture_is_not_governed_by_automatic_gate():
    js = _read()

    # El gate nuevo está exclusivamente en las dos
    # rutas automáticas anteriores.
    assert (
        js.count(
            "ARCHITECTURE_CAPTURE_NOT_AUTHORIZED"
        )
        == 2
    )


def test_policy_denial_does_not_contact_bridge():
    js = _read()

    navigation = _function_block(
        js,
        "async function "
        "runAutomaticSiteArchitectureCapture(",
        "function "
        "scheduleAutomaticSiteArchitectureCapture(",
    )

    gate = navigation.index(
        "qccAutomaticArchitectureCaptureDecision("
    )

    deny = navigation.index(
        "ARCHITECTURE_CAPTURE_NOT_AUTHORIZED"
    )

    submit = navigation.index(
        "qccSubmitAutomaticDomCapture("
    )

    assert gate < deny < submit
