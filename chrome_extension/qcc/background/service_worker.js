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


  function rectOf(
    element
  ) {
    try {
      const rect =
        element
          .getBoundingClientRect();

      return {
        x:
          Number(rect.x),

        y:
          Number(rect.y),

        width:
          Number(rect.width),

        height:
          Number(rect.height)
      };

    } catch (_) {
      return null;
    }
  }


  function viewportOf() {
    const root =
      document.documentElement;

    return {
      inner_width:
        Number(window.innerWidth),

      inner_height:
        Number(window.innerHeight),

      client_width:
        root
          ? Number(root.clientWidth)
          : null,

      client_height:
        root
          ? Number(root.clientHeight)
          : null,

      scroll_x:
        Number(window.scrollX),

      scroll_y:
        Number(window.scrollY),

      device_pixel_ratio:
        Number(
          window.devicePixelRatio
          || 1
        ),

      screen_x:
        Number(window.screenX),

      screen_y:
        Number(window.screenY),

      outer_width:
        Number(window.outerWidth),

      outer_height:
        Number(window.outerHeight)
    };
  }


  function visibilityOf(
    element,
    rect
  ) {
    try {
      if (!rect) {
        return false;
      }

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

        const rect =
          rectOf(
            element
          );

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

          rect:
            rect,

          visible:
            visibilityOf(
              element,
              rect
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

    viewport:
      viewportOf(),

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

    elements:
      inventory,

    shadow_roots:
      shadowRoots
  };
}


function captureVisualStyleProbe(
  selectors
) {
  const requested =
    (
      Array.isArray(selectors)
      ? selectors
      : []
    )
      .filter(
        (selector) =>
          typeof selector === "string"
          && selector.trim() !== ""
      )
      .map(
        (selector) =>
          selector.trim()
      )
      .slice(
        0,
        50
      );


  function rectOfElement(
    element
  ) {
    const rect =
      element.getBoundingClientRect();

    return {
      x:
        Number(rect.x),

      y:
        Number(rect.y),

      width:
        Number(rect.width),

      height:
        Number(rect.height)
    };
  }


  function styleSnapshot(
    style
  ) {
    const value = (property) =>
      String(
        style.getPropertyValue(
          property
        )
        || ""
      );

    return {
      display:
        value("display"),

      visibility:
        value("visibility"),

      opacity:
        value("opacity"),

      pointer_events:
        value("pointer-events"),

      font_family:
        value("font-family"),

      font_size:
        value("font-size"),

      font_weight:
        value("font-weight"),

      font_style:
        value("font-style"),

      line_height:
        value("line-height"),

      letter_spacing:
        value("letter-spacing"),

      color:
        value("color"),

      background_color:
        value("background-color"),

      background_image:
        value("background-image"),

      background_position:
        value("background-position"),

      background_repeat:
        value("background-repeat"),

      background_size:
        value("background-size"),

      border_top:
        value("border-top"),

      border_right:
        value("border-right"),

      border_bottom:
        value("border-bottom"),

      border_left:
        value("border-left"),

      border_radius:
        value("border-radius"),

      outline:
        value("outline"),

      outline_offset:
        value("outline-offset"),

      padding_top:
        value("padding-top"),

      padding_right:
        value("padding-right"),

      padding_bottom:
        value("padding-bottom"),

      padding_left:
        value("padding-left"),

      text_align:
        value("text-align"),

      text_transform:
        value("text-transform"),

      text_decoration_line:
        value("text-decoration-line"),

      text_decoration_color:
        value("text-decoration-color"),

      text_decoration_style:
        value("text-decoration-style"),

      white_space:
        value("white-space"),

      vertical_align:
        value("vertical-align"),

      overflow:
        value("overflow"),

      transform:
        value("transform"),

      box_shadow:
        value("box-shadow"),

      box_sizing:
        value("box-sizing"),

      appearance:
        value("appearance")
    };
  }


  function resolveElement(
    selector
  ) {
    const candidates =
      Array.from(
        document.querySelectorAll(
          selector
        )
      );

    let fallback = null;

    for (
      const element
      of candidates
    ) {
      const rect =
        rectOfElement(
          element
        );

      const style =
        window.getComputedStyle(
          element
        );

      const candidate = {
        element,
        rect,
        style
      };

      if (!fallback) {
        fallback =
          candidate;
      }

      if (
        rect.width > 0
        && rect.height > 0
        && style.display !== "none"
        && style.visibility
          !== "hidden"
      ) {
        return candidate;
      }
    }

    return fallback;
  }


  const elements =
    requested.map(
      (selector) => {
        try {
          const resolved =
            resolveElement(
              selector
            );

          if (!resolved) {
            return {
              selector,
              found:
                false
            };
          }

          const {
            element,
            rect,
            style
          } = resolved;

          return {
            selector,

            found:
              true,

            tag:
              String(
                element.tagName
                || ""
              ).toLowerCase(),

            id:
              String(
                element.id
                || ""
              ),

            classes:
              Array.from(
                element.classList
                || []
              ),

            disabled:
              Boolean(
                element.disabled
              ),

            visible:
              Boolean(
                rect.width > 0
                && rect.height > 0
                && style.display !== "none"
                && style.visibility
                  !== "hidden"
              ),

            rect,

            computed_style:
              styleSnapshot(
                style
              )
          };

        } catch (_) {
          return {
            selector,
            found:
              false,
            error:
              "INVALID_SELECTOR"
          };
        }
      }
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

    title:
      String(
        document.title
        || ""
      ),

    selectors_requested:
      requested.length,

    elements
  };
}


async function inspectActiveTabVisualStyle(
  selectors
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
      "QCC_VISUAL_ACTIVE_TAB_NOT_FOUND"
    );
  }

  const normalized =
    (
      Array.isArray(selectors)
      ? selectors
      : []
    )
      .filter(
        (selector) =>
          typeof selector === "string"
          && selector.trim() !== ""
      )
      .map(
        (selector) =>
          selector.trim()
      )
      .slice(
        0,
        50
      );

  if (
    normalized.length === 0
  ) {
    throw new Error(
      "QCC_VISUAL_SELECTORS_EMPTY"
    );
  }

  const injectionResults =
    await chrome.scripting.executeScript({
      target: {
        tabId:
          tab.id
      },

      world:
        "ISOLATED",

      func:
        captureVisualStyleProbe,

      args: [
        normalized
      ]
    });

  const result =
    (
      injectionResults
      || []
    )[0]?.result
    || null;

  if (!result) {
    throw new Error(
      "QCC_VISUAL_PROBE_EMPTY"
    );
  }

  return {
    ok:
      true,

    capture_type:
      "QCC_VISUAL_STYLE_PROBE",

    schema_version:
      1,

    captured_at:
      new Date()
        .toISOString(),

    tab_id:
      tab.id,

    main_url:
      result.url
      || "",

    main_title:
      result.title
      || "",

    result
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


chrome.runtime.onMessage.addListener(
  (
    message,
    _sender,
    sendResponse
  ) => {
    if (
      !message
      || message.type
        !== "QCC_VISUAL_STYLE_PROBE"
    ) {
      return false;
    }

    inspectActiveTabVisualStyle(
      message.selectors
    )
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
            "[QCC] Visual style probe:",
            error
          );

          sendResponse({
            ok:
              false,

            error:
              String(
                error?.message
                || error
                || "QCC_VISUAL_STYLE_PROBE_FAILED"
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
