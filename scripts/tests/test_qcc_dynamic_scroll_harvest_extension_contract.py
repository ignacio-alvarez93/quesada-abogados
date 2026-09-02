from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

QCC = (
    ROOT
    / "chrome_extension"
    / "qcc"
)

WORKER = (
    QCC
    / "background"
    / "service_worker.js"
)

PANEL = (
    QCC
    / "sidepanel"
    / "sidepanel.js"
)

HTML = (
    QCC
    / "sidepanel"
    / "index.html"
)


def worker_text():
    return WORKER.read_text(
        encoding="utf-8"
    )


def panel_text():
    return PANEL.read_text(
        encoding="utf-8"
    )


def dynamic_worker_block():
    text = worker_text()

    start = text.index(
        "QCC_GENERIC_DYNAMIC_HARVEST_V1"
    )

    end = text.index(
        'message.type\n        !== "QCC_CATALOG_EXPERIMENT"',
        start,
    )

    return text[
        start:end
    ]


def test_dynamic_harvest_ui_exists():
    html = HTML.read_text(
        encoding="utf-8"
    )

    assert (
        'id="tool-generic-dynamic-harvest"'
        in html
    )

    assert (
        "Harvest dinámico"
        in html
    )


def test_dynamic_harvest_has_conservative_bounds():
    text = dynamic_worker_block()

    required = (
        "QCC_GENERIC_DYNAMIC_MAX_STEPS",
        "12",
        "QCC_GENERIC_DYNAMIC_SCROLL_FRACTION",
        "0.75",
        "QCC_GENERIC_DYNAMIC_WAIT_MS",
        "1500",
        "QCC_GENERIC_DYNAMIC_STAGNATION_LIMIT",
        "2",
    )

    for literal in required:
        assert literal in text


def test_dynamic_harvest_requires_worker_policy_gate():
    text = dynamic_worker_block()

    start = text.index(
        "async function runGenericDynamicHarvest()"
    )

    block = text[
        start:
    ]

    assert (
        "resolveGenericHarvestActivePolicy()"
        in block
    )

    assert (
        ".HARVEST_ALLOWED"
        in block
    )

    assert (
        "QCC_GENERIC_DYNAMIC_HARVEST_NOT_ALLOWED"
        in block
    )

    assert (
        block.index(
            "resolveGenericHarvestActivePolicy()"
        )
        <
        block.index(
            "qccGenericDynamicScrollStep("
        )
    )


def test_dynamic_harvest_revalidates_each_cycle():
    text = dynamic_worker_block()

    start = text.index(
        "async function runGenericDynamicHarvest()"
    )

    block = text[
        start:
    ]

    assert (
        "Gate ANTES de cualquier nuevo scroll."
        in block
    )

    assert (
        "Gate DESPUÉS del scroll"
        in block
    )

    assert (
        block.count(
            "qccGenericDynamicAssertContext("
        )
        >= 2
    )

    assert (
        "QCC_GENERIC_DYNAMIC_HARVEST_PERMISSION_REVOKED"
        in block
    )


def test_dynamic_harvest_guards_tab_origin_and_document():
    text = dynamic_worker_block()

    required = (
        "QCC_GENERIC_DYNAMIC_HARVEST_TAB_CHANGED",
        "QCC_GENERIC_DYNAMIC_HARVEST_ORIGIN_CHANGED",
        "QCC_GENERIC_DYNAMIC_HARVEST_DOCUMENT_ID_REQUIRED",
        "QCC_GENERIC_DYNAMIC_HARVEST_DOCUMENT_CHANGED",
        "mainFrame?.document_id",
    )

    for literal in required:
        assert literal in text


def test_dynamic_harvest_only_scrolls_main_frame():
    text = dynamic_worker_block()

    assert (
        "frameIds: [\n          0\n        ]"
        in text
    )

    assert (
        "window.scrollTo({"
        in text
    )

    assert (
        "QCC_GENERIC_DYNAMIC_SCROLL_FRACTION"
        in text
    )


def test_dynamic_harvest_does_not_click_or_navigate():
    text = dynamic_worker_block()

    forbidden = (
        ".click(",
        "tabs.update(",
        "tabs.create(",
        "window.open(",
        "location.href =",
        "location.assign(",
        "location.replace(",
        "QCC_CATALOG_EXPERIMENT",
        "QCC_MERCURIO_REAL_CATALOG_STEP",
    )

    for literal in forbidden:
        assert literal not in text


def test_dynamic_harvest_stops_on_stagnation():
    text = dynamic_worker_block()

    required = (
        "stagnation",
        "STAGNATION_LIMIT",
        "BOTTOM_REACHED",
        "NO_SCROLL_PROGRESS",
        "merge.new_items === 0",
    )

    for literal in required:
        assert literal in text


def test_dynamic_harvest_merges_and_deduplicates_snapshots():
    text = dynamic_worker_block()

    required = (
        "qccGenericDynamicMergeDataset(",
        "qccGenericDynamicIdentity(",
        "first_seen_step",
        "last_seen_step",
        "observations",
        "duplicates_removed",
        "deduplicated_count",
    )

    for literal in required:
        assert literal in text


def test_dynamic_harvest_restores_initial_scroll_best_effort():
    text = dynamic_worker_block()

    required = (
        "qccGenericDynamicTryRestore(",
        "qccGenericDynamicRestoreScroll(",
        "initialScroll",
        "restoration:",
        "exact:",
    )

    for literal in required:
        assert literal in text


def test_dynamic_harvest_has_no_bridge_dependency():
    text = dynamic_worker_block()

    forbidden = (
        "QCC_BRIDGE_BASE_URL",
        "/qcc/",
        "fetch(",
    )

    for literal in forbidden:
        assert literal not in text


def test_dynamic_harvest_message_is_separate():
    text = worker_text()

    assert (
        '"QCC_GENERIC_DYNAMIC_HARVEST"'
        in text
    )

    assert (
        "runGenericDynamicHarvest()"
        in text
    )


def test_sidepanel_downloads_dynamic_dataset():
    text = panel_text()

    start = text.index(
        "async function handleGenericDynamicHarvest()"
    )

    end = text.index(
        "async function handleGenericHarvestDisable()",
        start,
    )

    block = text[
        start:end
    ]

    assert (
        '"QCC_GENERIC_DYNAMIC_HARVEST"'
        in block
    )

    assert (
        '"qcc_generic_dynamic_harvest"'
        in block
    )

    assert (
        "downloadSiteCatalogHarvest("
        in block
    )


def test_sidepanel_is_not_dynamic_security_authority():
    text = panel_text()

    start = text.index(
        "async function handleGenericDynamicHarvest()"
    )

    end = text.index(
        "async function handleGenericHarvestDisable()",
        start,
    )

    block = text[
        start:end
    ]

    assert (
        "QccAcquisitionPolicy.resolve"
        not in block
    )

    assert (
        "QCC_GENERIC_DYNAMIC_HARVEST"
        in block
    )


def test_injected_scroll_function_is_self_contained():
    text = worker_text()

    start = text.index(
        "function qccGenericDynamicScrollPage("
    )

    end = text.index(
        "function qccGenericDynamicRestorePage(",
        start,
    )

    block = text[
        start:end
    ]

    assert (
        "function readState()"
        in block
    )

    assert (
        "qccGenericDynamicReadScrollPage("
        not in block
    )

    assert (
        "window.scrollTo({"
        in block
    )


def test_injected_restore_function_is_self_contained():
    text = worker_text()

    start = text.index(
        "function qccGenericDynamicRestorePage("
    )

    end = text.index(
        "async function qccGenericDynamicReadScroll(",
        start,
    )

    block = text[
        start:end
    ]

    assert (
        "qccGenericDynamicReadScrollPage("
        not in block
    )

    assert (
        "window.scrollTo({"
        in block
    )

    assert (
        "document.documentElement"
        in block
    )


def test_sidepanel_harvest_messages_have_watchdog():
    text = panel_text()

    start = text.index(
        "async function qccGenericHarvestMessage("
    )

    end = text.index(
        "async function handleGenericHarvestEnable()",
        start,
    )

    block = text[
        start:end
    ]

    required = (
        "Promise.race([",
        "QCC_GENERIC_HARVEST_TIMEOUT",
        "window.setTimeout(",
        "window.clearTimeout(",
    )

    for literal in required:
        assert literal in block


def test_dynamic_harvest_has_longer_ui_watchdog():
    text = panel_text()

    start = text.index(
        "async function handleGenericDynamicHarvest()"
    )

    end = text.index(
        "async function handleGenericHarvestDisable()",
        start,
    )

    block = text[
        start:end
    ]

    assert (
        '"QCC_GENERIC_DYNAMIC_HARVEST",'
        in block
    )

    assert (
        "60000"
        in block
    )


def test_harvest_enable_worker_has_phase_deadlines():
    text = worker_text()

    start = text.index(
        "async function setGenericHarvestForActiveTab("
    )

    end = text.index(
        "chrome.runtime.onMessage.addListener(",
        start,
    )

    block = text[
        start:end
    ]

    required = (
        "QCC_GENERIC_HARVEST_ACTIVE_TAB_TIMEOUT",
        "QCC_GENERIC_HARVEST_POLICY_RESOLVE_TIMEOUT",
        "QCC_GENERIC_HARVEST_POLICY_ENABLE_TIMEOUT",
        "QCC_GENERIC_HARVEST_POLICY_DISABLE_TIMEOUT",
        "qccGenericHarvestWorkerDeadline(",
        "policy.resolve(",
        "policy.enableHarvestForUrl(",
        "policy.disableHarvestForUrl(",
    )

    for literal in required:
        assert literal in block


def test_harvest_worker_deadline_is_bounded():
    text = worker_text()

    start = text.index(
        "function qccGenericHarvestWorkerDeadline("
    )

    end = text.index(
        "async function setGenericHarvestForActiveTab(",
        start,
    )

    block = text[
        start:end
    ]

    assert "setTimeout(" in block
    assert "clearTimeout(" in block
    assert "3000" in text
