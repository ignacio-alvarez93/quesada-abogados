from pathlib import Path


WORKER = Path(
    "chrome_extension/qcc/background/"
    "service_worker.js"
)

PANEL = Path(
    "chrome_extension/qcc/sidepanel/"
    "sidepanel.js"
)

HTML = Path(
    "chrome_extension/qcc/sidepanel/"
    "index.html"
)


def test_catalog_experiment_is_twin_only():
    source = WORKER.read_text(
        encoding="utf-8"
    )

    assert (
        '"http://127.0.0.1:8767"'
        in source
    )

    assert (
        "QCC_CATALOG_EXPERIMENT_TWIN_ONLY"
        in source
    )

    assert (
        "activeUrl.origin"
        in source
    )


def test_catalog_experiment_has_explicit_restore():
    source = WORKER.read_text(
        encoding="utf-8"
    )

    required = (
        "try {",
        "finally {",
        "restoreCatalogSelectionInPage",
        "QCC_CATALOG_EXPERIMENT_RESTORE_FAILED",
        "restoration.exact",
    )

    for token in required:
        assert token in source


def test_catalog_experiment_changes_only_native_select():
    source = WORKER.read_text(
        encoding="utf-8"
    )

    required = (
        '!== "SELECT"',
        "select.disabled",
        "select.multiple",
        "select.value",
        'new Event(',
        '"change"',
    )

    for token in required:
        assert token in source


def test_catalog_experiment_never_clicks_or_submits():
    source = WORKER.read_text(
        encoding="utf-8"
    )

    start = source.index(
        "function setCatalogSelectionInPage"
    )

    end = source.index(
        "function restoreCatalogSelectionInPage",
        start,
    )

    active = source[start:end]

    forbidden = (
        ".click(",
        ".submit(",
        "requestSubmit(",
        "window.location",
    )

    for token in forbidden:
        assert token not in active


def test_catalog_experiment_keeps_three_observations():
    source = WORKER.read_text(
        encoding="utf-8"
    )

    required = (
        "before:",
        "after:",
        "restored:",
        "safety_mode:",
        '"TWIN_ONLY"',
    )

    for token in required:
        assert token in source


def test_catalog_experiment_has_separate_sidepanel_tool():
    html = HTML.read_text(
        encoding="utf-8"
    )

    panel = PANEL.read_text(
        encoding="utf-8"
    )

    assert (
        'id="catalog-experiment-selector"'
        in html
    )

    assert (
        'id="tool-catalog-experiment"'
        in html
    )

    assert (
        'id="catalog-experiment-feedback"'
        in html
    )

    assert (
        "QCC_CATALOG_EXPERIMENT"
        in panel
    )


def test_catalog_experiment_requires_integral_restoration():
    source = WORKER.read_text(
        encoding="utf-8"
    )

    required = (
        "catalogRestoreTargetsFromCapture",
        "restoreCatalogSnapshotInPage",
        "compareMainCatalogCaptures",
        "restorationVerification",
        "restore_passes:",
        "QCC_CATALOG_EXPERIMENT_RESTORE_STATE_MISMATCH",
        "pass <= 6",
    )

    for token in required:
        assert token in source


def test_catalog_restoration_compares_selection_and_options():
    source = WORKER.read_text(
        encoding="utf-8"
    )

    start = source.index(
        "function compareMainCatalogCaptures("
    )

    end = source.index(
        "async function runTwinCatalogExperiment(",
        start,
    )

    block = source[start:end]

    required = (
        "selected_value",
        "selected_values",
        "options",
        "selectionExact",
        "optionsExact",
        "CATALOG_MISSING",
    )

    for token in required:
        assert token in block


def test_catalog_experiment_surfaces_integral_restore():
    source = PANEL.read_text(
        encoding="utf-8"
    )

    assert (
        "restoration_verification"
        in source
    )

    assert (
        "compared_catalogs"
        in source
    )

    assert (
        "estado integral"
        in source
    )


def test_catalog_experiment_posts_to_backend_analyzer():
    source = PANEL.read_text(
        encoding="utf-8"
    )

    required = (
        "QCC_CATALOG_EXPERIMENT_URL",
        "/qcc/site-architecture/catalog-experiment",
        "submitCatalogExperiment",
        "protocol_version:",
        "experiment:",
        "causal_relation_count",
        "evidence_count",
        "relaciones causales",
    )

    for token in required:
        assert token in source


def test_catalog_harvester_has_separate_sidepanel_tool():
    html = HTML.read_text(
        encoding="utf-8"
    )

    panel = PANEL.read_text(
        encoding="utf-8"
    )

    assert (
        'id="tool-catalog-harvest"'
        in html
    )

    assert (
        'id="catalog-harvest-feedback"'
        in html
    )

    assert (
        "handleCatalogHarvest"
        in panel
    )


def test_catalog_harvester_is_bounded_and_sequential():
    source = PANEL.read_text(
        encoding="utf-8"
    )

    start = source.index(
        "async function handleCatalogHarvest()"
    )

    end = source.index(
        "async function handleCatalogExperiment()",
        start,
    )

    block = source[start:end]

    assert (
        "QCC_CATALOG_HARVEST_MAX_VALUES"
        in source
    )

    assert (
        "const QCC_CATALOG_HARVEST_MAX_VALUES ="
        in source
    )

    assert "5;" in source

    assert (
        "for (const requestedValue of values)"
        in block
    )

    assert (
        'type:\n            "QCC_CATALOG_EXPERIMENT"'
        in block
    )

    assert (
        "requested_value:"
        in block
    )


def test_catalog_harvester_requires_restore_before_next_value():
    source = PANEL.read_text(
        encoding="utf-8"
    )

    start = source.index(
        "async function handleCatalogHarvest()"
    )

    end = source.index(
        "async function handleCatalogExperiment()",
        start,
    )

    block = source[start:end]

    restore_position = block.index(
        "verification.exact !== true"
    )

    backend_position = block.index(
        "submitCatalogExperiment"
    )

    completed_position = block.index(
        "completed += 1"
    )

    assert (
        restore_position
        < backend_position
        < completed_position
    )

    assert (
        "QCC_CATALOG_HARVEST_RESTORE_NOT_EXACT"
        in block
    )


def test_catalog_harvester_filters_unsafe_values():
    source = PANEL.read_text(
        encoding="utf-8"
    )

    start = source.index(
        "function catalogHarvestValues("
    )

    end = source.index(
        "function causalRelationSignature(",
        start,
    )

    block = source[start:end]

    required = (
        "!value",
        "option?.disabled === true",
        "value === currentValue",
        "values.length >= limit",
    )

    for token in required:
        assert token in block


def test_catalog_harvester_deduplicates_causal_relations():
    source = PANEL.read_text(
        encoding="utf-8"
    )

    start = source.index(
        "async function handleCatalogHarvest()"
    )

    end = source.index(
        "async function handleCatalogExperiment()",
        start,
    )

    block = source[start:end]

    assert (
        "const causalRelations ="
        in block
    )

    assert (
        "new Map()"
        in block
    )

    assert (
        "causalRelationSignature"
        in block
    )

    assert (
        "causalRelations.set"
        in block
    )

    assert (
        "relaciones únicas"
        in block
    )
