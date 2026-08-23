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


chrome.runtime.onInstalled.addListener(() => {
  configureSidePanel();
});


chrome.runtime.onStartup.addListener(() => {
  configureSidePanel();
});


configureSidePanel();
