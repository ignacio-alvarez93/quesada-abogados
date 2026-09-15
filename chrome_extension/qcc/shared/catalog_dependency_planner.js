/*
 * ============================================================
 * QCC_CATALOG_DEPENDENCY_PLANNER_V1
 * ============================================================
 *
 * Planner puro y provider-neutral.
 *
 * NO:
 * - ejecuta navegador;
 * - consulta Bridge;
 * - muta DOM;
 * - persiste evidencia;
 * - conoce proveedores, sedes o implementaciones concretas.
 *
 * Consume exclusivamente Site Architecture catalog_probe.
 */

(function installQccCatalogDependencyPlanner(root) {
  "use strict";


  const SUPPORTED_CATALOG_TYPES =
    new Set([
      "native_select",
      "custom_select"
    ]);


  function clean(value) {
    return String(
      value ?? ""
    ).trim();
  }


  function isSupportedCatalog(catalog) {
    return SUPPORTED_CATALOG_TYPES.has(
      clean(
        catalog?.catalog_type
      )
    );
  }


  function mainCatalogsFromCapture(capture) {
    const mainFrame =
      (
        capture?.frames
        || []
      ).find(
        (frame) =>
          Number(
            frame?.frame_id
          ) === 0
      );

    return (
      mainFrame
        ?.result
        ?.catalog_probe
        ?.elements
      || []
    ).filter(
      isSupportedCatalog
    );
  }


  function collectDependencyHintTokens(
    value,
    target
  ) {
    if (typeof value === "string") {
      const raw =
        clean(
          value
        );

      if (!raw) {
        return;
      }

      target.add(
        raw
      );

      raw
        .split(
          /[\s,;|]+/
        )
        .map(
          clean
        )
        .filter(Boolean)
        .forEach(
          (token) =>
            target.add(
              token
            )
        );

      return;
    }


    if (Array.isArray(value)) {
      value.forEach(
        (item) =>
          collectDependencyHintTokens(
            item,
            target
          )
      );

      return;
    }


    if (
      value
      && typeof value === "object"
    ) {
      Object.values(
        value
      ).forEach(
        (item) =>
          collectDependencyHintTokens(
            item,
            target
          )
      );
    }
  }


  function normalizedReference(value) {
    return clean(
      value
    ).replace(
      /^#/,
      ""
    );
  }


  /*
   * Solo una clave que declare EXPLÍCITAMENTE una relación
   * outbound puede proponer un target.
   *
   * Metadatos de identidad del propio control como:
   *
   *   id
   *   name
   *   formcontrolname
   *
   * NO son evidencia de dependencia.
   *
   * No existe lógica específica de proveedor.
   */
  const QCC_EXPLICIT_OUTBOUND_DEPENDENCY_HINT_KEYS =
    new Set([
      "target",
      "target_selector",
      "targetselector",
      "target_selectors",
      "targetselectors",
      "dependent",
      "dependent_selector",
      "dependentselector",
      "dependent_selectors",
      "dependentselectors",
      "child",
      "child_selector",
      "childselector"
    ]);


  function normalizedHintKey(
    value
  ) {
    return clean(
      value
    )
      .toLowerCase()
      .replace(
        /[^a-z0-9]+/g,
        "_"
      );
  }


  function collectOutboundDependencyHintTokens(
    value,
    target,
    outboundContext = false
  ) {
    if (
      value === null
      || value === undefined
    ) {
      return;
    }


    if (
      typeof value === "string"
      || typeof value === "number"
    ) {
      if (!outboundContext) {
        return;
      }

      const token =
        clean(
          value
        );

      if (token) {
        target.add(
          token
        );
      }

      return;
    }


    if (
      Array.isArray(
        value
      )
    ) {
      value.forEach(
        (item) =>
          collectOutboundDependencyHintTokens(
            item,
            target,
            outboundContext
          )
      );

      return;
    }


    if (
      value
      && typeof value === "object"
    ) {
      Object.entries(
        value
      ).forEach(
        ([key, item]) => {
          const normalizedKey =
            normalizedHintKey(
              key
            );

          const nextOutboundContext =
            (
              outboundContext
              || QCC_EXPLICIT_OUTBOUND_DEPENDENCY_HINT_KEYS.has(
                normalizedKey
              )
            );

          collectOutboundDependencyHintTokens(
            item,
            target,
            nextOutboundContext
          );
        }
      );
    }
  }


  function explicitDependencyCandidates(
    sourceCatalog,
    catalogs
  ) {
    const rawTokens =
      new Set();

    collectOutboundDependencyHintTokens(
      sourceCatalog?.dependency_hints,
      rawTokens
    );

    const references =
      new Set(
        Array.from(
          rawTokens
        )
          .map(
            normalizedReference
          )
          .filter(Boolean)
      );

    if (
      references.size === 0
    ) {
      return [];
    }


    const sourceSelector =
      clean(
        sourceCatalog?.selector
      );

    const candidates =
      [];


    for (const catalog of catalogs) {
      if (
        !isSupportedCatalog(
          catalog
        )
      ) {
        continue;
      }

      const selector =
        clean(
          catalog?.selector
        );

      if (
        !selector
        || selector === sourceSelector
      ) {
        continue;
      }


      const aliases =
        [
          selector,
          catalog?.element?.id,
          catalog?.element?.name
        ]
          .map(
            normalizedReference
          )
          .filter(Boolean);


      const referenced =
        aliases.some(
          (alias) =>
            references.has(
              alias
            )
        );


      if (
        referenced
        && !candidates.includes(
          selector
        )
      ) {
        candidates.push(
          selector
        );
      }
    }


    return candidates;
  }


  /*
   * Fallback estructural conservador.
   *
   * Si no existe hint explícito:
   *
   * - source posee opciones;
   * - el catálogo inmediatamente posterior existe;
   * - target empieza vacío.
   *
   * No declaramos causalidad aquí.
   * Únicamente proponemos un experimento.
   *
   * La causalidad real solo la puede declarar posteriormente
   * el executor físico + analyzer backend.
   */
  function structuralDependencyCandidates(
    sourceCatalog,
    catalogs
  ) {
    const sourceSelector =
      clean(
        sourceCatalog?.selector
      );

    const sourceIndex =
      catalogs.findIndex(
        (catalog) =>
          clean(
            catalog?.selector
          ) === sourceSelector
      );


    if (
      sourceIndex < 0
      || sourceIndex
        >= catalogs.length - 1
    ) {
      return [];
    }


    const target =
      catalogs[
        sourceIndex + 1
      ];


    if (
      !isSupportedCatalog(
        target
      )
    ) {
      return [];
    }


    const targetSelector =
      clean(
        target?.selector
      );


    if (
      !targetSelector
      || targetSelector
        === sourceSelector
    ) {
      return [];
    }


    const targetOptions =
      Array.isArray(
        target?.options
      )
        ? target.options
        : [];


    if (
      targetOptions.length
      !== 0
    ) {
      return [];
    }


    return [
      targetSelector
    ];
  }


  function dependencyCandidates(
    sourceCatalog,
    catalogs
  ) {
    if (
      !sourceCatalog
      || !Array.isArray(
          catalogs
        )
    ) {
      return [];
    }


    const explicit =
      explicitDependencyCandidates(
        sourceCatalog,
        catalogs
      );


    if (
      explicit.length > 0
    ) {
      return explicit;
    }


    return structuralDependencyCandidates(
      sourceCatalog,
      catalogs
    );
  }


  function alternativeOptionOf(
    catalog
  ) {
    const selectedValue =
      clean(
        catalog?.state
          ?.selected_value
      );

    const selectedLabel =
      clean(
        catalog?.state
          ?.selected_label
      );


    const options =
      Array.isArray(
        catalog?.options
      )
        ? catalog.options
        : [];


    for (const option of options) {
      if (
        option?.disabled === true
      ) {
        continue;
      }


      const value =
        clean(
          option?.value
        );

      const label =
        clean(
          option?.label
        );


      /*
       * Nunca fabricamos RAW.
       *
       * Para custom_select el label observado puede ser la
       * única identidad física disponible.
       */
      if (
        !value
        && !label
      ) {
        continue;
      }


      if (
        (
          value
          && selectedValue
          && value === selectedValue
        )
        || (
          label
          && selectedLabel
          && label === selectedLabel
        )
        || option?.selected === true
      ) {
        continue;
      }


      return {
        value,
        label
      };
    }


    return null;
  }


  function planCapture(
    capture,
    options = {}
  ) {
    const maxPlans =
      Math.max(
        1,
        Number(
          options?.max_plans
          ?? 1
        )
      );


    const catalogs =
      mainCatalogsFromCapture(
        capture
      );


    const plans =
      [];


    for (const source of catalogs) {
      const sourceSelector =
        clean(
          source?.selector
        );


      if (!sourceSelector) {
        continue;
      }


      const sourceOptions =
        Array.isArray(
          source?.options
        )
          ? source.options
          : [];


      if (
        sourceOptions.length === 0
      ) {
        continue;
      }


      const alternative =
        alternativeOptionOf(
          source
        );


      if (!alternative) {
        continue;
      }


      const candidates =
        dependencyCandidates(
          source,
          catalogs
        );


      /*
       * Nunca elegimos arbitrariamente.
       */
      if (
        candidates.length !== 1
      ) {
        continue;
      }


      plans.push({
        source_selector:
          sourceSelector,

        target_selector:
          candidates[0],

        requested_value:
          alternative.value,

        requested_label:
          alternative.label
      });


      if (
        plans.length
        >= maxPlans
      ) {
        break;
      }
    }


    return plans;
  }


  function optionsFingerprint(
    options
  ) {
    const normalized =
      (
        Array.isArray(
          options
        )
          ? options
          : []
      ).map(
        (option) => ({
          value:
            clean(
              option?.value
            ),

          label:
            clean(
              option?.label
            ),

          disabled:
            option?.disabled === true
        })
      );


    return JSON.stringify(
      normalized
    );
  }


  root.QccCatalogDependencyPlanner =
    Object.freeze({
      mainCatalogsFromCapture,
      dependencyCandidates,
      alternativeOptionOf,
      planCapture,
      optionsFingerprint
    });

})(
  globalThis
);
