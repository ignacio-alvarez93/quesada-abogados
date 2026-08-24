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


def test_catalog_experiment_is_not_exposed_as_separate_sidepanel_tool():
    html = HTML.read_text(
        encoding="utf-8"
    )

    panel = PANEL.read_text(
        encoding="utf-8"
    )

    assert (
        'id="catalog-experiment-selector"'
        not in html
    )

    assert (
        'id="tool-catalog-experiment"'
        not in html
    )

    assert (
        "Probar dependencia"
        not in html
    )

    # La capacidad interna puede seguir
    # existiendo mientras retiramos legacy.
    assert (
        "handleCatalogExperiment"
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


def test_catalog_harvester_is_exposed_only_through_browser_tools():
    html = HTML.read_text(
        encoding="utf-8"
    )

    panel = PANEL.read_text(
        encoding="utf-8"
    )

    assert (
        'id="tool-catalog-harvest"'
        not in html
    )

    assert (
        'id="browser-tools-dialog"'
        in html
    )

    assert (
        'id="tool-mercurio-real-harvest"'
        in html
    )

    assert (
        "Cartografiar catálogo"
        in html
    )

    assert (
        "handleMercurioRealCatalogHarvest"
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


def test_mercurio_real_catalog_probe_is_narrowly_governed():
    worker = WORKER.read_text(
        encoding="utf-8"
    )

    required = (
        "QCC_MERCURIO_REAL_ORIGIN",
        '"https://mercurio.delegaciondelgobierno.gob.es"',
        '"/mercurio/"',
        '"#extCodigoMunicipio"',
        '"#extCodigoLocalidad"',
        "QCC_MERCURIO_REAL_CATALOG_PROBE",
        "QCC_MERCURIO_REAL_STATE_MISMATCH",
        "compareMainCatalogCaptures",
    )

    for token in required:
        assert token in worker


def test_mercurio_real_catalog_probe_is_not_exposed_as_legacy_ui():
    html = HTML.read_text(
        encoding="utf-8"
    )

    panel = PANEL.read_text(
        encoding="utf-8"
    )

    assert (
        'id="tool-mercurio-real-catalog"'
        not in html
    )

    assert (
        "Cartografiar Mercurio REAL"
        not in html
    )

    assert (
        "Probar dependencia"
        not in html
    )

    assert (
        "handleMercurioRealCatalogProbe"
        in panel
    )


def test_mercurio_real_harvester_is_generic_and_sequential():
    worker = WORKER.read_text(
        encoding="utf-8"
    )

    panel = PANEL.read_text(
        encoding="utf-8"
    )

    html = HTML.read_text(
        encoding="utf-8"
    )

    assert (
        'id="tool-mercurio-real-harvest"'
        in html
    )

    assert (
        "Cartografiar catálogo"
        in html
    )

    assert (
        'id="catalog-real-source-selector"'
        in html
    )

    assert (
        'id="catalog-real-target-selector"'
        in html
    )

    assert (
        "Cosechar Asturias REAL"
        not in html
    )

    handler_start = panel.index(
        "async function handleMercurioRealCatalogHarvest()"
    )

    handler_end = panel.index(
        "async function handleMercurioRealCatalogProbe()",
        handler_start,
    )

    handler = panel[
        handler_start:handler_end
    ]

    required_panel = (
        "QCC_SITE_CATALOG_HARVEST",
        "source_selector",
        "target_selector",
        "observations",
        "sequentialCatalogValues",
        "QCC_MERCURIO_REAL_CATALOG_STEP",
        "QCC_MERCURIO_REAL_CATALOG_RESTORE",
        "downloadSiteCatalogHarvest",
        "restauración final exacta",
    )

    for token in required_panel:
        assert token in handler

    assert (
        "MERCURIO_REAL_GEOGRAPHIC_CATALOG"
        not in handler
    )

    assert (
        "province_code"
        not in handler
    )

    assert (
        "Asturias"
        not in handler
    )

    assert (
        "artifact.localities"
        not in handler
    )

    required_worker = (
        "runMercurioRealSequentialCatalogStep",
        "runMercurioRealSequentialCatalogRestore",
        "QCC_MERCURIO_REAL_CATALOG_STEP",
        "QCC_MERCURIO_REAL_CATALOG_RESTORE",
        "QCC_MERCURIO_REAL_ORIGIN_REJECTED",
        "QCC_CATALOG_TARGET_NOT_STABLE",
        "QCC_CATALOG_FINAL_RESTORE_MISMATCH",
    )

    for token in required_worker:
        assert token in worker


def test_qcc_extension_files_do_not_end_with_literal_backslash_n():
    for path in (
        WORKER,
        PANEL,
        HTML,
    ):
        text = path.read_text(
            encoding="utf-8"
        )

        assert not text.endswith(
            "\\\\n"
        )


def test_browser_tools_are_grouped_in_modal():
    html = HTML.read_text(
        encoding="utf-8"
    )

    panel = PANEL.read_text(
        encoding="utf-8"
    )

    required_html = (
        'id="tool-browser-tools-open"',
        'id="browser-tools-dialog"',
        'id="tool-browser-tools-close"',
        'id="tool-dom-inspect"',
        'id="catalog-real-source-selector"',
        'id="catalog-real-target-selector"',
        'id="tool-mercurio-real-harvest"',
        "Abrir herramientas",
        "Cartografiar catálogo",
    )

    for token in required_html:
        assert token in html

    legacy_ui = (
        "Probar dependencia",
        "Cartografiar Mercurio REAL",
        "Cosechar Asturias REAL",
    )

    for token in legacy_ui:
        assert token not in html

    assert (
        "initializeBrowserToolsDialog"
        in panel
    )

    assert (
        "dialog.showModal()"
        in panel
    )

    assert (
        "dialog.close()"
        in panel
    )


def test_browser_tools_discovers_catalogs_without_manual_selectors():
    html = HTML.read_text(
        encoding="utf-8"
    )

    panel = PANEL.read_text(
        encoding="utf-8"
    )

    required_html = (
        'id="tool-catalog-refresh"',
        'id="tool-catalog-capture"',
        'id="catalog-real-source-selector"',
        'id="catalog-real-target-selector"',
        "Actualizar catálogos",
        "Capturar catálogo",
        "Cartografiar relación",
    )

    for token in required_html:
        assert token in html

    assert (
        '<select\n                id="catalog-real-source-selector"'
        in html
    )

    assert (
        '<select\n                id="catalog-real-target-selector"'
        in html
    )

    required_panel = (
        "mainCatalogsFromCapture",
        "catalogBrowserLabel",
        "populateCatalogBrowserSelect",
        "refreshCatalogBrowser",
        "handlePassiveCatalogCapture",
        "QCC_SITE_CATALOG",
        "qcc_site_catalog",
    )

    for token in required_panel:
        assert token in panel


def test_catalog_browser_auto_selects_passive_dependency_hints():
    panel = PANEL.read_text(
        encoding="utf-8"
    )

    required = (
        "dependency_hints",
        "collectCatalogDependencyHintTokens",
        "catalogDependencyCandidates",
        "applyCatalogDependencySuggestion",
        "updateCatalogRelationButtonState",
        "Dependencia detectada",
        "Sin dependencia detectada",
    )

    for token in required:
        assert token in panel


def test_catalog_browser_does_not_choose_arbitrary_dependency():
    panel = PANEL.read_text(
        encoding="utf-8"
    )

    start = panel.index(
        "async function refreshCatalogBrowser()"
    )

    end = panel.index(
        "async function handlePassiveCatalogCapture()",
        start,
    )

    block = panel[
        start:end
    ]

    assert (
        "applyCatalogDependencySuggestion"
        in block
    )

    assert (
        "const alternative ="
        not in block
    )


def test_real_catalog_harvest_records_completion_and_restoration():
    panel = PANEL.read_text(
        encoding="utf-8"
    )

    start = panel.index(
        "async function handleMercurioRealCatalogHarvest()"
    )

    end = panel.index(
        "async function handleMercurioRealCatalogProbe()",
        start,
    )

    block = panel[
        start:end
    ]

    required = (
        "completion:",
        "source_options:",
        "observations:",
        "complete:",
        "restoration:",
        "attempted:",
        "exact:",
        "QCC_SITE_CATALOG_EVIDENCE_INCOMPLETE",
    )

    for token in required:
        assert token in block
