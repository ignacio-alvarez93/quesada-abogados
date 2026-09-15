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


def test_generic_dom_harvest_ui_exists():
    html = HTML.read_text(
        encoding="utf-8"
    )

    required = (
        'id="tool-generic-harvest-enable"',
        'id="tool-generic-dom-harvest"',
        'id="tool-generic-harvest-disable"',
        'id="generic-harvest-feedback"',
        "Activar Harvest",
        "Capturar dataset",
        "Desactivar Harvest",
    )

    for literal in required:
        assert literal in html


def test_generic_dom_harvest_has_worker_authority_gate():
    text = worker_text()

    start = text.index(
        "async function runGenericDomHarvest()"
    )

    end = text.index(
        "async function setGenericHarvestForActiveTab(",
        start,
    )

    block = text[
        start:end
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
        "QCC_GENERIC_DOM_HARVEST_NOT_ALLOWED"
        in block
    )

    assert (
        block.index(
            "resolveGenericHarvestActivePolicy()"
        )
        <
        block.index(
            "inspectActiveTabDom()"
        )
    )


def test_generic_dom_harvest_rechecks_policy_after_capture():
    text = worker_text()

    start = text.index(
        "async function runGenericDomHarvest()"
    )

    end = text.index(
        "async function setGenericHarvestForActiveTab(",
        start,
    )

    block = text[
        start:end
    ]

    assert (
        "QCC_GENERIC_DOM_HARVEST_PERMISSION_REVOKED"
        in block
    )

    assert (
        block.count(
            ".HARVEST_ALLOWED"
        )
        >= 2
    )


def test_generic_dom_harvest_uses_existing_dom_capture():
    text = worker_text()

    assert (
        "buildGenericDomHarvestDataset("
        in text
    )

    assert (
        "frame.result.elements"
        in text
    )

    assert (
        "inspectActiveTabDom()"
        in text
    )


def test_generic_dom_harvest_has_deterministic_dedupe():
    text = worker_text()

    assert (
        "function qccGenericHarvestIdentity("
        in text
    )

    assert (
        "item.frame_path"
        in text
    )

    assert (
        '+"::selector::"'
        .replace("+", "")
        not in ""
    )

    assert (
        "::selector::"
        in text
    )

    assert (
        "duplicates_removed"
        in text
    )

    assert (
        "deduplicated_count"
        in text
    )


def test_generic_dom_harvest_dataset_contains_required_fields():
    text = worker_text()

    required = (
        '"QCC_GENERIC_DOM_HARVEST"',
        "schema_version:",
        "artifact_type:",
        "acquisition_mode:",
        "harvested_at:",
        "origin:",
        "pathname:",
        "document_id:",
        "captured_frames:",
        "raw_item_count:",
        "filtered_out_count:",
        "item_count:",
        "deduplicated_count:",
        "items:",
        "frame_path:",
        "selector:",
        "tag:",
        "text:",
        "accessible_name:",
        "href:",
        "role:",
        "visible:",
        "disabled:",
        "geometry:",
    )

    for literal in required:
        assert literal in text


def test_generic_dom_harvest_runtime_is_passive():
    text = worker_text()

    start = text.index(
        "QCC_GENERIC_DOM_HARVEST_V1"
    )

    end = text.index(
        'message.type\n        !== "QCC_DOM_INSPECT"',
        start,
    )

    block = text[
        start:end
    ]

    forbidden = (
        "scrollTo(",
        "scrollBy(",
        ".click(",
        "tabs.update(",
        "tabs.create(",
        "QCC_CATALOG_EXPERIMENT",
        "QCC_MERCURIO_REAL_CATALOG_STEP",
        "QCC_MERCURIO_REAL_CATALOG_RESTORE",
    )

    for literal in forbidden:
        assert literal not in block


def test_generic_dom_harvest_has_no_bridge_dependency():
    text = worker_text()

    start = text.index(
        "QCC_GENERIC_DOM_HARVEST_V1"
    )

    end = text.index(
        'message.type\n        !== "QCC_DOM_INSPECT"',
        start,
    )

    block = text[
        start:end
    ]

    forbidden = (
        "QCC_BRIDGE_BASE_URL",
        "/qcc/site-architecture",
        "fetch(",
    )

    for literal in forbidden:
        assert literal not in block


def test_generic_dom_harvest_worker_messages_exist():
    text = worker_text()

    required = (
        '"QCC_GENERIC_HARVEST_POLICY"',
        '"QCC_GENERIC_HARVEST_ENABLE"',
        '"QCC_GENERIC_HARVEST_DISABLE"',
        '"QCC_GENERIC_DOM_HARVEST"',
    )

    for literal in required:
        assert literal in text


def test_sidepanel_downloads_generic_harvest_locally():
    text = panel_text()

    start = text.index(
        "async function handleGenericDomHarvest()"
    )

    end = text.index(
        "document.addEventListener(",
        start,
    )

    block = text[
        start:end
    ]

    assert (
        'downloadSiteCatalogHarvest('
        in block
    )

    assert (
        '"qcc_generic_dom_harvest"'
        in block
    )

    assert (
        '"QCC_GENERIC_DOM_HARVEST"'
        in block
    )


def test_sidepanel_is_not_harvest_security_authority():
    text = panel_text()

    start = text.index(
        "QCC_GENERIC_DOM_HARVEST_UI_V1"
    )

    end = text.index(
        "async function handleDomInspect()",
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
        "QCC_GENERIC_DOM_HARVEST"
        in block
    )



def test_generic_dom_harvest_document_id_comes_from_main_frame():
    text = worker_text()

    start = text.index(
        "function buildGenericDomHarvestDataset("
    )

    end = text.index(
        "async function runGenericDomHarvest()",
        start,
    )

    block = text[
        start:end
    ]

    assert (
        "frame?.frame_id === 0"
        in block
    )

    assert (
        "mainFrame?.document_id"
        in block
    )

    assert (
        "capture?.document_id"
        not in block
    )


def test_generic_dom_harvest_filters_document_infrastructure():
    text = worker_text()

    assert (
        "QCC_GENERIC_HARVEST_EXCLUDED_TAGS"
        in text
    )

    assert (
        "function qccGenericHarvestRelevantItem("
        in text
    )

    required_excluded = (
        '"html"',
        '"head"',
        '"body"',
        '"script"',
        '"style"',
        '"meta"',
        '"link"',
        '"noscript"',
        '"template"',
    )

    for literal in required_excluded:
        assert literal in text

    assert (
        "filteredOutCount"
        in text
    )

    assert (
        "acceptedItemCount"
        in text
    )


def test_generic_dom_harvest_filter_preserves_semantic_hidden_items():
    text = worker_text()

    start = text.index(
        "function qccGenericHarvestRelevantItem("
    )

    end = text.index(
        "function buildGenericDomHarvestDataset(",
        start,
    )

    block = text[
        start:end
    ]

    required = (
        "item?.visible === true",
        "item?.selector",
        "item?.id",
        "item?.name",
        "item?.type",
        "item?.role",
        "item?.href",
        "item?.accessible_name",
        "item?.text",
    )

    for literal in required:
        assert literal in block
