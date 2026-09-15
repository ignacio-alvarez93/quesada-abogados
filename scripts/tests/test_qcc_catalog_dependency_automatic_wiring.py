from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

WORKER = (
    ROOT
    / "chrome_extension"
    / "qcc"
    / "background"
    / "service_worker.js"
)

PLANNER = (
    ROOT
    / "chrome_extension"
    / "qcc"
    / "shared"
    / "catalog_dependency_planner.js"
)


def test_shared_planner_supports_native_and_custom_catalogs():
    text = PLANNER.read_text(
        encoding="utf-8"
    )

    assert '"native_select"' in text
    assert '"custom_select"' in text
    assert "planCapture(" in text
    assert "dependencyCandidates(" in text
    assert "alternativeOptionOf(" in text


def test_shared_planner_is_provider_neutral():
    text = PLANNER.read_text(
        encoding="utf-8"
    ).lower()

    for forbidden in (
        "red_sara",
        "redsara",
        "mercurio",
        "dnt-select",
        "dnt-option",
    ):
        assert forbidden not in text


def test_shared_planner_never_fabricates_raw_values():
    text = PLANNER.read_text(
        encoding="utf-8"
    )

    assert "option?.value" in text
    assert "option?.label" in text
    assert "Nunca fabricamos RAW" in text

    assert (
        "requested_value:"
        in text
    )

    assert (
        "requested_label:"
        in text
    )


def test_service_worker_imports_shared_catalog_dependency_planner():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    assert (
        "../shared/catalog_dependency_planner.js"
        in text
    )


def test_automatic_capture_schedules_causal_discovery_after_persistence():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    capture_start = text.index(
        "async function runAutomaticSiteArchitectureCapture("
    )

    capture_end = text.index(
        "function scheduleAutomaticSiteArchitectureCapture(",
        capture_start,
    )

    block = text[
        capture_start:capture_end
    ]

    assert (
        "await qccRememberAutomaticCapture("
        in block
    )

    assert (
        "runAutomaticCatalogCausalDiscovery("
        in block
    )

    remember_index = block.index(
        "await qccRememberAutomaticCapture("
    )

    causal_after_persistence = block.find(
        "runAutomaticCatalogCausalDiscovery(",
        remember_index,
    )

    assert causal_after_persistence > remember_index


def test_automatic_causal_probe_is_bounded_and_fail_open():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    start = text.index(
        "async function runAutomaticCatalogCausalDiscovery("
    )

    end = text.index(
        "function scheduleAutomaticSiteArchitectureCapture(",
        start,
    )

    block = text[
        start:end
    ]

    assert (
        "max_plans:"
        in block
    )

    assert (
        "TARGET_UNCHANGED"
        in block
    )

    assert (
        "qccAutomaticCatalogProbeInFlight"
        in block
    )

    assert (
        "qccAutomaticCatalogProbeAttempted"
        in block
    )

    assert (
        "Automatic Catalog Causal Discovery skipped"
        in block
    )


def test_automatic_executor_guards_exact_physical_tab_before_mutation():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    start = text.index(
        "async function runGenericCatalogCausalProbe("
    )

    end = text.index(
        "const authority =",
        start,
    )

    block = text[
        start:end
    ]

    assert "expectedTabId" in block
    assert "expectedUrl" in block
    assert (
        "QCC_GENERIC_CATALOG_EXPECTED_TAB_CHANGED"
        in block
    )
    assert (
        "QCC_GENERIC_CATALOG_EXPECTED_URL_CHANGED"
        in block
    )


def test_causal_artifact_is_posted_to_backend_dependency_store():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    assert (
        "/qcc/auto-twin/catalog-dependency-probe"
        in text
    )

    assert (
        "async function qccPersistGenericCatalogCausalProbe("
        in text
    )

    assert (
        "browser_profile_key:"
        in text
    )

    assert (
        "probe:"
        in text
    )


def test_automatic_planner_does_not_run_on_arbitrary_target_choice():
    text = PLANNER.read_text(
        encoding="utf-8"
    )

    assert (
        "candidates.length !== 1"
        in text
    )

    assert (
        "targetOptions.length"
        in text
    )



def test_dependency_transport_uses_backend_authorized_url():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    start = text.index(
        "async function qccPersistGenericCatalogCausalProbe("
    )

    end = text.index(
        "function qccAutomaticCatalogProbeKey(",
        start,
    )

    block = text[start:end]

    assert "?.auto_twin" in block
    assert "?.url" in block

    # authority.tab nunca ha formado parte del contrato.
    assert "?.tab" not in block


def test_document_dedupe_does_not_suppress_causal_discovery():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    start = text.index(
        "async function runAutomaticSiteArchitectureCapture("
    )

    end = text.index(
        "function scheduleAutomaticSiteArchitectureCapture(",
        start,
    )

    block = text[start:end]

    dedupe = block.index(
        '"DOCUMENT_ALREADY_CAPTURED"'
    )

    causal_before_dedupe = block.rfind(
        "runAutomaticCatalogCausalDiscovery(",
        0,
        dedupe,
    )

    assert causal_before_dedupe >= 0


def test_local_restore_failure_is_governed_by_hard_restore_fallback():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    start = text.index(
        "async function runGenericCatalogCausalProbe("
    )

    end = text.index(
        "function setCatalogSelectionInPage(",
        start,
    )

    block = text[start:end]

    assert (
        '"LOCAL_RESTORE_FAILED"'
        in block
    )

    assert (
        "qccGenericCatalogHardDocumentRestore("
        in block
    )

    assert (
        "QCC_GENERIC_CATALOG_EXACT_RESTORE_FAILED"
        in block
    )



def test_governed_harvest_bootstrap_requires_backend_discovery_authority_first():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    start = text.index(
        "async function qccGenericCatalogProbeAuthority("
    )

    end = text.index(
        "async function qccGenericCatalogHardRestoreAuthority(",
        start,
    )

    block = text[start:end]

    backend_decision = block.index(
        "const decision ="
    )

    active_discovery = block.index(
        "active_discovery"
    )

    active_catalog_probe = block.index(
        "active_catalog_probe"
    )

    harvest_bootstrap = block.index(
        "enableHarvestForUrl("
    )

    assert backend_decision < harvest_bootstrap
    assert active_discovery < harvest_bootstrap
    assert active_catalog_probe < harvest_bootstrap


def test_governed_harvest_bootstrap_keeps_acquisition_policy_as_second_gate():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    start = text.index(
        "async function qccGenericCatalogProbeAuthority("
    )

    end = text.index(
        "async function qccGenericCatalogHardRestoreAuthority(",
        start,
    )

    block = text[start:end]

    assert (
        "acquisition.resolve("
        in block
    )

    assert (
        "acquisition.HARVEST_ALLOWED"
        in block
    )

    assert (
        "QCC_GENERIC_CATALOG_HARVEST_NOT_ALLOWED"
        in block
    )

    assert (
        "QCC_GENERIC_CATALOG_GOVERNED_HARVEST_BOOTSTRAP_DENIED"
        in block
    )


def test_governed_harvest_bootstrap_is_provider_neutral():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    start = text.index(
        "async function qccGenericCatalogProbeAuthority("
    )

    end = text.index(
        "async function qccGenericCatalogHardRestoreAuthority(",
        start,
    )

    block = text[start:end].lower()

    for forbidden in (
        "red_sara",
        "redsara",
        "dnt-select",
        "dnt-option",
    ):
        assert forbidden not in block



def test_automatic_causal_dispatch_is_awaited():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    assert (
        "await runAutomaticCatalogCausalDiscovery("
        in text
    )


def test_automatic_causal_dispatch_result_is_observable():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    assert (
        "[QCC] Automatic Catalog Causal Discovery result:"
        in text
    )

    assert (
        "[QCC] Automatic Catalog Causal Discovery dispatch skipped:"
        in text
    )


def test_automatic_causal_dispatch_does_not_silence_rejection():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    forbidden = """runAutomaticCatalogCausalDiscovery(
      normalizedTabId,
      capture,
      trigger
    ).catch(
      () => {}
    );"""

    assert forbidden not in text



def test_target_unchanged_preserves_physical_probe_diagnostic():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    assert (
        "const targetUnchangedDiagnostic = {"
        in text
    )

    for required in (
        "requested_value:",
        "requested_label:",
        "source_value:",
        "source_label:",
        "target_options_count:",
        "mutation:",
        "restoration_verification:",
    ):
        assert required in text


def test_target_unchanged_returns_diagnostic_to_outer_dispatch_log():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    start = text.index(
        "async function runAutomaticCatalogCausalDiscovery("
    )

    end = text.index(
        "function scheduleAutomaticSiteArchitectureCapture(",
        start,
    )

    block = text[start:end]

    compact = "".join(
        block.split()
    )

    assert (
        'reason:"TARGET_UNCHANGED",diagnostic:targetUnchangedDiagnostic'
        in compact
    )

    assert (
        "consttargetUnchangedDiagnostic={"
        in compact
    )



def test_planner_does_not_treat_control_identity_as_dependency():
    text = PLANNER.read_text(
        encoding="utf-8"
    )

    assert (
        "collectOutboundDependencyHintTokens("
        in text
    )

    assert (
        """collectDependencyHintTokens(
      sourceCatalog?.dependency_hints,
      rawTokens
    );"""
        not in text
    )

    start = text.index(
        "const QCC_EXPLICIT_OUTBOUND_DEPENDENCY_HINT_KEYS"
    )

    end = text.index(
        "function normalizedHintKey(",
        start,
    )

    key_contract = text[start:end].lower()

    assert "formcontrolname" not in key_contract


def test_planner_keeps_explicit_outbound_target_contract():
    text = PLANNER.read_text(
        encoding="utf-8"
    )

    start = text.index(
        "const QCC_EXPLICIT_OUTBOUND_DEPENDENCY_HINT_KEYS"
    )

    end = text.index(
        "function normalizedHintKey(",
        start,
    )

    key_contract = text[start:end]

    assert '"target_selector"' in key_contract
    assert '"dependent_selector"' in key_contract



def test_catalog_dependency_transport_uses_authorized_protocol_version():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    start = text.index(
        "async function qccPersistGenericCatalogCausalProbe("
    )

    end = text.index(
        "function qccAutomaticCatalogProbeKey(",
        start,
    )

    block = text[start:end]

    compact = "".join(
        block.split()
    )

    assert (
        "artifact?.authority?.auto_twin?.protocol_version"
        in compact
    )

    assert (
        "protocol_version:protocolVersion"
        in compact
    )


def test_catalog_dependency_transport_has_no_undefined_protocol_global():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    start = text.index(
        "async function qccPersistGenericCatalogCausalProbe("
    )

    end = text.index(
        "function qccAutomaticCatalogProbeKey(",
        start,
    )

    block = text[start:end]

    assert "QCC_PROTOCOL_VERSION" not in block

    assert (
        "QCC_GENERIC_CATALOG_DEPENDENCY_PROTOCOL_VERSION_INVALID"
        in block
    )



def test_automatic_discovery_enumerates_candidates_but_mutates_one_per_cycle():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    start = text.index(
        "async function runAutomaticCatalogCausalDiscovery("
    )

    end = text.index(
        "function scheduleAutomaticSiteArchitectureCapture(",
        start,
    )

    block = text[start:end]
    compact = "".join(block.split())

    assert (
        "max_plans:Number.MAX_SAFE_INTEGER"
        in compact
    )

    assert (
        ".find((entry)=>!qccAutomaticCatalogProbeAttempted.has(entry.attemptKey))"
        in compact
    )

    assert (
        "construnGenericCatalogCausalProbe"
        not in compact
    )


def test_automatic_discovery_advances_when_first_candidate_was_attempted():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    start = text.index(
        "async function runAutomaticCatalogCausalDiscovery("
    )

    end = text.index(
        "function scheduleAutomaticSiteArchitectureCapture(",
        start,
    )

    block = text[start:end]

    assert (
        "ALL_CAUSAL_CANDIDATES_ATTEMPTED"
        in block
    )

    assert (
        "candidate_count:"
        in block
    )

    assert (
        "const plan =\n      pendingPlan.plan;"
        in block
    )


def test_document_dedupe_causal_dispatch_is_not_fire_and_forget():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    dedupe = text.index(
        '"DOCUMENT_ALREADY_CAPTURED"'
    )

    prefix = text[
        max(0, dedupe - 2500):
        dedupe
    ]

    assert (
        "await runAutomaticCatalogCausalDiscovery("
        in prefix
    )

    assert (
        ").catch(\n        () => {}\n      );"
        not in prefix
    )
