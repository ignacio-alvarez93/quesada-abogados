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
const QCC_HUMAN_ACTION_BRIDGE_BASE_URL =
  "http://127.0.0.1:8766";

const QCC_HUMAN_LISTENER_TTL_MS =
  30000;

/*
 * Tokens válidos únicamente dentro del Service Worker.
 *
 * El código inyectado nunca conoce:
 * - session environment;
 * - site;
 * - fingerprint;
 * - policy;
 * - kind.
 *
 * El token une:
 *   capture document A
 *   -> injected listener
 *   -> runtime sender metadata.
 */
const qccHumanListenerArms =
  new Map();

/*
 * MV3 SAFETY
 *
 * El Service Worker puede ser suspendido entre
 * el armado y el click físico.
 *
 * El Map sigue siendo la cache rápida, pero el arm
 * se replica en chrome.storage.session:
 *
 * - memoria de sesión únicamente;
 * - desaparece al terminar la sesión de extensión;
 * - no contiene policy/kind/environment/fingerprint;
 * - sigue siendo single-shot;
 * - TTL sigue validándose antes del forward.
 */
const QCC_HUMAN_ARM_STORAGE_PREFIX =
  "qcc:human-arm:";


function qccHumanArmStorageKey(
  token
) {
  return (
    QCC_HUMAN_ARM_STORAGE_PREFIX
    + String(
        token
        || ""
      )
  );
}


async function pruneExpiredQccHumanListenerArms(
  now = Date.now()
) {
  const referenceTime =
    Number(
      now
    );

  /*
   * Cache rápida en memoria.
   */
  for (
    const [
      token,
      arm
    ]
    of qccHumanListenerArms.entries()
  ) {
    if (
      Number(
        arm?.expires_at
        || 0
      )
      <= referenceTime
    ) {
      qccHumanListenerArms.delete(
        token
      );
    }
  }

  /*
   * MV3 session storage.
   *
   * chrome.storage.session no expira claves
   * automáticamente por TTL.
   */
  const stored =
    await chrome.storage.session.get(
      null
    );

  const expiredKeys = [];

  for (
    const [
      key,
      arm
    ]
    of Object.entries(
      stored
      || {}
    )
  ) {
    if (
      !key.startsWith(
        QCC_HUMAN_ARM_STORAGE_PREFIX
      )
    ) {
      continue;
    }

    if (
      Number(
        arm?.expires_at
        || 0
      )
      <= referenceTime
    ) {
      expiredKeys.push(
        key
      );
    }
  }

  if (
    expiredKeys.length > 0
  ) {
    await chrome.storage.session.remove(
      expiredKeys
    );
  }

  return {
    removed:
      expiredKeys.length
  };
}


pruneExpiredQccHumanListenerArms()
  .catch(
    () => {}
  );


async function persistQccHumanListenerArm(
  token,
  arm
) {
  /*
   * Housekeeping oportunista:
   * antes de crear un nuevo arm eliminamos
   * cualquier evidencia MV3 ya caducada.
   */
  await pruneExpiredQccHumanListenerArms();

  const key =
    qccHumanArmStorageKey(
      token
    );

  qccHumanListenerArms.set(
    token,
    arm
  );

  await chrome.storage.session.set({
    [key]:
      arm
  });
}


async function takeQccHumanListenerArm(
  token
) {
  const key =
    qccHumanArmStorageKey(
      token
    );

  let arm =
    qccHumanListenerArms.get(
      token
    )
    || null;


  if (!arm) {
    const stored =
      await chrome.storage.session.get(
        key
      );

    arm =
      stored?.[key]
      || null;
  }


  /*
   * Single-shot antes de cualquier validación
   * posterior o request HTTP.
   */
  qccHumanListenerArms.delete(
    token
  );

  await chrome.storage.session.remove(
    key
  );

  return arm;
}




function installQccHumanClickListenerInFrame(
  framePath,
  selectors,
  listenerToken,
  ttlMs
) {

  /*
   * El click puede navegar inmediatamente.
   *
   * Port.postMessage() entrega la señal al proceso de
   * extensión sin esperar una respuesta del documento.
   *
   * La señal sigue siendo locator-only.
   */
  const qccHumanPortSend =
    (message) =>
      new Promise(
        (resolve, reject) => {
          try {
            const port =
              chrome.runtime.connect({
                name:
                  "QCC_HUMAN_DOM_ACTION_PORT"
              });

            port.postMessage(
              message
            );

            /*
             * No esperamos respuesta.
             * El documento puede desaparecer por navegación.
             */
            resolve({
              ok:
                true,

              queued:
                true
            });

          } catch (error) {
            reject(
              error
            );
          }
        }
      );


  const STATE_KEY =
    "__QCC_HUMAN_CLICK_LISTENER_V1__";

  const normalizedFramePath =
    String(
      framePath
      || ""
    ).trim();

  const normalizedToken =
    String(
      listenerToken
      || ""
    ).trim();

  const normalizedSelectors =
    Array.from(
      new Set(
        (
          Array.isArray(selectors)
          ? selectors
          : []
        )
          .map(
            (value) =>
              String(
                value
                || ""
              ).trim()
          )
          .filter(Boolean)
      )
    );

  const normalizedTtl =
    Math.max(
      1,
      Number(
        ttlMs
        || 30000
      )
    );


  const previous =
    globalThis[
      STATE_KEY
    ];

  if (
    previous
    && typeof previous.handler
      === "function"
  ) {
    try {
      document.removeEventListener(
        "pointerdown",
        previous.handler,
        true
      );
    } catch (_) {
      // Fail closed.
    }
  }

  if (
    previous
    && previous.timer
  ) {
    try {
      clearTimeout(
        previous.timer
      );
    } catch (_) {
      // No-op.
    }
  }


  if (
    !normalizedFramePath
    || !normalizedToken
    || normalizedSelectors.length === 0
  ) {
    delete globalThis[
      STATE_KEY
    ];

    return {
      armed:
        false,

      reason:
        "INVALID_LISTENER_INPUT"
    };
  }


  let active = true;


  function cleanup() {
    if (!active) {
      return;
    }

    active = false;

    try {
      document.removeEventListener(
        "pointerdown",
        handler,
        true
      );
    } catch (_) {
      // No-op.
    }

    const current =
      globalThis[
        STATE_KEY
      ];

    if (
      current
      && current.token
        === normalizedToken
    ) {
      delete globalThis[
        STATE_KEY
      ];
    }
  }


  function matchedSelectorsForEvent(
    event
  ) {
    const matched =
      new Set();

    const target =
      event?.target;

    for (
      const selector
      of normalizedSelectors
    ) {
      let found =
        false;

      /*
       * Camino principal.
       *
       * Este es exactamente el mecanismo
       * validado físicamente en QCC-CLICK-2:
       *
       *   event.target.closest("#btncont")
       *
       * pointerdown + isTrusted=true.
       */
      try {
        if (
          target
          && target.nodeType === 1
          && typeof target.closest
            === "function"
          && target.closest(
            selector
          )
        ) {
          found =
            true;
        }
      } catch (_) {
        // Selector no resoluble.
      }

      /*
       * Fallback para composed/shadow paths.
       */
      if (!found) {
        const path =
          (
            typeof event.composedPath
              === "function"
            ? event.composedPath()
            : []
          );

        for (
          const candidate
          of path
        ) {
          if (
            !candidate
            || candidate.nodeType !== 1
            || typeof candidate.matches
              !== "function"
          ) {
            continue;
          }

          try {
            if (
              candidate.matches(
                selector
              )
            ) {
              found =
                true;

              break;
            }

          } catch (_) {
            // Selector no resoluble.
          }
        }
      }

      if (found) {
        matched.add(
          selector
        );
      }
    }

    return Array.from(
      matched
    );
  }


  function handler(
    event
  ) {
    /*
     * CRÍTICO:
     * solo eventos generados por interacción real
     * del usuario.
     *
     * La activación sintética/programática del DOM
     * produce isTrusted=false.
     */
    if (
      !active
      || !event
      || event.isTrusted !== true
    ) {
      return;
    }

    const matched =
      matchedSelectorsForEvent(
        event
      );

    /*
     * 0 matches:
     *   no sabemos qué acción fue.
     *
     * >1:
     *   causalidad ambigua.
     *
     * En ambos casos no emitimos nada.
     */
    if (
      matched.length !== 1
    ) {
      return;
    }

    const selector =
      matched[0];

    const observedAt =
      new Date()
        .toISOString();

    /*
     * Single-shot.
     *
     * Se desarma ANTES de transportar la señal.
     * Un segundo click requiere nueva observation A.
     */
    cleanup();

    try {
      const promise =
        qccHumanPortSend({
          type:
            "QCC_HUMAN_DOM_ACTION_SIGNAL",

          listener_token:
            normalizedToken,

          selector:
            selector,

          frame_path:
            normalizedFramePath,

          observed_at:
            observedAt
        });

      if (
        promise
        && typeof promise.catch
          === "function"
      ) {
        promise.catch(
          () => {}
        );
      }

    } catch (_) {
      // Fail closed:
      // si Service Worker no responde,
      // no se aprende nada.
    }
  }


  document.addEventListener(
    "pointerdown",
    handler,
    true
  );


  const timer =
    setTimeout(
      cleanup,
      normalizedTtl
    );


  globalThis[
    STATE_KEY
  ] = {
    handler:
      handler,

    timer:
      timer,

    token:
      normalizedToken
  };


  return {
    armed:
      true,

    target_count:
      normalizedSelectors.length
  };
}


function qccHumanFrameIdFromPath(
  framePath
) {
  const normalized =
    String(
      framePath
      || ""
    ).trim();

  if (
    normalized === "main"
  ) {
    return 0;
  }

  const match =
    /^qcc-frame:(\d+)$/
      .exec(
        normalized
      );

  if (!match) {
    return null;
  }

  const value =
    Number(
      match[1]
    );

  return (
    Number.isInteger(value)
    ? value
    : null
  );
}


function qccHumanListenerToken() {
  if (
    globalThis.crypto
    && typeof crypto.randomUUID
      === "function"
  ) {
    return crypto.randomUUID();
  }

  return (
    "qcc-human-"
    + Date.now().toString(36)
    + "-"
    + Math.random()
        .toString(36)
        .slice(2)
  );
}


function clearQccHumanListenerArmsFor(
  tabId,
  sessionId
) {
  for (
    const [
      token,
      arm
    ]
    of qccHumanListenerArms
  ) {
    if (
      arm?.tab_id === tabId
      || arm?.session_id
        === sessionId
    ) {
      qccHumanListenerArms.delete(
        token
      );
    }
  }
}


async function armQccHumanClickListeners(
  request
) {
  const tabId =
    Number(
      request?.tab_id
    );

  const sessionId =
    String(
      request?.session_id
      || ""
    ).trim();

  const targets =
    (
      Array.isArray(
        request?.targets
      )
      ? request.targets
      : []
    );

  const frameDocuments =
    (
      Array.isArray(
        request?.frame_documents
      )
      ? request.frame_documents
      : []
    );


  if (
    !Number.isInteger(
      tabId
    )
    || !sessionId
    || targets.length === 0
  ) {
    throw new Error(
      "QCC_HUMAN_LISTENER_ARM_INVALID"
    );
  }


  /*
   * Routing browser-only.
   *
   * document_id procede de la MISMA captura A.
   * No se envía al backend como identidad de acción.
   */
  const documentByFrame =
    new Map();

  for (
    const frame
    of frameDocuments
  ) {
    const frameId =
      Number(
        frame?.frame_id
      );

    const documentId =
      String(
        frame?.document_id
        || ""
      ).trim();

    if (
      Number.isInteger(
        frameId
      )
      && documentId
    ) {
      documentByFrame.set(
        frameId,
        documentId
      );
    }
  }


  const groups =
    new Map();

  for (
    const target
    of targets
  ) {
    if (
      !target
      || typeof target
        !== "object"
    ) {
      continue;
    }

    const keys =
      Object.keys(
        target
      ).sort();

    if (
      JSON.stringify(
        keys
      )
      !== JSON.stringify([
        "frame_path",
        "selector"
      ])
    ) {
      /*
       * Browser listener plan tampoco acepta
       * authority fields accidentales.
       */
      continue;
    }

    const selector =
      String(
        target.selector
        || ""
      ).trim();

    const framePath =
      String(
        target.frame_path
        || ""
      ).trim();

    const frameId =
      qccHumanFrameIdFromPath(
        framePath
      );

    if (
      !selector
      || frameId === null
    ) {
      continue;
    }

    const documentId =
      documentByFrame.get(
        frameId
      );

    /*
     * Sin documentId exacto NO hacemos fallback
     * a frameId.
     *
     * Eso impediría demostrar que seguimos en
     * el documento A capturado.
     */
    if (!documentId) {
      continue;
    }

    const groupKey =
      (
        framePath
        + "\n"
        + documentId
      );

    if (
      !groups.has(
        groupKey
      )
    ) {
      groups.set(
        groupKey,
        {
          frame_path:
            framePath,

          frame_id:
            frameId,

          document_id:
            documentId,

          selectors:
            []
        }
      );
    }

    const group =
      groups.get(
        groupKey
      );

    if (
      !group.selectors.includes(
        selector
      )
    ) {
      group.selectors.push(
        selector
      );
    }
  }


  clearQccHumanListenerArmsFor(
    tabId,
    sessionId
  );


  let armedFrames = 0;
  let armedTargets = 0;


  for (
    const group
    of groups.values()
  ) {
    const token =
      qccHumanListenerToken();

    const expiresAt =
      (
        Date.now()
        + QCC_HUMAN_LISTENER_TTL_MS
      );


    /*
     * Registramos primero para que un click
     * inmediatamente posterior a executeScript
     * también pueda validarse.
     */
    await persistQccHumanListenerArm(
      token,
      {
        session_id:
          sessionId,

        tab_id:
          tabId,

        frame_id:
          group.frame_id,

        frame_path:
          group.frame_path,

        document_id:
          group.document_id,

        selectors:
          Array.from(
            group.selectors
          ),

        expires_at:
          expiresAt
      }
    );


    try {
      const result =
        await chrome.scripting.executeScript({
          target: {
            tabId:
              tabId,

            /*
             * Exact-document binding.
             *
             * No frameIds simultáneamente.
             */
            documentIds: [
              group.document_id
            ]
          },

          world:
            "ISOLATED",

          func:
            installQccHumanClickListenerInFrame,

          args: [
            group.frame_path,
            group.selectors,
            token,
            QCC_HUMAN_LISTENER_TTL_MS
          ]
        });


      const installed =
        result?.[0]?.result;

      if (
        !installed
        || installed.armed !== true
      ) {
        qccHumanListenerArms.delete(
          token
        );

        continue;
      }


      armedFrames += 1;
      armedTargets +=
        Number(
          installed.target_count
          || 0
        );

    } catch (_) {
      qccHumanListenerArms.delete(
        token
      );
    }
  }


  if (
    armedFrames === 0
  ) {
    throw new Error(
      "QCC_HUMAN_LISTENER_DOCUMENT_UNAVAILABLE"
    );
  }


  return {
    ok:
      true,

    armed:
      true,

    armed_frames:
      armedFrames,

    armed_targets:
      armedTargets
  };
}


async function forwardQccHumanDomActionSignal(
  message,
  sender
) {
  const token =
    String(
      message?.listener_token
      || ""
    ).trim();

  if (!token) {
    throw new Error(
      "QCC_HUMAN_SIGNAL_TOKEN_REQUIRED"
    );
  }


  const arm =
    await takeQccHumanListenerArm(
      token
    );

  if (!arm) {
    throw new Error(
      "QCC_HUMAN_SIGNAL_ARM_NOT_FOUND"
    );
  }



  if (
    Date.now()
    > Number(
        arm.expires_at
        || 0
      )
  ) {
    throw new Error(
      "QCC_HUMAN_SIGNAL_ARM_EXPIRED"
    );
  }


  /*
   * El sender es metadata suministrada por Chrome,
   * no por la página.
   */
  if (
    sender?.tab?.id
      !== arm.tab_id
  ) {
    throw new Error(
      "QCC_HUMAN_SIGNAL_TAB_MISMATCH"
    );
  }

  if (
    String(
      sender?.documentId
      || ""
    )
    !== arm.document_id
  ) {
    throw new Error(
      "QCC_HUMAN_SIGNAL_DOCUMENT_MISMATCH"
    );
  }

  if (
    Number(
      sender?.frameId
    )
    !== arm.frame_id
  ) {
    throw new Error(
      "QCC_HUMAN_SIGNAL_FRAME_MISMATCH"
    );
  }


  const selector =
    String(
      message?.selector
      || ""
    ).trim();

  const framePath =
    String(
      message?.frame_path
      || ""
    ).trim();

  const observedAt =
    String(
      message?.observed_at
      || ""
    ).trim();


  if (
    !selector
    || !framePath
    || !observedAt
  ) {
    throw new Error(
      "QCC_HUMAN_SIGNAL_INVALID"
    );
  }


  if (
    framePath
    !== arm.frame_path
  ) {
    throw new Error(
      "QCC_HUMAN_SIGNAL_FRAME_PATH_MISMATCH"
    );
  }


  if (
    !arm.selectors.includes(
      selector
    )
  ) {
    throw new Error(
      "QCC_HUMAN_SIGNAL_SELECTOR_MISMATCH"
    );
  }


  /*
   * event_id nace aquí, fuera de la página.
   */
  const eventId =
    qccHumanListenerToken();


  const url =
    (
      QCC_HUMAN_ACTION_BRIDGE_BASE_URL
      + "/qcc/session/"
      + encodeURIComponent(
          arm.session_id
        )
      + "/human-dom-action"
    );


  const response =
    await fetch(
      url,
      {
        method:
          "POST",

        cache:
          "no-store",

        headers: {
          "Content-Type":
            "application/json"
        },

        body:
          JSON.stringify({
            protocol_version:
              1,

            signal: {
              event_id:
                eventId,

              selector:
                selector,

              frame_path:
                framePath,

              observed_at:
                observedAt
            }
          })
      }
    );


  let payload = null;

  try {
    payload =
      await response.json();
  } catch (_) {
    payload = null;
  }


  if (!response.ok) {
    throw new Error(
      payload?.error
      || (
        "QCC_HUMAN_SIGNAL_HTTP_"
        + String(
            response.status
          )
      )
    );
  }


  if (
    !payload
    || payload.ok !== true
    || payload.accepted !== true
  ) {
    throw new Error(
      "QCC_HUMAN_SIGNAL_RESPONSE_INVALID"
    );
  }


  return {
    ok:
      true,

    accepted:
      true,

    event_id:
      payload.event_id
  };
}


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


  function viewportGeometryOfDocument() {
    const documentElement =
      document.documentElement;

    return {
      inner_width:
        Number(
          window.innerWidth
          || 0
        ),

      inner_height:
        Number(
          window.innerHeight
          || 0
        ),

      client_width:
        Number(
          documentElement
            ?.clientWidth
          || 0
        ),

      client_height:
        Number(
          documentElement
            ?.clientHeight
          || 0
        ),

      scroll_x:
        Number(
          window.scrollX
          || 0
        ),

      scroll_y:
        Number(
          window.scrollY
          || 0
        ),

      device_pixel_ratio:
        Number(
          window.devicePixelRatio
          || 1
        ),

      screen_x:
        Number(
          window.screenX
          || 0
        ),

      screen_y:
        Number(
          window.screenY
          || 0
        ),

      outer_width:
        Number(
          window.outerWidth
          || 0
        ),

      outer_height:
        Number(
          window.outerHeight
          || 0
        )
    };
  }


  function interactionSignalsOf(
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

      const viewportWidth =
        Number(
          window.innerWidth
          || document
            .documentElement
            ?.clientWidth
          || 0
        );

      const viewportHeight =
        Number(
          window.innerHeight
          || document
            .documentElement
            ?.clientHeight
          || 0
        );

      const visible =
        Boolean(
          rect.width > 0
          && rect.height > 0
          && style.display !== "none"
          && style.visibility
            !== "hidden"
        );

      const inViewport =
        Boolean(
          rect.bottom > 0
          && rect.right > 0
          && rect.top < viewportHeight
          && rect.left < viewportWidth
        );

      return {
        visible:
          visible,

        in_viewport:
          inViewport,

        opacity:
          String(
            style.opacity
            || ""
          ),

        pointer_events:
          String(
            style.pointerEvents
            || ""
          ),

        rect: {
          x:
            Number(rect.x),

          y:
            Number(rect.y),

          top:
            Number(rect.top),

          left:
            Number(rect.left),

          right:
            Number(rect.right),

          bottom:
            Number(rect.bottom),

          width:
            Number(rect.width),

          height:
            Number(rect.height)
        }
      };

    } catch (_) {
      return {
        visible:
          false,

        in_viewport:
          false,

        opacity:
          null,

        pointer_events:
          null,

        rect:
          null
      };
    }
  }


  function visibilityOf(
    element
  ) {
    return (
      interactionSignalsOf(
        element
      ).visible
    );
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

        const interactionSignals =
          interactionSignalsOf(
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

          visible:
            interactionSignals.visible,

          in_viewport:
            interactionSignals
              .in_viewport,

          opacity:
            interactionSignals.opacity,

          pointer_events:
            interactionSignals
              .pointer_events,

          rect:
            interactionSignals.rect,

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
          tag === "input"
          && (
            record.type === "radio"
            || record.type === "checkbox"
          )
        ) {
          record["checked"] =
            Boolean(
              element.checked
            );

          record.indeterminate =
            Boolean(
              element.indeterminate
            );
        }


        if (
          tag === "option"
        ) {
          record.selected =
            Boolean(
              element.selected
            );
        }


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

    viewport:
      viewportGeometryOfDocument(),

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


const QCC_MERCURIO_REAL_ORIGIN =
  "https://mercurio.delegaciondelgobierno.gob.es";

const QCC_MERCURIO_REAL_SOURCE_SELECTOR =
  "#extCodigoMunicipio";

const QCC_MERCURIO_REAL_TARGET_SELECTOR =
  "#extCodigoLocalidad";


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


function catalogFromMainCapture(
  capture,
  selector
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

  return (
    catalogs.find(
      (catalog) =>
        String(
          catalog?.selector
          || ""
        ) === selector
    )
    || null
  );
}


function sanitizedCatalogOptions(
  catalog
) {
  return (
    Array.isArray(
      catalog?.options
    )
    ? catalog.options.map(
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
    : []
  );
}



async function requireMercurioRealCatalogTab() {
  const tabs =
    await chrome.tabs.query({
      active: true,
      currentWindow: true
    });

  const tab =
    tabs[0];

  if (!tab || !tab.id) {
    throw new Error(
      "QCC_MERCURIO_REAL_TAB_REQUIRED"
    );
  }

  const url =
    new URL(
      String(
        tab.url
        || ""
      )
    );

  if (
    url.origin
      !== QCC_MERCURIO_REAL_ORIGIN
    || !url.pathname.startsWith(
      "/mercurio/"
    )
  ) {
    throw new Error(
      "QCC_MERCURIO_REAL_ORIGIN_REJECTED"
    );
  }

  return tab;
}


function normalizedCatalogSelector(
  selector
) {
  const value =
    String(
      selector
      || ""
    ).trim();

  if (!value) {
    throw new Error(
      "QCC_CATALOG_SELECTOR_REQUIRED"
    );
  }

  return value;
}


function catalogOptionsFingerprint(
  catalog
) {
  return JSON.stringify(
    sanitizedCatalogOptions(
      catalog
    )
  );
}


async function runMercurioRealSequentialCatalogStep(
  sourceSelector,
  targetSelector,
  requestedValue
) {
  const source =
    normalizedCatalogSelector(
      sourceSelector
    );

  const target =
    normalizedCatalogSelector(
      targetSelector
    );

  if (source === target) {
    throw new Error(
      "QCC_CATALOG_SOURCE_TARGET_SAME"
    );
  }

  const requested =
    String(
      requestedValue
      || ""
    );

  if (!requested) {
    throw new Error(
      "QCC_CATALOG_VALUE_REQUIRED"
    );
  }

  const tab =
    await requireMercurioRealCatalogTab();

  const injection =
    await chrome.scripting.executeScript({
      target: {
        tabId: tab.id
      },
      func:
        setCatalogSelectionInPage,
      args: [
        source,
        requested
      ]
    });

  const mutation =
    injection?.[0]?.result;

  if (
    !mutation
    || String(
      mutation.current_value
      || ""
    ) !== requested
  ) {
    throw new Error(
      "QCC_CATALOG_STEP_SELECTION_MISMATCH"
    );
  }

  /*
   * Damos tiempo a que Mercurio dispare
   * y procese la cascada AJAX.
   */
  await waitForCatalogExperiment(
    700
  );

  let previousFingerprint =
    null;

  let stableObservations =
    0;

  let lastCapture =
    null;

  let lastTargetCatalog =
    null;

  for (
    let attempt = 0;
    attempt < 12;
    attempt += 1
  ) {
    const capture =
      await inspectActiveTabDom();

    const sourceCatalog =
      catalogFromMainCapture(
        capture,
        source
      );

    const targetCatalog =
      catalogFromMainCapture(
        capture,
        target
      );

    const selectedValue =
      String(
        sourceCatalog
          ?.state
          ?.selected_value
        || ""
      );

    if (selectedValue !== requested) {
      stableObservations =
        0;

      previousFingerprint =
        null;

      await waitForCatalogExperiment(
        250
      );

      continue;
    }

    const fingerprint =
      catalogOptionsFingerprint(
        targetCatalog
      );

    if (
      previousFingerprint !== null
      && fingerprint
        === previousFingerprint
    ) {
      stableObservations += 1;
    } else {
      stableObservations =
        0;
    }

    previousFingerprint =
      fingerprint;

    lastCapture =
      capture;

    lastTargetCatalog =
      targetCatalog;

    if (stableObservations >= 1) {
      return {
        ok: true,

        source: {
          selector:
            source,

          test_value:
            requested,

          test_label:
            String(
              mutation.test_label
              || ""
            ),

          current_value:
            selectedValue
        },

        target: {
          selector:
            target,

          options_count:
            (
              lastTargetCatalog
                ?.options
                ?.length
              || 0
            ),

          options:
            sanitizedCatalogOptions(
              lastTargetCatalog
            )
        },

        stabilization: {
          stable:
            true,

          attempts:
            attempt + 1
        }
      };
    }

    await waitForCatalogExperiment(
      250
    );
  }

  void lastCapture;

  throw new Error(
    "QCC_CATALOG_TARGET_NOT_STABLE"
  );
}


async function runMercurioRealSequentialCatalogRestore(
  sourceSelector,
  targetSelector,
  originalValue,
  expectedTargetOptions
) {
  const source =
    normalizedCatalogSelector(
      sourceSelector
    );

  const target =
    normalizedCatalogSelector(
      targetSelector
    );

  const expectedSourceValue =
    String(
      originalValue
      ?? ""
    );

  const expectedTargetFingerprint =
    JSON.stringify(
      Array.isArray(
        expectedTargetOptions
      )
      ? expectedTargetOptions
      : []
    );

  const tab =
    await requireMercurioRealCatalogTab();

  const injection =
    await chrome.scripting.executeScript({
      target: {
        tabId: tab.id
      },
      func:
        restoreCatalogSelectionInPage,
      args: [
        source,
        expectedSourceValue
      ]
    });

  const restore =
    injection?.[0]?.result;

  if (
    !restore
    || restore.exact !== true
  ) {
    throw new Error(
      "QCC_CATALOG_FINAL_RESTORE_SELECTION_FAILED"
    );
  }

  await waitForCatalogExperiment(
    700
  );

  for (
    let attempt = 0;
    attempt < 16;
    attempt += 1
  ) {
    const capture =
      await inspectActiveTabDom();

    const sourceCatalog =
      catalogFromMainCapture(
        capture,
        source
      );

    const targetCatalog =
      catalogFromMainCapture(
        capture,
        target
      );

    const sourceExact =
      (
        String(
          sourceCatalog
            ?.state
            ?.selected_value
          || ""
        )
        === expectedSourceValue
      );

    const targetExact =
      (
        catalogOptionsFingerprint(
          targetCatalog
        )
        === expectedTargetFingerprint
      );

    if (
      sourceExact
      && targetExact
    ) {
      return {
        ok: true,

        exact:
          true,

        source_selector:
          source,

        target_selector:
          target,

        compared_catalogs:
          2,

        attempts:
          attempt + 1
      };
    }

    await waitForCatalogExperiment(
      250
    );
  }

  throw new Error(
    "QCC_CATALOG_FINAL_RESTORE_MISMATCH"
  );
}


async function runRealMercurioCatalogProbe(
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
    || !Number.isInteger(tab.id)
  ) {
    throw new Error(
      "QCC_MERCURIO_REAL_ACTIVE_TAB_NOT_FOUND"
    );
  }

  const activeUrl =
    new URL(
      String(
        tab.url
        || ""
      )
    );

  if (
    activeUrl.origin
      !== QCC_MERCURIO_REAL_ORIGIN
    || !activeUrl.pathname.startsWith(
      "/mercurio/"
    )
  ) {
    throw new Error(
      "QCC_MERCURIO_REAL_ORIGIN_REJECTED"
    );
  }

  const before =
    await inspectActiveTabDom();

  const sourceBefore =
    catalogFromMainCapture(
      before,
      QCC_MERCURIO_REAL_SOURCE_SELECTOR
    );

  if (!sourceBefore) {
    throw new Error(
      "QCC_MERCURIO_REAL_SOURCE_NOT_FOUND"
    );
  }

  let mutation = null;
  let after = null;
  let restored = null;
  let restoration = null;

  try {
    const results =
      await chrome.scripting.executeScript({
        target: {
          tabId: tab.id,
          frameIds: [0]
        },

        world:
          "MAIN",

        func:
          setCatalogSelectionInPage,

        args: [
          QCC_MERCURIO_REAL_SOURCE_SELECTOR,
          String(
            requestedValue
            || ""
          )
        ]
      });

    mutation =
      results?.[0]?.result
      || null;

    if (!mutation) {
      throw new Error(
        "QCC_MERCURIO_REAL_MUTATION_EMPTY"
      );
    }

    await waitForCatalogExperiment(
      900
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
      const results =
        await chrome.scripting.executeScript({
          target: {
            tabId: tab.id,
            frameIds: [0]
          },

          world:
            "MAIN",

          func:
            restoreCatalogSelectionInPage,

          args: [
            QCC_MERCURIO_REAL_SOURCE_SELECTOR,
            mutation.original_value
          ]
        });

      restoration =
        results?.[0]?.result
        || null;

      await waitForCatalogExperiment(
        900
      );

      restored =
        await inspectActiveTabDom();
    }
  }

  if (
    !restoration
    || restoration.exact !== true
  ) {
    throw new Error(
      "QCC_MERCURIO_REAL_RESTORE_FAILED"
    );
  }

  const QCC_MERCURIO_REAL_STABILIZATION_ATTEMPTS =
    8;

  let verification =
    compareMainCatalogCaptures(
      before,
      restored
    );

  for (
    let attempt = 1;
    attempt < QCC_MERCURIO_REAL_STABILIZATION_ATTEMPTS;
    attempt += 1
  ) {
    if (verification.exact === true) {
      break;
    }

    await waitForCatalogExperiment(
      500
    );

    restored =
      await inspectActiveTabDom();

    verification =
      compareMainCatalogCaptures(
        before,
        restored
      );
  }

  if (verification.exact !== true) {
    console.error(
      "[QCC] Mercurio REAL restore mismatch:",
      verification.differences
    );

    throw new Error(
      "QCC_MERCURIO_REAL_STATE_MISMATCH::"
      + JSON.stringify(
          verification.differences.slice(
            0,
            5
          )
        )
    );
  }

  const targetAfter =
    catalogFromMainCapture(
      after,
      QCC_MERCURIO_REAL_TARGET_SELECTOR
    );

  if (!targetAfter) {
    throw new Error(
      "QCC_MERCURIO_REAL_TARGET_NOT_FOUND"
    );
  }

  const options =
    sanitizedCatalogOptions(
      targetAfter
    );

  return {
    ok:
      true,

    harvest_type:
      "QCC_MERCURIO_REAL_CATALOG_PROBE",

    schema_version:
      1,

    origin:
      activeUrl.origin,

    pathname:
      activeUrl.pathname,

    source_selector:
      QCC_MERCURIO_REAL_SOURCE_SELECTOR,

    target_selector:
      QCC_MERCURIO_REAL_TARGET_SELECTOR,

    source: {
      original_value:
        String(
          mutation.original_value
          || ""
        ),

      test_value:
        String(
          mutation.test_value
          || ""
        ),

      restored_value:
        String(
          restoration.restored_value
          || ""
        )
    },

    target: {
      options_count:
        options.length,

      options:
        options
    },

    restoration_verification: {
      exact:
        true,

      compared_catalogs:
        verification.compared_catalogs
    }
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
      message?.type
        !== "QCC_ARM_HUMAN_LISTENER"
    ) {
      return false;
    }

    armQccHumanClickListeners(
      message
    )
      .then(
        sendResponse
      )
      .catch(
        (error) => {
          sendResponse({
            ok:
              false,

            armed:
              false,

            error:
              String(
                error?.message
                || error
              )
          });
        }
      );

    return true;
  }
);



/*
 * QCC_HUMAN_DOM_ACTION_PORT_RECEIVER
 *
 * Transporte robusto ante navegación inmediata.
 *
 * port.sender conserva:
 * - tab
 * - documentId
 * - frameId
 *
 * forwardQccHumanDomActionSignal mantiene TODA
 * la validación/canonicalización existente.
 */
chrome.runtime.onConnect.addListener(
  (port) => {
    if (
      port?.name
        !== "QCC_HUMAN_DOM_ACTION_PORT"
    ) {
      return;
    }

    const sender =
      port.sender;

    port.onMessage.addListener(
      (message) => {
        if (
          message?.type
            !== "QCC_HUMAN_DOM_ACTION_SIGNAL"
        ) {
          return;
        }

        forwardQccHumanDomActionSignal(
          message,
          sender
        )
          .catch(
            (error) => {
              console.warn(
                "[QCC] Human DOM action port:",
                String(
                  error?.message
                  || error
                )
              );
            }
          );
      }
    );
  }
);


chrome.runtime.onMessage.addListener(
  (
    message,
    sender,
    sendResponse
  ) => {
    if (
      message?.type
        !== "QCC_HUMAN_DOM_ACTION_SIGNAL"
    ) {
      return false;
    }

    forwardQccHumanDomActionSignal(
      message,
      sender
    )
      .then(
        sendResponse
      )
      .catch(
        (error) => {
          sendResponse({
            ok:
              false,

            accepted:
              false,

            error:
              String(
                error?.message
                || error
              )
          });
        }
      );

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


chrome.runtime.onMessage.addListener(
  (
    message,
    _sender,
    sendResponse
  ) => {
    if (
      !message
      || message.type
        !== "QCC_MERCURIO_REAL_CATALOG_PROBE"
    ) {
      return false;
    }

    runRealMercurioCatalogProbe(
      message.requested_value
    )
      .then(sendResponse)
      .catch(
        (error) => {
          sendResponse({
            ok:
              false,

            error:
              String(
                error?.message
                || error
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


chrome.runtime.onMessage.addListener(
  (
    message,
    _sender,
    sendResponse
  ) => {
    if (
      message?.type
        === "QCC_MERCURIO_REAL_CATALOG_STEP"
    ) {
      runMercurioRealSequentialCatalogStep(
        message.source_selector,
        message.target_selector,
        message.requested_value
      )
        .then(
          sendResponse
        )
        .catch(
          (error) => {
            sendResponse({
              ok: false,
              error:
                String(
                  error?.message
                  || error
                )
            });
          }
        );

      return true;
    }

    if (
      message?.type
        === "QCC_MERCURIO_REAL_CATALOG_RESTORE"
    ) {
      runMercurioRealSequentialCatalogRestore(
        message.source_selector,
        message.target_selector,
        message.original_value,
        message.expected_target_options
      )
        .then(
          sendResponse
        )
        .catch(
          (error) => {
            sendResponse({
              ok: false,
              error:
                String(
                  error?.message
                  || error
                )
            });
          }
        );

      return true;
    }

    return false;
  }
);



configureSidePanel();
