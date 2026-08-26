/*
 * QCC Provider Adapter · Mercurio
 *
 * Contiene comportamiento y transporte
 * específicos del proveedor.
 *
 * No forma parte del núcleo genérico del
 * Side Panel.
 */

async function handleMercurioRealCatalogHarvest() {
  const button =
    element(
      "tool-catalog-relation-harvest"
    );

  if (!button) {
    return;
  }

  const sourceSelector =
    realCatalogSelector(
      "catalog-real-source-selector"
    );

  const targetSelector =
    realCatalogSelector(
      "catalog-real-target-selector"
    );

  if (
    !sourceSelector
    || !targetSelector
  ) {
    setText(
      "catalog-relation-harvest-feedback",
      "Faltan selectores de catálogo."
    );

    return;
  }

  if (
    sourceSelector
      === targetSelector
  ) {
    setText(
      "catalog-relation-harvest-feedback",
      "Origen y destino no pueden ser iguales."
    );

    return;
  }

  button.disabled =
    true;

  let originalValue =
    null;

  let originalTargetOptions =
    null;

  let mutated =
    false;

  let restored =
    false;

  try {
    const permissionGranted =
      await requestDomInspectionPermission();

    if (!permissionGranted) {
      throw new Error(
        "QCC_DOM_HOST_PERMISSION_DENIED"
      );
    }

    setText(
      "catalog-relation-harvest-feedback",
      "Leyendo catálogos..."
    );

    const capture =
      await chrome.runtime.sendMessage({
        type:
          "QCC_DOM_INSPECT"
      });

    if (
      !capture
      || capture.ok !== true
    ) {
      throw new Error(
        "QCC_SITE_CATALOG_CAPTURE_INVALID"
      );
    }

    const sourceCatalog =
      mainCatalogFromCapture(
        capture,
        sourceSelector
      );

    const targetCatalog =
      mainCatalogFromCapture(
        capture,
        targetSelector
      );

    originalValue =
      String(
        sourceCatalog
          ?.state
          ?.selected_value
        || ""
      );

    if (!originalValue) {
      throw new Error(
        "QCC_SITE_CATALOG_SOURCE_VALUE_REQUIRED"
      );
    }

    originalTargetOptions =
      sanitizedOptionsForHarvest(
        targetCatalog
      );

    const sourceOptions =
      (
        sourceCatalog.options
        || []
      ).filter(
        (option) => (
          String(
            option?.value
            || ""
          )
          && option?.disabled !== true
        )
      );

    if (!sourceOptions.length) {
      throw new Error(
        "QCC_SITE_CATALOG_SOURCE_EMPTY"
      );
    }

    const mainUrl =
      String(
        capture.main_url
        || ""
      );

    let origin =
      "";

    let pathname =
      "";

    try {
      const parsed =
        new URL(
          mainUrl
        );

      origin =
        parsed.origin;

      pathname =
        parsed.pathname;
    } catch (_) {
      origin =
        "";
      pathname =
        "";
    }

    const artifact = {
      schema_version:
        1,

      artifact_type:
        "QCC_SITE_CATALOG_HARVEST",

      source_system:
        catalogSourceSystemFromOrigin(
          origin
        ),

      origin:
        origin,

      pathname:
        pathname,

      harvested_at:
        new Date().toISOString(),

      source: {
        selector:
          sourceSelector,

        options:
          sourceOptions.map(
            (option) => ({
              value:
                String(
                  option?.value
                  || ""
                ),

              label:
                String(
                  option?.label
                  || ""
                ),

              disabled:
                option?.disabled === true
            })
          )
      },

      target: {
        selector:
          targetSelector
      },

      observations:
        [],

      completion: {
        source_options:
          sourceOptions.length,

        observations:
          0,

        complete:
          false
      },

      restoration: {
        attempted:
          false,

        exact:
          null
      }
    };

    /*
     * El estado actual también es una
     * observación válida y no requiere
     * mutación.
     */
    const originalOption =
      sourceCatalogOption(
        sourceCatalog,
        originalValue
      );

    artifact.observations.push({
      source_value:
        originalValue,

      source_label:
        String(
          originalOption?.label
          || ""
        ),

      target_options:
        originalTargetOptions
    });

    const pending =
      sequentialCatalogValues(
        sourceOptions,
        originalValue
      );

    let completed =
      1;

    for (const option of pending) {
      const value =
        String(
          option?.value
          || ""
        );

      setText(
        "catalog-relation-harvest-feedback",
        (
          `Cartografiando ${completed + 1}`
          + "/"
          + `${sourceOptions.length}`
          + " · "
          + `${value}`
        )
      );

      const result =
        await chrome.runtime.sendMessage({
          type:
            "QCC_MERCURIO_REAL_CATALOG_STEP",

          source_selector:
            sourceSelector,

          target_selector:
            targetSelector,

          requested_value:
            value
        });

      if (
        !result
        || result.ok !== true
      ) {
        throw new Error(
          (
            "SOURCE_"
            + value
            + "_"
            + (
                result?.error
                || "FAILED"
              )
          )
        );
      }

      mutated =
        true;

      if (
        String(
          result?.source?.current_value
          || ""
        ) !== value
      ) {
        throw new Error(
          "SOURCE_"
          + value
          + "_SELECTION_MISMATCH"
        );
      }

      artifact.observations.push({
        source_value:
          value,

        source_label:
          String(
            result?.source?.test_label
            || option?.label
            || ""
          ),

        target_options:
          (
            Array.isArray(
              result?.target?.options
            )
            ? result.target.options
            : []
          )
      });

      completed += 1;
    }

    if (
      completed
      !== sourceOptions.length
    ) {
      throw new Error(
        "QCC_SITE_CATALOG_HARVEST_INCOMPLETE"
      );
    }

    artifact.completion.observations =
      artifact.observations.length;

    artifact.completion.complete =
      (
        artifact.observations.length
        === sourceOptions.length
      );

    if (!artifact.completion.complete) {
      throw new Error(
        "QCC_SITE_CATALOG_EVIDENCE_INCOMPLETE"
      );
    }

    /*
     * Restauración ÚNICA.
     * No se vuelve al valor inicial
     * durante el recorrido.
     */
    if (mutated) {
      setText(
        "catalog-relation-harvest-feedback",
        "Restaurando estado inicial..."
      );

      const restoration =
        await chrome.runtime.sendMessage({
          type:
            "QCC_MERCURIO_REAL_CATALOG_RESTORE",

          source_selector:
            sourceSelector,

          target_selector:
            targetSelector,

          original_value:
            originalValue,

          expected_target_options:
            originalTargetOptions
        });

      if (
        !restoration
        || restoration.ok !== true
        || restoration.exact !== true
      ) {
        throw new Error(
          (
            "QCC_SITE_CATALOG_FINAL_RESTORE_FAILED_"
            + (
                restoration?.error
                || "UNKNOWN"
              )
          )
        );
      }

      restored =
        true;

      artifact.restoration.attempted =
        true;

      artifact.restoration.exact =
        true;
    }

    if (!mutated) {
      artifact.restoration.exact =
        true;
    }

    downloadSiteCatalogHarvest(
      artifact
    );

    setText(
      "catalog-relation-harvest-feedback",
      (
        `Cartografiado ${completed}/${sourceOptions.length}`
        + " · observaciones "
        + `${artifact.observations.length}`
        + " · restauración final exacta"
        + " · JSON descargado · OK"
      )
    );

  } catch (error) {
    let detail =
      String(
        error?.message
        || error
        || "QCC_SITE_CATALOG_HARVEST_FAILED"
      );

    /*
     * Si el recorrido falla a mitad,
     * intentamos UNA restauración de
     * emergencia antes de terminar.
     */
    if (
      mutated
      && !restored
      && originalValue !== null
      && originalTargetOptions !== null
    ) {
      try {
        const emergencyRestore =
          await chrome.runtime.sendMessage({
            type:
              "QCC_MERCURIO_REAL_CATALOG_RESTORE",

            source_selector:
              sourceSelector,

            target_selector:
              targetSelector,

            original_value:
              originalValue,

            expected_target_options:
              originalTargetOptions
          });

        if (
          emergencyRestore?.ok === true
          && emergencyRestore?.exact === true
        ) {
          detail +=
            " · estado inicial restaurado";
        } else {
          detail +=
            " · RESTAURACION_FINAL_NO_CONFIRMADA";
        }

      } catch (_) {
        detail +=
          " · RESTAURACION_FINAL_NO_CONFIRMADA";
      }
    }

    setText(
      "catalog-relation-harvest-feedback",
      (
        "Cartografiado detenido · "
        + detail
      )
    );

  } finally {
    button.disabled =
      false;
  }
}


async function handleMercurioRealCatalogProbe() {
  const button =
    element(
      "tool-mercurio-real-catalog"
    );

  if (!button) {
    return;
  }

  button.disabled =
    true;

  setText(
    "mercurio-real-catalog-feedback",
    "Mercurio REAL · cartografiando..."
  );

  try {
    const permissionGranted =
      await requestDomInspectionPermission();

    if (!permissionGranted) {
      throw new Error(
        "QCC_DOM_HOST_PERMISSION_DENIED"
      );
    }

    const result =
      await chrome.runtime.sendMessage({
        type:
          "QCC_MERCURIO_REAL_CATALOG_PROBE"
      });

    if (
      !result
      || result.ok !== true
    ) {
      throw new Error(
        result?.error
        || "QCC_MERCURIO_REAL_PROBE_FAILED"
      );
    }

    setText(
      "mercurio-real-catalog-feedback",
      (
        `${result.source.original_value}`
        + " → "
        + `${result.source.test_value}`
        + " → restaurado "
        + `${result.source.restored_value}`
        + " · localidades "
        + `${result.target.options_count}`
        + " · estado "
        + `${result.restoration_verification.compared_catalogs}`
        + "/"
        + `${result.restoration_verification.compared_catalogs}`
        + " · OK"
      )
    );

    console.log(
      "[QCC] MERCURIO REAL CATALOG",
      result
    );

  } catch (error) {
    setText(
      "mercurio-real-catalog-feedback",
      (
        "Mercurio REAL detenido · "
        + String(
            error?.message
            || error
          )
      )
    );

  } finally {
    button.disabled =
      false;
  }
}


document.addEventListener(
  "DOMContentLoaded",
  () => {
    const relationHarvest =
      element(
        "tool-catalog-relation-harvest"
      );

    if (relationHarvest) {
      relationHarvest.addEventListener(
        "click",
        handleMercurioRealCatalogHarvest
      );
    }

    /*
     * Probe histórico no expuesto actualmente
     * en la UI. Conservamos su contrato para
     * compatibilidad y diagnóstico.
     */
    const realCatalogProbe =
      element(
        "tool-mercurio-real-catalog"
      );

    if (realCatalogProbe) {
      realCatalogProbe.addEventListener(
        "click",
        handleMercurioRealCatalogProbe
      );
    }
  }
);
