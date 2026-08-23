async function configureSidePanel() {
  if (!chrome.sidePanel) {
    return;
  }

  try {
    await chrome.sidePanel.setPanelBehavior({
      openPanelOnActionClick: true
    });
  } catch (error) {
    console.error(
      "[QCC] No se pudo configurar Side Panel:",
      error
    );
  }
}


/*
 * Captura ejecutada DENTRO de cada frame permitido
 * de la pestaña activa.
 *
 * Es deliberadamente READ-ONLY:
 * - no pulsa controles;
 * - no modifica campos;
 * - no dispara eventos;
 * - no altera el DOM de la página.
 */
function captureDomFrame() {
  function cleanText(
    value,
    limit = 300
  ) {
    const text =
      String(value || "")
        .replace(/\s+/g, " ")
        .trim();

    if (
      text.length <= limit
    ) {
      return text;
    }

    return text.slice(
      0,
      limit
    );
  }


  function attributesOf(
    element
  ) {
    const attributes = {};

    for (
      const attribute
      of Array.from(
        element.attributes
        || []
      )
    ) {
      attributes[
        String(
          attribute.name
          || ""
        )
      ] = String(
        attribute.value
        || ""
      );
    }

    return attributes;
  }


  function catalogSelectorOf(
    element
  ) {
    const id =
      String(
        element.id
        || ""
      );

    if (id) {
      if (
        globalThis.CSS
        && typeof CSS.escape
          === "function"
      ) {
        return (
          "#"
          + CSS.escape(id)
        );
      }

      return (
        "#"
        + id.replace(
          /[^A-Za-z0-9_-]/g,
          function (value) {
            return "\\" + value;
          }
        )
      );
    }


    const name =
      String(
        element.name
        || ""
      );

    if (name) {
      const escapedName =
        name
          .replace(
            /\\/g,
            "\\\\"
          )
          .replace(
            /"/g,
            '\\"'
          );

      const selector =
        'select[name="'
        + escapedName
        + '"]';

      try {
        if (
          document
            .querySelectorAll(
              selector
            )
            .length === 1
        ) {
          return selector;
        }
      } catch (_) {
        // Continúa con selector estructural.
      }
    }


    const parts = [];
    let current = element;

    while (
      current
      && current.nodeType === 1
      && current
        !== document.documentElement
    ) {
      const tag =
        String(
          current.tagName
          || ""
        ).toLowerCase();

      const parent =
        current.parentElement;

      if (
        !tag
        || !parent
      ) {
        break;
      }

      const siblings =
        Array.from(
          parent.children
          || []
        ).filter(
          function (candidate) {
            return (
              candidate.tagName
              === current.tagName
            );
          }
        );

      const position =
        siblings.indexOf(
          current
        ) + 1;

      parts.unshift(
        tag
        + ":nth-of-type("
        + position
        + ")"
      );

      current = parent;

      if (
        current
        === document.body
      ) {
        parts.unshift(
          "body"
        );

        break;
      }
    }

    return parts.join(
      " > "
    );
  }


  function catalogLabelOf(
    element
  ) {
    return Array.from(
      element.labels
      || []
    )
      .map(
        function (label) {
          return cleanText(
            label.textContent
            || "",
            300
          );
        }
      )
      .filter(Boolean)
      .join(" | ");
  }


  function catalogDependencyHintsOf(
    element
  ) {
    const attributes =
      attributesOf(
        element
      );

    const hints = {};

    for (
      const [
        name,
        value
      ]
      of Object.entries(
        attributes
      )
    ) {
      const normalizedName =
        String(
          name
          || ""
        ).toLowerCase();

      const normalizedValue =
        String(
          value
          || ""
        );

      const semanticHint =
        (
          normalizedName
            .startsWith("data-")
          || normalizedName
            === "onchange"
          || normalizedName
            === "aria-controls"
          || normalizedName
            === "aria-owns"
          || normalizedName
            === "list"
        );

      let referencesElement =
        false;

      if (normalizedValue) {
        const referencedElement =
          document
            .getElementById(
              normalizedValue
            );

        referencesElement =
          (
            referencedElement !== null
            && referencedElement !== element
          );
      }

      if (
        semanticHint
        || referencesElement
      ) {
        hints[name] =
          normalizedValue;
      }
    }

    return hints;
  }


  function captureCatalogProbe() {
    const catalogs =
      Array.from(
        document.querySelectorAll(
          "select"
        )
      ).map(
        function (select) {
          const selectedOptions =
            Array.from(
              select.selectedOptions
              || []
            );

          const firstSelected =
            selectedOptions[0]
            || null;

          const options =
            Array.from(
              select.options
              || []
            ).map(
              function (option) {
                return {
                  value:
                    String(
                      option.value
                      || ""
                    ),

                  label:
                    cleanText(
                      option.label
                      || option.textContent
                      || "",
                      300
                    ),

                  selected:
                    Boolean(
                      option.selected
                    ),

                  disabled:
                    Boolean(
                      option.disabled
                    )
                };
              }
            );

          return {
            catalog_type:
              "native_select",

            selector:
              catalogSelectorOf(
                select
              ),

            element: {
              tag:
                "select",

              id:
                String(
                  select.id
                  || ""
                ),

              name:
                String(
                  select.name
                  || ""
                ),

              classes:
                Array.from(
                  select.classList
                  || []
                ),

              label_text:
                catalogLabelOf(
                  select
                ),

              attributes:
                attributesOf(
                  select
                )
            },

            state: {
              selected_value:
                String(
                  select.value
                  || ""
                ),

              selected_label:
                (
                  firstSelected
                  ? cleanText(
                      firstSelected.label
                      || firstSelected
                        .textContent
                      || "",
                      300
                    )
                  : ""
                ),

              selected_values:
                selectedOptions.map(
                  function (option) {
                    return String(
                      option.value
                      || ""
                    );
                  }
                ),

              selected_index:
                Number(
                  select.selectedIndex
                ),

              disabled:
                Boolean(
                  select.disabled
                ),

              required:
                Boolean(
                  select.required
                ),

              multiple:
                Boolean(
                  select.multiple
                )
            },

            options_count:
              options.length,

            options,

            dependency_hints:
              catalogDependencyHintsOf(
                select
              )
          };
        }
      );

    return {
      schema_version:
        1,

      catalog_count:
        catalogs.length,

      elements:
        catalogs
    };
  }


  function visibilityOf(
    element
  ) {
    try {
      const rect =
        element
          .getBoundingClientRect();

      const style =
        window.getComputedStyle(
          element
        );

      return Boolean(
        rect.width > 0
        && rect.height > 0
        && style.display !== "none"
        && style.visibility
          !== "hidden"
      );

    } catch (_) {
      return false;
    }
  }


  function inspectShadowRoots(
    root,
    parentPath,
    target
  ) {
    let elements = [];

    try {
      elements =
        Array.from(
          root.querySelectorAll(
            "*"
          )
        );
    } catch (_) {
      return;
    }

    elements.forEach(
      (
        host,
        index
      ) => {
        let shadowRoot = null;

        try {
          shadowRoot =
            host.shadowRoot;
        } catch (_) {
          shadowRoot = null;
        }

        if (!shadowRoot) {
          return;
        }

        const shadowPath =
          (
            parentPath
            + "/shadow-"
            + String(
              target.length + 1
            )
          );

        target.push({
          shadow_path:
            shadowPath,

          parent_path:
            parentPath,

          host_index:
            index,

          host_tag:
            String(
              host.tagName
              || ""
            ).toLowerCase(),

          host_id:
            String(
              host.id
              || ""
            ),

          host_classes:
            Array.from(
              host.classList
              || []
            ),

          html:
            String(
              shadowRoot.innerHTML
              || ""
            )
        });

        inspectShadowRoots(
          shadowRoot,
          shadowPath,
          target
        );
      }
    );
  }


  const elements =
    Array.from(
      document.querySelectorAll(
        "*"
      )
    );


  const inventory =
    elements.map(
      (
        element,
        index
      ) => {
        const tag =
          String(
            element.tagName
            || ""
          ).toLowerCase();

        const record = {
          index:
            index,

          tag:
            tag,

          id:
            String(
              element.id
              || ""
            ),

          name:
            String(
              element.getAttribute?.(
                "name"
              )
              || ""
            ),

          type:
            String(
              element.getAttribute?.(
                "type"
              )
              || ""
            ),

          role:
            String(
              element.getAttribute?.(
                "role"
              )
              || ""
            ),

          classes:
            Array.from(
              element.classList
              || []
            ),

          attributes:
            attributesOf(
              element
            ),

          text:
            cleanText(
              element.innerText
              || element.textContent
            ),

          visible:
            visibilityOf(
              element
            ),

          disabled:
            Boolean(
              element.disabled
            ),

          has_open_shadow_root:
            Boolean(
              element.shadowRoot
            )
        };


        if (
          tag === "iframe"
          || tag === "frame"
        ) {
          record.src =
            String(
              element.getAttribute(
                "src"
              )
              || ""
            );
        }


        if (
          tag === "a"
        ) {
          record.href =
            String(
              element.getAttribute(
                "href"
              )
              || ""
            );
        }


        if (
          tag === "form"
        ) {
          record.action =
            String(
              element.getAttribute(
                "action"
              )
              || ""
            );

          record.method =
            String(
              element.getAttribute(
                "method"
              )
              || ""
            );
        }


        if (
          tag === "select"
        ) {
          record.options =
            Array.from(
              element.options
              || []
            ).map(
              (option) => ({
                value:
                  String(
                    option.value
                    || ""
                  ),

                text:
                  cleanText(
                    option.textContent,
                    200
                  ),

                selected:
                  Boolean(
                    option.selected
                  ),

                disabled:
                  Boolean(
                    option.disabled
                  )
              })
            );
        }


        return record;
      }
    );


  const shadowRoots = [];

  inspectShadowRoots(
    document,
    "document",
    shadowRoots
  );


  return {
    schema_version:
      1,

    captured_at:
      new Date()
        .toISOString(),

    url:
      String(
        window.location.href
        || ""
      ),

    origin:
      String(
        window.location.origin
        || ""
      ),

    pathname:
      String(
        window.location.pathname
        || ""
      ),

    hostname:
      String(
        window.location.hostname
        || ""
      ),

    title:
      String(
        document.title
        || ""
      ),

    ready_state:
      String(
        document.readyState
        || ""
      ),

    content_type:
      String(
        document.contentType
        || ""
      ),

    character_set:
      String(
        document.characterSet
        || ""
      ),

    html:
      (
        document.documentElement
        ? document
            .documentElement
            .outerHTML
        : ""
      ),

    counts: {
      elements:
        elements.length,

      forms:
        document.querySelectorAll(
          "form"
        ).length,

      inputs:
        document.querySelectorAll(
          "input"
        ).length,

      textareas:
        document.querySelectorAll(
          "textarea"
        ).length,

      selects:
        document.querySelectorAll(
          "select"
        ).length,

      buttons:
        document.querySelectorAll(
          "button,"
          + "input[type=button],"
          + "input[type=submit]"
        ).length,

      links:
        document.querySelectorAll(
          "a"
        ).length,

      tables:
        document.querySelectorAll(
          "table"
        ).length,

      iframe_elements:
        document.querySelectorAll(
          "iframe,frame"
        ).length,

      open_shadow_roots:
        shadowRoots.length
    },

    catalog_probe:
      captureCatalogProbe(),

    elements:
      inventory,

    shadow_roots:
      shadowRoots
  };
}


async function inspectActiveTabDom() {
  const tabs =
    await chrome.tabs.query({
      active: true,
      lastFocusedWindow: true
    });

  const tab =
    (
      Array.isArray(tabs)
      ? tabs[0]
      : null
    );

  if (
    !tab
    || !Number.isInteger(
      tab.id
    )
  ) {
    throw new Error(
      "QCC_DOM_ACTIVE_TAB_NOT_FOUND"
    );
  }


  const injectionResults =
    await chrome.scripting.executeScript({
      target: {
        tabId:
          tab.id,

        allFrames:
          true
      },

      world:
        "ISOLATED",

      func:
        captureDomFrame
    });


  const frames =
    (
      injectionResults
      || []
    ).map(
      (entry) => ({
        frame_id:
          entry.frameId,

        document_id:
          entry.documentId
          || null,

        result:
          entry.result
          || null
      })
    );


  const mainFrame =
    (
      frames.find(
        (frame) =>
          frame.frame_id === 0
      )
      || frames[0]
      || null
    );


  return {
    ok:
      true,

    capture_type:
      "QCC_EXTENSION_DOM_CAPTURE",

    schema_version:
      1,

    captured_at:
      new Date()
        .toISOString(),

    tab_id:
      tab.id,

    captured_frames:
      frames.length,

    main_url:
      (
        mainFrame
        ?.result
        ?.url
        || ""
      ),

    main_title:
      (
        mainFrame
        ?.result
        ?.title
        || ""
      ),

    frames:
      frames
  };
}


const QCC_CATALOG_EXPERIMENT_TWIN_ORIGIN =
  "http://127.0.0.1:8767";


function waitForCatalogExperiment(
  milliseconds
) {
  return new Promise(
    (resolve) => {
      setTimeout(
        resolve,
        milliseconds
      );
    }
  );
}


function setCatalogSelectionInPage(
  selector,
  requestedValue
) {
  const normalizedSelector =
    String(
      selector
      || ""
    ).trim();

  if (!normalizedSelector) {
    throw new Error(
      "QCC_CATALOG_EXPERIMENT_SELECTOR_REQUIRED"
    );
  }


  const select =
    document.querySelector(
      normalizedSelector
    );

  if (
    !select
    || String(
      select.tagName
      || ""
    ).toUpperCase() !== "SELECT"
  ) {
    throw new Error(
      "QCC_CATALOG_EXPERIMENT_SELECT_NOT_FOUND"
    );
  }


  if (select.disabled) {
    throw new Error(
      "QCC_CATALOG_EXPERIMENT_SELECT_DISABLED"
    );
  }


  if (select.multiple) {
    throw new Error(
      "QCC_CATALOG_EXPERIMENT_MULTIPLE_UNSUPPORTED"
    );
  }


  const originalValue =
    String(
      select.value
      || ""
    );

  const options =
    Array.from(
      select.options
      || []
    );


  let target = null;

  const explicitValue =
    String(
      requestedValue
      || ""
    );


  if (explicitValue) {
    target =
      options.find(
        (option) => (
          !option.disabled
          && String(
            option.value
            || ""
          ) === explicitValue
          && String(
            option.value
            || ""
          ) !== originalValue
        )
      )
      || null;

    if (!target) {
      throw new Error(
        "QCC_CATALOG_EXPERIMENT_VALUE_INVALID"
      );
    }

  } else {
    target =
      options.find(
        (option) => {
          const value =
            String(
              option.value
              || ""
            );

          return (
            !option.disabled
            && value
            && value !== originalValue
          );
        }
      )
      || null;
  }


  if (!target) {
    throw new Error(
      "QCC_CATALOG_EXPERIMENT_NO_ALTERNATIVE"
    );
  }


  const testValue =
    String(
      target.value
      || ""
    );


  select.value =
    testValue;


  select.dispatchEvent(
    new Event(
      "input",
      {
        bubbles: true
      }
    )
  );


  select.dispatchEvent(
    new Event(
      "change",
      {
        bubbles: true
      }
    )
  );


  return {
    selector:
      normalizedSelector,

    original_value:
      originalValue,

    test_value:
      testValue,

    test_label:
      String(
        target.label
        || target.textContent
        || ""
      ).trim(),

    options_count:
      options.length,

    current_value:
      String(
        select.value
        || ""
      )
  };
}


function restoreCatalogSelectionInPage(
  selector,
  originalValue
) {
  const normalizedSelector =
    String(
      selector
      || ""
    ).trim();

  const select =
    document.querySelector(
      normalizedSelector
    );

  if (
    !select
    || String(
      select.tagName
      || ""
    ).toUpperCase() !== "SELECT"
  ) {
    throw new Error(
      "QCC_CATALOG_EXPERIMENT_RESTORE_SELECT_NOT_FOUND"
    );
  }


  const value =
    String(
      originalValue
      ?? ""
    );


  const optionExists =
    Array.from(
      select.options
      || []
    ).some(
      (option) => (
        String(
          option.value
          || ""
        ) === value
      )
    );


  if (!optionExists) {
    throw new Error(
      "QCC_CATALOG_EXPERIMENT_RESTORE_VALUE_MISSING"
    );
  }


  select.value =
    value;


  select.dispatchEvent(
    new Event(
      "input",
      {
        bubbles: true
      }
    )
  );


  select.dispatchEvent(
    new Event(
      "change",
      {
        bubbles: true
      }
    )
  );


  return {
    selector:
      normalizedSelector,

    expected_value:
      value,

    restored_value:
      String(
        select.value
        || ""
      ),

    exact:
      (
        String(
          select.value
          || ""
        ) === value
      )
  };
}


function catalogRestoreTargetsFromCapture(
  capture
) {
  const mainFrame =
    (
      capture?.frames
      || []
    ).find(
      (frame) =>
        frame?.frame_id === 0
    );


  const catalogs =
    (
      mainFrame
      ?.result
      ?.catalog_probe
      ?.elements
      || []
    );


  return catalogs
    .filter(
      (catalog) => (
        catalog
        && catalog.catalog_type
          === "native_select"
        && String(
          catalog.selector
          || ""
        ).trim()
      )
    )
    .map(
      (catalog) => ({
        selector:
          String(
            catalog.selector
            || ""
          ).trim(),

        multiple:
          Boolean(
            catalog.state
            ?.multiple
          ),

        selected_value:
          String(
            catalog.state
            ?.selected_value
            ?? ""
          ),

        selected_values:
          Array.isArray(
            catalog.state
            ?.selected_values
          )
          ? catalog.state
              .selected_values
              .map(
                (value) =>
                  String(
                    value
                    ?? ""
                  )
              )
          : []
      })
    );
}


function restoreCatalogSnapshotInPage(
  targets
) {
  const results = [];


  for (
    const target
    of (
      Array.isArray(targets)
      ? targets
      : []
    )
  ) {
    const selector =
      String(
        target?.selector
        || ""
      ).trim();


    if (!selector) {
      continue;
    }


    const select =
      document.querySelector(
        selector
      );


    if (
      !select
      || String(
        select.tagName
        || ""
      ).toUpperCase() !== "SELECT"
    ) {
      results.push({
        selector:
          selector,

        status:
          "SELECT_NOT_FOUND"
      });

      continue;
    }


    const options =
      Array.from(
        select.options
        || []
      );


    let changed = false;
    let missing = [];


    if (
      Boolean(
        target.multiple
      )
    ) {
      const desired =
        new Set(
          Array.isArray(
            target.selected_values
          )
          ? target.selected_values.map(
              (value) =>
                String(
                  value
                  ?? ""
                )
            )
          : []
        );


      const available =
        new Set(
          options.map(
            (option) =>
              String(
                option.value
                ?? ""
              )
          )
        );


      missing =
        Array.from(
          desired
        ).filter(
          (value) =>
            !available.has(
              value
            )
        );


      for (
        const option
        of options
      ) {
        const shouldSelect =
          desired.has(
            String(
              option.value
              ?? ""
            )
          );


        if (
          option.selected
          !== shouldSelect
        ) {
          option.selected =
            shouldSelect;

          changed =
            true;
        }
      }

    } else {
      const desiredValue =
        String(
          target.selected_value
          ?? ""
        );


      const exists =
        options.some(
          (option) =>
            String(
              option.value
              ?? ""
            ) === desiredValue
        );


      if (!exists) {
        missing = [
          desiredValue
        ];

      } else if (
        String(
          select.value
          ?? ""
        ) !== desiredValue
      ) {
        select.value =
          desiredValue;

        changed =
          true;
      }
    }


    if (
      changed
      && missing.length === 0
    ) {
      select.dispatchEvent(
        new Event(
          "input",
          {
            bubbles: true
          }
        )
      );


      select.dispatchEvent(
        new Event(
          "change",
          {
            bubbles: true
          }
        )
      );
    }


    results.push({
      selector:
        selector,

      status:
        (
          missing.length
          ? "VALUE_NOT_AVAILABLE"
          : (
              changed
              ? "RESTORED"
              : "UNCHANGED"
            )
        ),

      missing_values:
        missing
    });
  }


  return {
    attempted:
      results.length,

    results:
      results
  };
}


function compareMainCatalogCaptures(
  beforeCapture,
  afterCapture
) {
  function catalogMap(
    capture
  ) {
    const mainFrame =
      (
        capture?.frames
        || []
      ).find(
        (frame) =>
          frame?.frame_id === 0
      );


    const catalogs =
      (
        mainFrame
        ?.result
        ?.catalog_probe
        ?.elements
        || []
      );


    const map =
      new Map();


    for (
      const catalog
      of catalogs
    ) {
      const selector =
        String(
          catalog?.selector
          || ""
        ).trim();


      if (!selector) {
        continue;
      }


      const state =
        catalog.state
        || {};


      const selectedValues =
        Array.isArray(
          state.selected_values
        )
        ? state.selected_values.map(
            (value) =>
              String(
                value
                ?? ""
              )
          )
        : [];


      const options =
        (
          catalog.options
          || []
        ).map(
          (option) => [
            String(
              option?.value
              ?? ""
            ),
            String(
              option?.label
              ?? ""
            ),
            Boolean(
              option?.disabled
            )
          ]
        );


      map.set(
        selector,
        {
          selected_value:
            String(
              state.selected_value
              ?? ""
            ),

          selected_values:
            selectedValues,

          options:
            options
        }
      );
    }


    return map;
  }


  const before =
    catalogMap(
      beforeCapture
    );

  const after =
    catalogMap(
      afterCapture
    );


  const selectors =
    new Set([
      ...before.keys(),
      ...after.keys()
    ]);


  const differences =
    [];


  for (
    const selector
    of selectors
  ) {
    const expected =
      before.get(
        selector
      );

    const actual =
      after.get(
        selector
      );


    if (
      !expected
      || !actual
    ) {
      differences.push({
        selector:
          selector,

        reason:
          "CATALOG_MISSING"
      });

      continue;
    }


    const selectionExact =
      (
        expected.selected_value
        === actual.selected_value

        && JSON.stringify(
          expected.selected_values
        ) === JSON.stringify(
          actual.selected_values
        )
      );


    const optionsExact =
      (
        JSON.stringify(
          expected.options
        ) === JSON.stringify(
          actual.options
        )
      );


    if (
      !selectionExact
      || !optionsExact
    ) {
      differences.push({
        selector:
          selector,

        selection_exact:
          selectionExact,

        options_exact:
          optionsExact,

        expected_value:
          expected.selected_value,

        actual_value:
          actual.selected_value
      });
    }
  }


  return {
    exact:
      differences.length === 0,

    compared_catalogs:
      selectors.size,

    differences:
      differences
  };
}


async function runTwinCatalogExperiment(
  selector,
  requestedValue = ""
) {
  const tabs =
    await chrome.tabs.query({
      active: true,
      lastFocusedWindow: true
    });


  const tab =
    (
      Array.isArray(tabs)
      ? tabs[0]
      : null
    );


  if (
    !tab
    || !Number.isInteger(
      tab.id
    )
  ) {
    throw new Error(
      "QCC_CATALOG_EXPERIMENT_ACTIVE_TAB_NOT_FOUND"
    );
  }


  let activeUrl = null;

  try {
    activeUrl =
      new URL(
        String(
          tab.url
          || ""
        )
      );
  } catch (_) {
    throw new Error(
      "QCC_CATALOG_EXPERIMENT_URL_INVALID"
    );
  }


  if (
    activeUrl.origin
    !== QCC_CATALOG_EXPERIMENT_TWIN_ORIGIN
  ) {
    throw new Error(
      "QCC_CATALOG_EXPERIMENT_TWIN_ONLY"
    );
  }


  const normalizedSelector =
    String(
      selector
      || ""
    ).trim();


  if (!normalizedSelector) {
    throw new Error(
      "QCC_CATALOG_EXPERIMENT_SELECTOR_REQUIRED"
    );
  }


  const before =
    await inspectActiveTabDom();


  let mutation = null;
  let after = null;
  let restoration = null;
  let restored = null;
  let restorationVerification = null;
  let restorePasses = [];


  try {
    const mutationResults =
      await chrome.scripting.executeScript({
        target: {
          tabId:
            tab.id,

          frameIds:
            [0]
        },

        world:
          "MAIN",

        func:
          setCatalogSelectionInPage,

        args: [
          normalizedSelector,
          String(
            requestedValue
            || ""
          )
        ]
      });


    mutation =
      (
        mutationResults
        && mutationResults[0]
        ? mutationResults[0].result
        : null
      );


    if (!mutation) {
      throw new Error(
        "QCC_CATALOG_EXPERIMENT_MUTATION_EMPTY"
      );
    }


    await waitForCatalogExperiment(
      500
    );


    after =
      await inspectActiveTabDom();

  } finally {
    if (
      mutation
      && Object.prototype.hasOwnProperty.call(
        mutation,
        "original_value"
      )
    ) {
      const restorationResults =
        await chrome.scripting.executeScript({
          target: {
            tabId:
              tab.id,

            frameIds:
              [0]
          },

          world:
            "MAIN",

          func:
            restoreCatalogSelectionInPage,

          args: [
            normalizedSelector,
            mutation.original_value
          ]
        });


      restoration =
        (
          restorationResults
          && restorationResults[0]
          ? restorationResults[0].result
          : null
        );


      await waitForCatalogExperiment(
        350
      );


      const restoreTargets =
        catalogRestoreTargetsFromCapture(
          before
        );


      restorePasses = [];


      for (
        let pass = 1;
        pass <= 6;
        pass += 1
      ) {
        const passResults =
          await chrome.scripting.executeScript({
            target: {
              tabId:
                tab.id,

              frameIds:
                [0]
            },

            world:
              "MAIN",

            func:
              restoreCatalogSnapshotInPage,

            args: [
              restoreTargets
            ]
          });


        restorePasses.push({
          pass:
            pass,

          result:
            (
              passResults
              && passResults[0]
              ? passResults[0].result
              : null
            )
        });


        await waitForCatalogExperiment(
          250
        );


        restored =
          await inspectActiveTabDom();


        restorationVerification =
          compareMainCatalogCaptures(
            before,
            restored
          );


        if (
          restorationVerification
          .exact === true
        ) {
          break;
        }
      }
    }
  }


  if (
    !restoration
    || restoration.exact !== true
  ) {
    throw new Error(
      "QCC_CATALOG_EXPERIMENT_RESTORE_FAILED"
    );
  }


  if (
    !restorationVerification
    || restorationVerification.exact !== true
  ) {
    throw new Error(
      "QCC_CATALOG_EXPERIMENT_RESTORE_STATE_MISMATCH"
    );
  }


  return {
    ok:
      true,

    experiment_type:
      "QCC_CATALOG_EXPERIMENT",

    schema_version:
      1,

    safety_mode:
      "TWIN_ONLY",

    origin:
      activeUrl.origin,

    selector:
      normalizedSelector,

    mutation:
      mutation,

    restoration:
      restoration,

    restoration_verification:
      restorationVerification,

    restore_passes:
      restorePasses,

    before:
      before,

    after:
      after,

    restored:
      restored
  };
}


chrome.runtime.onMessage.addListener(
  (
    message,
    _sender,
    sendResponse
  ) => {
    if (
      !message
      || message.type
        !== "QCC_DOM_INSPECT"
    ) {
      return false;
    }


    inspectActiveTabDom()
      .then(
        (capture) => {
          sendResponse(
            capture
          );
        }
      )
      .catch(
        (error) => {
          console.error(
            "[QCC] DOM inspect error:",
            error
          );

          sendResponse({
            ok:
              false,

            error:
              String(
                error?.message
                || error
                || "QCC_DOM_INSPECT_FAILED"
              )
          });
        }
      );


    // Mantiene vivo el canal mientras
    // termina executeScript().
    return true;
  }
);


chrome.runtime.onMessage.addListener(
  (
    message,
    _sender,
    sendResponse
  ) => {
    if (
      !message
      || message.type
        !== "QCC_CATALOG_EXPERIMENT"
    ) {
      return false;
    }


    runTwinCatalogExperiment(
      message.selector,
      message.requested_value
    )
      .then(
        (result) => {
          sendResponse(
            result
          );
        }
      )
      .catch(
        (error) => {
          console.error(
            "[QCC] Catalog experiment:",
            error
          );

          sendResponse({
            ok:
              false,

            error:
              String(
                error?.message
                || error
                || "QCC_CATALOG_EXPERIMENT_FAILED"
              )
          });
        }
      );


    return true;
  }
);


chrome.runtime.onInstalled.addListener(() => {
  configureSidePanel();
});


chrome.runtime.onStartup.addListener(() => {
  configureSidePanel();
});


configureSidePanel();
