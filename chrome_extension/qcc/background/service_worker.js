/*
 * QCC_SHARED_ACQUISITION_POLICY_WORKER_V1
 *
 * La política de adquisición se carga también en el runtime
 * que ejecutará Generic Harvest.
 *
 * No depende del Side Panel, CRM ni Bridge.
 */
importScripts(
  "../shared/browser_identity.js",
  "../shared/architecture_capture_policy.js",
  "../shared/acquisition_policy.js",
  "../shared/providers/mercurio_acquisition.js"
);


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



/*
 * ============================================================
 * QCC_AUTOMATIC_SITE_ARCHITECTURE_V1
 * ============================================================
 *
 * Captura automática PASIVA ante navegación/documento nuevo.
 *
 * Principios:
 * - Service Worker: funciona aunque Side Panel esté cerrado.
 * - no pide permisos automáticamente;
 * - no hace scroll;
 * - no pulsa;
 * - no cambia foco;
 * - no modifica DOM;
 * - captura automática requiere autorización
 *   explícita profile_key + origin;
 * - fallo de identidad/policy => no captura;
 * - documentId evita capturas duplicadas;
 * - backend conserva autoridad sobre fingerprint/estado;
 * - Bridge caído => fail-open silencioso.
 *
 * VIS-2A observa DOCUMENTOS.
 * Cambios DOM dentro del mismo documento pertenecen a VIS-2B.
 */

const QCC_AUTO_PROTOCOL_VERSION =
  1;

const QCC_AUTO_CAPTURE_DEBOUNCE_MS =
  1500;

const QCC_AUTO_CAPTURE_REQUEST_TIMEOUT_MS =
  20000;

const QCC_AUTO_CAPTURE_STORAGE_PREFIX =
  "qcc:auto-capture:last-document:";

const QCC_AUTO_SITE_ARCHITECTURE_CAPTURE_URL =
  (
    QCC_HUMAN_ACTION_BRIDGE_BASE_URL
    + "/qcc/site-architecture/capture"
  );

const QCC_AUTO_VISUAL_ARTIFACT_URL =
  (
    QCC_HUMAN_ACTION_BRIDGE_BASE_URL
    + "/qcc/site-architecture/visual-artifact"
  );

const QCC_AUTO_PAGE_ARTIFACT_URL =
  (
    QCC_HUMAN_ACTION_BRIDGE_BASE_URL
    + "/qcc/site-architecture/page-artifact"
  );


/*
 * ============================================================
 * QCC_SAME_DOCUMENT_MUTATION_CAPTURE_V1
 * ============================================================
 *
 * Cambios funcionales dentro del MISMO documentId.
 *
 * Browser:
 * - solo detecta DIRTY;
 * - nunca calcula fingerprint;
 * - nunca decide semántica de estado.
 *
 * Backend:
 * - adapta;
 * - normaliza;
 * - calcula fingerprint canónico.
 *
 * Solo persistimos si el fingerprint cambia.
 */

const QCC_AUTO_SITE_ARCHITECTURE_OBSERVE_URL =
  (
    QCC_HUMAN_ACTION_BRIDGE_BASE_URL
    + "/qcc/site-architecture/observe"
  );

const QCC_AUTO_MUTATION_DEBOUNCE_MS =
  1800;

const QCC_AUTO_MUTATION_FRAME_DEBOUNCE_MS =
  650;

const qccAutomaticMutationTimers =
  new Map();

const qccAutomaticMutationInFlight =
  new Set();


const qccAutomaticCaptureTimers =
  new Map();

const qccAutomaticCaptureInFlight =
  new Set();


function qccAutomaticCaptureStorageKey(
  tabId
) {
  return (
    QCC_AUTO_CAPTURE_STORAGE_PREFIX
    + String(
        tabId
      )
  );
}


function qccAutomaticCaptureEligibleUrl(
  value
) {
  try {
    const url =
      new URL(
        String(
          value
          || ""
        )
      );

    return (
      url.protocol === "http:"
      || url.protocol === "https:"
    );

  } catch (_) {
    return false;
  }
}



/*
 * QCC_ARCHITECTURE_AUTOMATIC_CAPTURE_GATE_V1
 *
 * Autoridad:
 *   browser_profile_key + tab.url
 *
 * Seguridad:
 * - antes de permisos;
 * - antes de leer DOM;
 * - antes de instalar MutationObserver;
 * - antes de viewport/MHTML;
 * - antes de Bridge;
 * - identidad/policy/storage inválidos => OFF.
 *
 * Force Capture manual NO usa este gate.
 */
async function qccAutomaticArchitectureCaptureDecision(
  tab
) {
  const identity =
    globalThis
      ?.QccBrowserIdentity;

  const policy =
    globalThis
      ?.QccArchitectureCapturePolicy;

  const url =
    String(
      tab?.url
      || ""
    );


  if (
    !identity
    || !policy
  ) {
    return {
      automatic_allowed:
        false,

      source:
        "POLICY_RUNTIME_UNAVAILABLE"
    };
  }


  let profileKey = null;

  try {
    profileKey =
      await identity.read();

  } catch (_) {
    return {
      automatic_allowed:
        false,

      source:
        "IDENTITY_STORAGE_ERROR"
    };
  }


  if (!profileKey) {
    return {
      automatic_allowed:
        false,

      source:
        "PROFILE_UNBOUND"
    };
  }


  try {
    const resolution =
      await policy.resolve(
        profileKey,
        url
      );

    if (
      !resolution
      || resolution
        .automatic_allowed
        !== true
    ) {
      return {
        ...(resolution || {}),

        browser_profile_key:
          profileKey,

        automatic_allowed:
          false,

        source:
          resolution?.source
          || "POLICY_DENIED"
      };
    }


    return {
      ...resolution,

      browser_profile_key:
        profileKey,

      automatic_allowed:
        true
    };

  } catch (_) {
    return {
      browser_profile_key:
        profileKey,

      automatic_allowed:
        false,

      source:
        "POLICY_RESOLUTION_ERROR"
    };
  }
}


async function qccAutomaticCapturePermissions() {
  /*
   * IMPORTANTE:
   * el automático jamás llama permissions.request().
   *
   * El usuario concede estos permisos desde el flujo
   * manual Arquitectura DOM.
   */
  const hostGranted =
    await chrome.permissions.contains({
      origins: [
        "<all_urls>"
      ]
    });

  const pageCaptureGranted =
    await chrome.permissions.contains({
      permissions: [
        "pageCapture"
      ]
    });

  return {
    host_granted:
      Boolean(
        hostGranted
      ),

    page_capture_granted:
      Boolean(
        pageCaptureGranted
      )
  };
}


async function inspectSpecificTabDom(
  tabId
) {
  const normalizedTabId =
    Number(
      tabId
    );

  if (
    !Number.isInteger(
      normalizedTabId
    )
  ) {
    throw new Error(
      "QCC_AUTO_CAPTURE_TAB_INVALID"
    );
  }


  const tab =
    await chrome.tabs.get(
      normalizedTabId
    );


  if (
    !tab
    || tab.id !== normalizedTabId
  ) {
    throw new Error(
      "QCC_AUTO_CAPTURE_TAB_NOT_FOUND"
    );
  }


  const injectionResults =
    await chrome.scripting.executeScript({
      target: {
        tabId:
          normalizedTabId,

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
      normalizedTabId,

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


function qccAutomaticMainDocumentId(
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

  return String(
    mainFrame?.document_id
    || ""
  ).trim();
}


async function qccAutomaticStoredCaptureState(
  tabId
) {
  const key =
    qccAutomaticCaptureStorageKey(
      tabId
    );

  const stored =
    await chrome.storage.session.get(
      key
    );

  const state =
    stored?.[key];

  if (
    !state
    || typeof state !== "object"
  ) {
    return null;
  }

  return state;
}


async function qccAutomaticAlreadyCaptured(
  tabId,
  documentId
) {
  if (!documentId) {
    return false;
  }

  const key =
    qccAutomaticCaptureStorageKey(
      tabId
    );

  const stored =
    await chrome.storage.session.get(
      key
    );

  return (
    String(
      stored?.[key]?.document_id
      || ""
    )
    === documentId
  );
}


async function qccRememberAutomaticCapture(
  tabId,
  documentId,
  url,
  captureId,
  fingerprint
) {
  if (!documentId) {
    return;
  }

  const key =
    qccAutomaticCaptureStorageKey(
      tabId
    );

  await chrome.storage.session.set({
    [key]: {
      document_id:
        documentId,

      url:
        String(
          url
          || ""
        ),

      capture_id:
        String(
          captureId
          || ""
        ),

      fingerprint:
        String(
          fingerprint
          || ""
        ),

      captured_at:
        new Date()
          .toISOString()
    }
  });
}


async function qccAutomaticFetchJson(
  url,
  options
) {
  const controller =
    new AbortController();

  const timeoutId =
    setTimeout(
      () => {
        controller.abort();
      },
      QCC_AUTO_CAPTURE_REQUEST_TIMEOUT_MS
    );


  try {
    const response =
      await fetch(
        url,
        {
          ...options,
          signal:
            controller.signal
        }
      );


    let payload = null;

    try {
      payload =
        await response.json();

    } catch (_) {
      payload = null;
    }


    if (
      !response.ok
      || !payload
      || payload.ok !== true
    ) {
      throw new Error(
        payload?.error
        || (
          "QCC_AUTO_CAPTURE_HTTP_"
          + String(
              response.status
            )
        )
      );
    }


    return payload;

  } finally {
    clearTimeout(
      timeoutId
    );
  }
}


async function qccSubmitAutomaticDomCapture(
  capture
) {
  const browserProfileKey =
    await globalThis
      .QccBrowserIdentity
      .read();

  return await qccAutomaticFetchJson(
    QCC_AUTO_SITE_ARCHITECTURE_CAPTURE_URL,
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
            QCC_AUTO_PROTOCOL_VERSION,

          browser_profile_key:
            browserProfileKey,

          capture:
            capture
        })
    }
  );
}


function qccAutomaticCanonicalFingerprint(
  payload
) {
  return String(
    payload
      ?.state_observation
      ?.fingerprint
    || payload?.fingerprint
    || ""
  ).trim();
}


async function qccSubmitAutomaticDomObservation(
  capture,
  baselineCaptureId
) {
  const browserProfileKey =
    await globalThis
      .QccBrowserIdentity
      .read();

  return await qccAutomaticFetchJson(
    QCC_AUTO_SITE_ARCHITECTURE_OBSERVE_URL,
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
            QCC_AUTO_PROTOCOL_VERSION,

          browser_profile_key:
            browserProfileKey,

          capture:
            capture,

          baseline_capture_id:
            String(
              baselineCaptureId
              || ""
            )
        })
    }
  );
}


async function qccCaptureAutomaticViewport(
  tab
) {
  if (
    !tab
    || !Number.isInteger(
        tab.id
      )
    || !Number.isInteger(
        tab.windowId
      )
    || tab.active !== true
  ) {
    return null;
  }


  /*
   * Evita capturar otra pestaña si el usuario
   * ha cambiado de tab durante el debounce.
   */
  const activeTabs =
    await chrome.tabs.query({
      active:
        true,

      windowId:
        tab.windowId
    });


  const activeTab =
    (
      activeTabs?.[0]
      || null
    );


  if (
    !activeTab
    || activeTab.id !== tab.id
  ) {
    return null;
  }


  const dataUrl =
    await chrome.tabs.captureVisibleTab(
      tab.windowId,
      {
        format:
          "png"
      }
    );


  if (
    typeof dataUrl !== "string"
    || !dataUrl.startsWith(
        "data:image/png"
      )
  ) {
    return null;
  }


  const response =
    await fetch(
      dataUrl
    );

  if (!response.ok) {
    return null;
  }


  const blob =
    await response.blob();


  if (
    !(blob instanceof Blob)
    || blob.size <= 0
  ) {
    return null;
  }


  return blob;
}


async function qccCaptureAutomaticMhtml(
  tabId
) {
  if (
    !chrome.pageCapture
    || typeof (
        chrome
        .pageCapture
        .saveAsMHTML
      ) !== "function"
  ) {
    return null;
  }


  const blob =
    await chrome.pageCapture.saveAsMHTML({
      tabId:
        tabId
    });


  if (
    !(blob instanceof Blob)
    || blob.size <= 0
  ) {
    return null;
  }


  return blob;
}


async function qccSubmitAutomaticVisualArtifact(
  captureId,
  blob
) {
  if (
    !captureId
    || !(blob instanceof Blob)
    || blob.size <= 0
  ) {
    return null;
  }


  return await qccAutomaticFetchJson(
    QCC_AUTO_VISUAL_ARTIFACT_URL,
    {
      method:
        "POST",

      headers: {
        "Content-Type":
          "image/png",

        "X-QCC-Protocol-Version":
          String(
            QCC_AUTO_PROTOCOL_VERSION
          ),

        "X-QCC-Capture-Id":
          String(
            captureId
          ),

        "X-QCC-Visual-Kind":
          "viewport"
      },

      body:
        blob
    }
  );
}


async function qccSubmitAutomaticPageArtifact(
  captureId,
  blob
) {
  if (
    !captureId
    || !(blob instanceof Blob)
    || blob.size <= 0
  ) {
    return null;
  }


  return await qccAutomaticFetchJson(
    QCC_AUTO_PAGE_ARTIFACT_URL,
    {
      method:
        "POST",

      headers: {
        "Content-Type":
          "multipart/related",

        "X-QCC-Protocol-Version":
          String(
            QCC_AUTO_PROTOCOL_VERSION
          ),

        "X-QCC-Capture-Id":
          String(
            captureId
          ),

        "X-QCC-Page-Kind":
          "mhtml"
      },

      body:
        blob
    }
  );
}


function installQccAutomaticMutationObserverFrame() {
  const marker =
    "__QCC_SITE_ARCHITECTURE_MUTATION_OBSERVER_V1__";

  if (
    globalThis[marker]
    && globalThis[marker].observer
  ) {
    return {
      ok:
        true,

      installed:
        false,

      reason:
        "ALREADY_INSTALLED"
    };
  }


  const relevantAttributes =
    new Set([
      "disabled",
      "hidden",
      "id",
      "name",
      "type",
      "role",
      "class",
      "style",
      "open",
      "inert",
      "href",
      "aria-selected",
      "aria-expanded",
      "aria-pressed",
      "aria-current",
      "aria-hidden"
    ]);


  let debounceTimer = null;


  const emitDirtySignal = () => {
    debounceTimer = null;

    try {
      const maybePromise =
        chrome.runtime.sendMessage({
          type:
            "QCC_SITE_ARCHITECTURE_DIRTY",

          schema_version:
            1,

          observed_at:
            new Date()
              .toISOString()
        });

      if (
        maybePromise
        && typeof maybePromise.catch
          === "function"
      ) {
        maybePromise.catch(
          () => {}
        );
      }

    } catch (_) {
      // Fail-open.
    }
  };


  const scheduleDirtySignal = () => {
    if (debounceTimer !== null) {
      clearTimeout(
        debounceTimer
      );
    }

    debounceTimer =
      setTimeout(
        emitDirtySignal,
        650
      );
  };


  const observer =
    new MutationObserver(
      (mutations) => {
        let relevant = false;

        for (const mutation of mutations) {
          if (
            mutation.type
            === "childList"
          ) {
            const addedElement =
              Array.from(
                mutation.addedNodes
                || []
              ).some(
                (node) =>
                  node?.nodeType === 1
              );

            const removedElement =
              Array.from(
                mutation.removedNodes
                || []
              ).some(
                (node) =>
                  node?.nodeType === 1
              );

            if (
              addedElement
              || removedElement
            ) {
              relevant = true;
              break;
            }
          }


          if (
            mutation.type
            === "attributes"
            && relevantAttributes.has(
                mutation.attributeName
              )
          ) {
            relevant = true;
            break;
          }
        }


        if (relevant) {
          scheduleDirtySignal();
        }
      }
    );


  const root =
    document.documentElement
    || document;


  observer.observe(
    root,
    {
      subtree:
        true,

      childList:
        true,

      attributes:
        true,

      attributeFilter:
        Array.from(
          relevantAttributes
        )
    }
  );


  globalThis[marker] = {
    observer:
      observer
  };


  return {
    ok:
      true,

    installed:
      true
  };
}


async function qccInstallAutomaticMutationObservers(
  tabId
) {
  const normalizedTabId =
    Number(
      tabId
    );

  if (
    !Number.isInteger(
      normalizedTabId
    )
  ) {
    return false;
  }


  await chrome.scripting.executeScript({
    target: {
      tabId:
        normalizedTabId,

      allFrames:
        true
    },

    world:
      "ISOLATED",

    func:
      installQccAutomaticMutationObserverFrame
  });


  return true;
}


function scheduleAutomaticSameDocumentObservation(
  tabId,
  trigger
) {
  const normalizedTabId =
    Number(
      tabId
    );

  if (
    !Number.isInteger(
      normalizedTabId
    )
  ) {
    return;
  }


  const previousTimer =
    qccAutomaticMutationTimers.get(
      normalizedTabId
    );


  if (previousTimer) {
    clearTimeout(
      previousTimer
    );
  }


  const timer =
    setTimeout(
      () => {
        qccAutomaticMutationTimers.delete(
          normalizedTabId
        );

        runAutomaticSameDocumentObservation(
          normalizedTabId,
          trigger
        ).catch(
          () => {}
        );
      },
      QCC_AUTO_MUTATION_DEBOUNCE_MS
    );


  qccAutomaticMutationTimers.set(
    normalizedTabId,
    timer
  );
}


async function runAutomaticSameDocumentObservation(
  tabId,
  trigger
) {
  const normalizedTabId =
    Number(
      tabId
    );


  if (
    !Number.isInteger(
      normalizedTabId
    )
  ) {
    return {
      ok:
        true,

      captured:
        false,

      reason:
        "TAB_INVALID"
    };
  }


  /*
   * Si VIS-2A está persistiendo la misma pestaña,
   * no perdemos la señal: la reintentamos.
   */
  if (
    qccAutomaticCaptureInFlight.has(
      normalizedTabId
    )
    || qccAutomaticMutationInFlight.has(
      normalizedTabId
    )
  ) {
    scheduleAutomaticSameDocumentObservation(
      normalizedTabId,
      "MUTATION_RETRY_AFTER_IN_FLIGHT"
    );

    return {
      ok:
        true,

      captured:
        false,

      reason:
        "CAPTURE_IN_FLIGHT"
    };
  }


  qccAutomaticMutationInFlight.add(
    normalizedTabId
  );


  try {
    const tab =
      await chrome.tabs.get(
        normalizedTabId
      );


    if (
      !tab
      || tab.status !== "complete"
      || !qccAutomaticCaptureEligibleUrl(
          tab.url
        )
    ) {
      return {
        ok:
          true,

        captured:
          false,

        reason:
          "TAB_NOT_ELIGIBLE"
      };
    }


    /*
     * ARCH-1C:
     * ninguna adquisición automática ocurre
     * sin autorización profile_key + origin.
     */
    const architectureCaptureDecision =
      await qccAutomaticArchitectureCaptureDecision(
        tab
      );


    if (
      architectureCaptureDecision
        ?.automatic_allowed
        !== true
    ) {
      return {
        ok:
          true,

        captured:
          false,

        reason:
          "ARCHITECTURE_CAPTURE_NOT_AUTHORIZED",

        policy_source:
          architectureCaptureDecision
            ?.source
          || "POLICY_DENIED"
      };
    }


    const permissions =
      await qccAutomaticCapturePermissions();


    if (
      permissions.host_granted
      !== true
    ) {
      return {
        ok:
          true,

        captured:
          false,

        reason:
          "HOST_PERMISSION_NOT_GRANTED"
      };
    }


    const stored =
      await qccAutomaticStoredCaptureState(
        normalizedTabId
      );


    if (!stored) {
      scheduleAutomaticSiteArchitectureCapture(
        normalizedTabId,
        "MUTATION_BASELINE_MISSING"
      );

      return {
        ok:
          true,

        captured:
          false,

        reseed_scheduled:
          true,

        reason:
          "BASELINE_RESEED_SCHEDULED"
      };
    }


    const capture =
      await inspectSpecificTabDom(
        normalizedTabId
      );


    const documentId =
      qccAutomaticMainDocumentId(
        capture
      );


    const baselineDocumentId =
      String(
        stored?.document_id
        || ""
      ).trim();


    /*
     * VIS-2B solo compara estados del MISMO documento.
     * Documento nuevo pertenece a VIS-2A.
     */
    if (
      !documentId
      || !baselineDocumentId
      || documentId
        !== baselineDocumentId
    ) {
      scheduleAutomaticSiteArchitectureCapture(
        normalizedTabId,
        "MUTATION_BASELINE_MISMATCH"
      );

      return {
        ok:
          true,

        captured:
          false,

        reseed_scheduled:
          true,

        reason:
          "DOCUMENT_BASELINE_RESEED_SCHEDULED"
      };
    }


    /*
     * Candidato completamente in-memory.
     * /observe NO crea capture_id ni archivos.
     */
    const baselineCaptureId =
      String(
        stored?.capture_id
        || ""
      ).trim();


    if (!baselineCaptureId) {
      return {
        ok:
          true,

        captured:
          false,

        reason:
          "BASELINE_CAPTURE_ID_MISSING"
      };
    }


    const observed =
      await qccSubmitAutomaticDomObservation(
        capture,
        baselineCaptureId
      );


    const candidateFingerprint =
      qccAutomaticCanonicalFingerprint(
        observed
      );


    if (!candidateFingerprint) {
      throw new Error(
        "QCC_AUTO_OBSERVE_FINGERPRINT_MISSING"
      );
    }


    const backendChanged =
      observed?.changed;


    /*
     * BACKEND = autoridad de dedupe.
     *
     * El navegador NO compara fingerprints
     * almacenados localmente para decidir persistencia.
     */
    if (
      backendChanged === false
    ) {
      console.debug(
        "[QCC] Same-document state unchanged:",
        {
          tab_id:
            normalizedTabId,

          document_id:
            documentId,

          fingerprint:
            candidateFingerprint,

          trigger:
            String(
              trigger
              || ""
            )
        }
      );

      return {
        ok:
          true,

        captured:
          false,

        changed:
          false,

        reason:
          "FUNCTIONAL_STATE_UNCHANGED",

        fingerprint:
          candidateFingerprint
      };
    }


    if (
      backendChanged !== true
    ) {
      throw new Error(
        "QCC_AUTO_OBSERVE_CHANGE_DECISION_MISSING"
      );
    }


    /*
     * Solo ahora pagamos el coste de evidencia visual.
     */
    let viewportBlob = null;
    let mhtmlBlob = null;


    try {
      viewportBlob =
        await qccCaptureAutomaticViewport(
          tab
        );

    } catch (error) {
      console.debug(
        "[QCC] Mutation viewport skipped:",
        String(
          error?.message
          || error
        )
      );
    }


    if (
      permissions.page_capture_granted
      === true
    ) {
      try {
        mhtmlBlob =
          await qccCaptureAutomaticMhtml(
            normalizedTabId
          );

      } catch (error) {
        console.debug(
          "[QCC] Mutation MHTML skipped:",
          String(
            error?.message
            || error
          )
        );
      }
    }


    /*
     * Persistimos EXACTAMENTE el DOM candidato que
     * produjo candidateFingerprint.
     *
     * El backend recalcula de nuevo su fingerprint;
     * el browser nunca lo aporta como autoridad.
     */
    const backendResult =
      await qccSubmitAutomaticDomCapture(
        capture
      );


    const captureId =
      String(
        backendResult?.capture_id
        || ""
      ).trim();


    if (!captureId) {
      throw new Error(
        "QCC_AUTO_CAPTURE_ID_MISSING"
      );
    }


    const persistedFingerprint =
      (
        qccAutomaticCanonicalFingerprint(
          backendResult
        )
        || candidateFingerprint
      );


    if (viewportBlob) {
      try {
        await qccSubmitAutomaticVisualArtifact(
          captureId,
          viewportBlob
        );

      } catch (error) {
        console.debug(
          "[QCC] Mutation viewport attach skipped:",
          String(
            error?.message
            || error
          )
        );
      }
    }


    if (mhtmlBlob) {
      try {
        await qccSubmitAutomaticPageArtifact(
          captureId,
          mhtmlBlob
        );

      } catch (error) {
        console.debug(
          "[QCC] Mutation MHTML attach skipped:",
          String(
            error?.message
            || error
          )
        );
      }
    }


    await qccRememberAutomaticCapture(
      normalizedTabId,
      documentId,
      capture.main_url,
      captureId,
      persistedFingerprint
    );


    console.log(
      "[QCC] Same-document functional state captured:",
      {
        capture_id:
          captureId,

        tab_id:
          normalizedTabId,

        document_id:
          documentId,

        fingerprint:
          persistedFingerprint,

        trigger:
          String(
            trigger
            || ""
          ),

        viewport:
          Boolean(
            viewportBlob
          ),

        mhtml:
          Boolean(
            mhtmlBlob
          )
      }
    );


    return {
      ok:
        true,

      captured:
        true,

      changed:
        true,

      capture_id:
        captureId,

      document_id:
        documentId,

      fingerprint:
        persistedFingerprint
    };


  } catch (error) {
    console.debug(
      "[QCC] Same-document observation skipped:",
      String(
        error?.message
        || error
      )
    );

    return {
      ok:
        true,

      captured:
        false,

      reason:
        String(
          error?.message
          || error
        )
    };

  } finally {
    qccAutomaticMutationInFlight.delete(
      normalizedTabId
    );
  }
}


async function runAutomaticSiteArchitectureCapture(
  tabId,
  trigger
) {
  const normalizedTabId =
    Number(
      tabId
    );


  if (
    !Number.isInteger(
      normalizedTabId
    )
  ) {
    return {
      ok:
        true,

      captured:
        false,

      reason:
        "TAB_INVALID"
    };
  }


  if (
    qccAutomaticCaptureInFlight.has(
      normalizedTabId
    )
  ) {
    return {
      ok:
        true,

      captured:
        false,

      reason:
        "CAPTURE_IN_FLIGHT"
    };
  }


  qccAutomaticCaptureInFlight.add(
    normalizedTabId
  );


  try {
    const tab =
      await chrome.tabs.get(
        normalizedTabId
      );


    if (
      !tab
      || tab.status !== "complete"
      || !qccAutomaticCaptureEligibleUrl(
          tab.url
        )
    ) {
      return {
        ok:
          true,

        captured:
          false,

        reason:
          "TAB_NOT_ELIGIBLE"
      };
    }


    /*
     * ARCH-1C:
     * ninguna adquisición automática ocurre
     * sin autorización profile_key + origin.
     */
    const architectureCaptureDecision =
      await qccAutomaticArchitectureCaptureDecision(
        tab
      );


    if (
      architectureCaptureDecision
        ?.automatic_allowed
        !== true
    ) {
      return {
        ok:
          true,

        captured:
          false,

        reason:
          "ARCHITECTURE_CAPTURE_NOT_AUTHORIZED",

        policy_source:
          architectureCaptureDecision
            ?.source
          || "POLICY_DENIED"
      };
    }


    const permissions =
      await qccAutomaticCapturePermissions();


    /*
     * Sin host grant no podemos leer el DOM.
     * No solicitamos permisos aquí.
     */
    if (
      permissions.host_granted
      !== true
    ) {
      return {
        ok:
          true,

        captured:
          false,

        reason:
          "HOST_PERMISSION_NOT_GRANTED"
      };
    }


    /*
     * Debounce temporal terminado:
     * capturamos contra el tab exacto que originó
     * el evento, nunca contra "el activo ahora"
     * de otra ventana.
     */
    const capture =
      await inspectSpecificTabDom(
        normalizedTabId
      );


    const documentId =
      qccAutomaticMainDocumentId(
        capture
      );


    /*
     * Instala observación del documento incluso
     * cuando VIS-2A vaya a deduplicarlo.
     *
     * Así onActivated puede rearmar el observer
     * después de una recarga de la extensión.
     */
    try {
      await qccInstallAutomaticMutationObservers(
        normalizedTabId
      );

    } catch (error) {
      console.debug(
        "[QCC] Auto mutation observer install skipped:",
        String(
          error?.message
          || error
        )
      );
    }


    if (
      documentId
      && await qccAutomaticAlreadyCaptured(
        normalizedTabId,
        documentId
      )
    ) {
      return {
        ok:
          true,

        captured:
          false,

        reason:
          "DOCUMENT_ALREADY_CAPTURED"
      };
    }


    /*
     * Evidencia visual inmediatamente después
     * de DOM/Geometry y ANTES del Bridge.
     *
     * Cada artefacto es fail-open independiente.
     */
    let viewportBlob = null;
    let mhtmlBlob = null;


    try {
      viewportBlob =
        await qccCaptureAutomaticViewport(
          tab
        );

    } catch (error) {
      console.debug(
        "[QCC] Auto viewport skipped:",
        String(
          error?.message
          || error
        )
      );
    }


    if (
      permissions.page_capture_granted
      === true
    ) {
      try {
        mhtmlBlob =
          await qccCaptureAutomaticMhtml(
            normalizedTabId
          );

      } catch (error) {
        console.debug(
          "[QCC] Auto MHTML skipped:",
          String(
            error?.message
            || error
          )
        );
      }
    }


    /*
     * Backend = autoridad del capture_id,
     * fingerprint y estado funcional.
     */
    const backendResult =
      await qccSubmitAutomaticDomCapture(
        capture
      );


    const captureId =
      String(
        backendResult?.capture_id
        || ""
      ).trim();


    if (!captureId) {
      throw new Error(
        "QCC_AUTO_CAPTURE_ID_MISSING"
      );
    }


    const fingerprint =
      qccAutomaticCanonicalFingerprint(
        backendResult
      );


    /*
     * Adjuntos independientes.
     * Su fallo no invalida DOM/State.
     */
    if (viewportBlob) {
      try {
        await qccSubmitAutomaticVisualArtifact(
          captureId,
          viewportBlob
        );

      } catch (error) {
        console.debug(
          "[QCC] Auto viewport attach skipped:",
          String(
            error?.message
            || error
          )
        );
      }
    }


    if (mhtmlBlob) {
      try {
        await qccSubmitAutomaticPageArtifact(
          captureId,
          mhtmlBlob
        );

      } catch (error) {
        console.debug(
          "[QCC] Auto MHTML attach skipped:",
          String(
            error?.message
            || error
          )
        );
      }
    }


    /*
     * Solo deduplicamos tras persistencia backend
     * satisfactoria.
     *
     * Si Bridge estaba caído, el documento podrá
     * reintentarse en un evento posterior.
     */
    await qccRememberAutomaticCapture(
      normalizedTabId,
      documentId,
      capture.main_url,
      captureId,
      fingerprint
    );


    console.log(
      "[QCC] Automatic Site Architecture:",
      {
        capture_id:
          captureId,

        tab_id:
          normalizedTabId,

        document_id:
          documentId,

        trigger:
          String(
            trigger
            || ""
          ),

        viewport:
          Boolean(
            viewportBlob
          ),

        mhtml:
          Boolean(
            mhtmlBlob
          )
      }
    );


    return {
      ok:
        true,

      captured:
        true,

      capture_id:
        captureId,

      document_id:
        documentId
    };


  } catch (error) {
    /*
     * Fail-open absoluto.
     *
     * Nunca impedimos la navegación del usuario
     * porque Bridge/QCC/captura fallen.
     */
    console.debug(
      "[QCC] Automatic Site Architecture skipped:",
      String(
        error?.message
        || error
      )
    );

    return {
      ok:
        true,

      captured:
        false,

      reason:
        String(
          error?.message
          || error
        )
    };

  } finally {
    qccAutomaticCaptureInFlight.delete(
      normalizedTabId
    );
  }
}


function scheduleAutomaticSiteArchitectureCapture(
  tabId,
  trigger
) {
  const normalizedTabId =
    Number(
      tabId
    );


  if (
    !Number.isInteger(
      normalizedTabId
    )
  ) {
    return;
  }


  const previousTimer =
    qccAutomaticCaptureTimers.get(
      normalizedTabId
    );


  if (previousTimer) {
    clearTimeout(
      previousTimer
    );
  }


  const timer =
    setTimeout(
      () => {
        qccAutomaticCaptureTimers.delete(
          normalizedTabId
        );

        runAutomaticSiteArchitectureCapture(
          normalizedTabId,
          trigger
        ).catch(
          () => {}
        );
      },
      QCC_AUTO_CAPTURE_DEBOUNCE_MS
    );


  qccAutomaticCaptureTimers.set(
    normalizedTabId,
    timer
  );
}


/*
 * Navegación/documento completado.
 */
chrome.tabs.onUpdated.addListener(
  (
    tabId,
    changeInfo,
    tab
  ) => {
    if (
      changeInfo?.status !== "complete"
    ) {
      return;
    }


    scheduleAutomaticSiteArchitectureCapture(
      tabId,
      "TAB_UPDATED_COMPLETE"
    );
  }
);


/*
 * Cambio manual de pestaña.
 *
 * El documentId dedupe evita recapturar una
 * pantalla ya registrada.
 */
chrome.tabs.onActivated.addListener(
  (activeInfo) => {
    scheduleAutomaticSiteArchitectureCapture(
      activeInfo?.tabId,
      "TAB_ACTIVATED"
    );
  }
);


/*
 * QCC_SITE_ARCHITECTURE_DIRTY
 *
 * Señal mínima desde MutationObserver.
 *
 * No aceptamos:
 * - DOM;
 * - fingerprint;
 * - policy;
 * - site;
 * - environment;
 * - capture_id.
 *
 * sender.tab es la identidad Chrome efectiva.
 */
chrome.runtime.onMessage.addListener(
  (
    message,
    sender,
    sendResponse
  ) => {
    if (
      message?.type
        !== "QCC_SITE_ARCHITECTURE_DIRTY"
    ) {
      return false;
    }


    const tabId =
      Number(
        sender?.tab?.id
      );


    if (
      sender?.id !== chrome.runtime.id
      || !Number.isInteger(
          tabId
        )
    ) {
      sendResponse({
        ok:
          true,

        scheduled:
          false,

        reason:
          "DIRTY_SENDER_INVALID"
      });

      return false;
    }


    scheduleAutomaticSameDocumentObservation(
      tabId,
      "DOM_MUTATION_DIRTY"
    );


    sendResponse({
      ok:
        true,

      scheduled:
        true
    });


    return false;
  }
);


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



/*
 * ============================================================
 * QCC_GENERIC_DOM_HARVEST_V1
 * ============================================================
 *
 * Extracción genérica y PASIVA del DOM ya cargado.
 *
 * Garantías:
 * - requiere HARVEST_ALLOWED;
 * - la autoridad se comprueba en Service Worker;
 * - no hace scroll;
 * - no hace click;
 * - no navega;
 * - no muta el DOM;
 * - no requiere Bridge ni CRM.
 */


async function qccGenericHarvestActiveTab() {
  const tabs =
    await chrome.tabs.query({
      active:
        true,

      lastFocusedWindow:
        true
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
    || !tab.url
  ) {
    throw new Error(
      "QCC_GENERIC_DOM_HARVEST_ACTIVE_TAB_NOT_FOUND"
    );
  }

  return tab;
}


async function resolveGenericHarvestActivePolicy() {
  const tab =
    await qccGenericHarvestActiveTab();

  const policyApi =
    globalThis.QccAcquisitionPolicy;

  if (
    !policyApi
    || typeof policyApi.resolve
      !== "function"
  ) {
    throw new Error(
      "QCC_ACQUISITION_POLICY_NOT_AVAILABLE"
    );
  }

  const policy =
    await policyApi.resolve(
      tab.url
    );

  return {
    tab:
      tab,

    policy:
      policy
  };
}


function qccGenericHarvestText(
  value
) {
  return String(
    value
    || ""
  )
    .replace(
      /\s+/g,
      " "
    )
    .trim();
}


function qccGenericHarvestBoolean(
  ...values
) {
  for (const value of values) {
    if (value === true) {
      return true;
    }

    if (value === false) {
      return false;
    }
  }

  return null;
}


function qccGenericHarvestRect(
  item
) {
  const rect =
    (
      item
        ?.interaction
        ?.rect
      || item
        ?.geometry
        ?.rect
      || item
        ?.rect
      || null
    );

  if (
    !rect
    || typeof rect !== "object"
  ) {
    return null;
  }

  return {
    x:
      Number(
        rect.x
        || 0
      ),

    y:
      Number(
        rect.y
        || 0
      ),

    top:
      Number(
        rect.top
        || 0
      ),

    left:
      Number(
        rect.left
        || 0
      ),

    right:
      Number(
        rect.right
        || 0
      ),

    bottom:
      Number(
        rect.bottom
        || 0
      ),

    width:
      Number(
        rect.width
        || 0
      ),

    height:
      Number(
        rect.height
        || 0
      )
  };
}


function qccGenericHarvestFramePath(
  frame
) {
  const explicit =
    qccGenericHarvestText(
      frame?.frame_path
      || frame
        ?.result
        ?.frame_path
      || ""
    );

  if (explicit) {
    return explicit;
  }

  if (
    Number.isInteger(
      frame?.frame_id
    )
  ) {
    return (
      "frame:"
      + String(
          frame.frame_id
        )
    );
  }

  return "frame:unknown";
}


function qccGenericHarvestItem(
  item,
  frame,
  index
) {
  const element =
    (
      item?.element
      && typeof item.element
        === "object"
      ? item.element
      : {}
    );

  const semantics =
    (
      item?.semantics
      && typeof item.semantics
        === "object"
      ? item.semantics
      : {}
    );

  const interaction =
    (
      item?.interaction
      && typeof item.interaction
        === "object"
      ? item.interaction
      : {}
    );

  const attributes =
    (
      item?.attributes
      && typeof item.attributes
        === "object"
      ? item.attributes
      : {}
    );

  const framePath =
    qccGenericHarvestFramePath(
      frame
    );

  const selector =
    qccGenericHarvestText(
      item?.selector
      || element?.selector
      || ""
    );

  const tag =
    qccGenericHarvestText(
      item?.tag
      || item?.tag_name
      || element?.tag
      || element?.tag_name
      || ""
    ).toLowerCase();

  const id =
    qccGenericHarvestText(
      item?.id
      || element?.id
      || attributes?.id
      || ""
    );

  const name =
    qccGenericHarvestText(
      item?.name
      || element?.name
      || attributes?.name
      || ""
    );

  const type =
    qccGenericHarvestText(
      item?.type
      || element?.type
      || attributes?.type
      || ""
    );

  const role =
    qccGenericHarvestText(
      item?.role
      || element?.role
      || semantics?.role
      || attributes?.role
      || ""
    );

  const text =
    qccGenericHarvestText(
      item?.text
      || item?.text_content
      || element?.text
      || semantics?.text
      || ""
    );

  const accessibleName =
    qccGenericHarvestText(
      item?.accessible_name
      || element?.accessible_name
      || semantics?.accessible_name
      || item?.aria_label
      || attributes?.["aria-label"]
      || ""
    );

  const href =
    qccGenericHarvestText(
      item?.href
      || element?.href
      || attributes?.href
      || ""
    );

  const visible =
    qccGenericHarvestBoolean(
      interaction?.visible,
      item?.visible
    );

  const disabled =
    qccGenericHarvestBoolean(
      interaction?.disabled,
      item?.disabled,
      element?.disabled
    );

  const inViewport =
    qccGenericHarvestBoolean(
      interaction?.in_viewport,
      item?.in_viewport
    );

  return {
    frame_path:
      framePath,

    frame_id:
      (
        Number.isInteger(
          frame?.frame_id
        )
        ? frame.frame_id
        : null
      ),

    source_index:
      index,

    selector:
      selector,

    tag:
      tag,

    id:
      id,

    name:
      name,

    type:
      type,

    role:
      role,

    text:
      text,

    accessible_name:
      accessibleName,

    href:
      href,

    visible:
      visible,

    in_viewport:
      inViewport,

    disabled:
      disabled,

    geometry:
      qccGenericHarvestRect(
        item
      )
  };
}


function qccGenericHarvestIdentity(
  item
) {
  /*
   * Selector + frame es la identidad preferida.
   *
   * Si no existe selector NO colapsamos elementos
   * potencialmente distintos solo porque compartan texto.
   */
  if (item.selector) {
    return (
      item.frame_path
      + "::selector::"
      + item.selector
    );
  }

  return (
    item.frame_path
    + "::source-index::"
    + String(
        item.source_index
      )
  );
}



const QCC_GENERIC_HARVEST_EXCLUDED_TAGS =
  new Set([
    "html",
    "head",
    "body",
    "script",
    "style",
    "meta",
    "link",
    "noscript",
    "template"
  ]);


function qccGenericHarvestRelevantItem(
  item
) {
  const tag =
    String(
      item?.tag
      || ""
    )
      .trim()
      .toLowerCase();


  /*
   * Infraestructura documental.
   *
   * Su contenido ya queda representado por
   * elementos descendientes más concretos y
   * solo añade ruido masivo al dataset.
   */
  if (
    QCC_GENERIC_HARVEST_EXCLUDED_TAGS.has(
      tag
    )
  ) {
    return false;
  }


  /*
   * Conservamos elementos visibles.
   */
  if (item?.visible === true) {
    return true;
  }


  /*
   * Conservamos también elementos no visibles
   * cuando poseen identidad o semántica útil.
   *
   * Esto evita perder controles, enlaces,
   * estructuras accesibles o elementos que
   * podrán aparecer durante Dynamic Harvest.
   */
  return Boolean(
    item?.selector
    || item?.id
    || item?.name
    || item?.type
    || item?.role
    || item?.href
    || item?.accessible_name
    || item?.text
  );
}


function buildGenericDomHarvestDataset(
  capture,
  policy
) {
  const frames =
    (
      Array.isArray(
        capture?.frames
      )
      ? capture.frames
      : []
    );

  const deduplicated =
    new Map();

  let rawItemCount =
    0;

  let acceptedItemCount =
    0;

  let filteredOutCount =
    0;

  frames.forEach(
    (frame) => {
      const inventory =
        (
          Array.isArray(
            frame
              ?.result
              ?.elements
          )
          ? frame.result.elements
          : []
        );

      inventory.forEach(
        (
          item,
          index
        ) => {
          rawItemCount += 1;

          const normalized =
            qccGenericHarvestItem(
              item,
              frame,
              index
            );

          if (
            !qccGenericHarvestRelevantItem(
              normalized
            )
          ) {
            filteredOutCount +=
              1;

            return;
          }

          acceptedItemCount +=
            1;

          const identity =
            qccGenericHarvestIdentity(
              normalized
            );

          if (
            !deduplicated.has(
              identity
            )
          ) {
            deduplicated.set(
              identity,
              normalized
            );
          }
        }
      );
    }
  );

  const items =
    Array.from(
      deduplicated.values()
    );


  const mainFrame =
    (
      frames.find(
        (frame) =>
          frame?.frame_id === 0
      )
      || frames[0]
      || null
    );


  const documentId =
    String(
      mainFrame?.document_id
      || ""
    );


  const mainUrl =
    String(
      capture?.main_url
      || ""
    );

  let origin = "";
  let pathname = "";

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
    origin = "";
    pathname = "";
  }

  return {
    schema_version:
      1,

    artifact_type:
      "QCC_GENERIC_DOM_HARVEST",

    acquisition_mode:
      String(
        policy?.mode
        || ""
      ),

    source:
      String(
        policy?.source
        || ""
      ),

    harvested_at:
      new Date().toISOString(),

    origin:
      origin,

    pathname:
      pathname,

    url:
      mainUrl,

    tab_id:
      (
        Number.isInteger(
          capture?.tab_id
        )
        ? capture.tab_id
        : null
      ),

    document_id:
      documentId,

    captured_frames:
      Number(
        capture?.captured_frames
        || frames.length
        || 0
      ),

    raw_item_count:
      rawItemCount,

    filtered_out_count:
      filteredOutCount,

    item_count:
      acceptedItemCount,

    deduplicated_count:
      items.length,

    duplicates_removed:
      Math.max(
        0,
        acceptedItemCount
          - items.length
      ),

    items:
      items
  };
}


async function runGenericDomHarvest() {
  const initial =
    await resolveGenericHarvestActivePolicy();

  if (
    initial.policy?.mode
      !== globalThis
        .QccAcquisitionPolicy
        .HARVEST_ALLOWED
    || initial.policy?.allowed
      !== true
  ) {
    throw new Error(
      "QCC_GENERIC_DOM_HARVEST_NOT_ALLOWED"
    );
  }


  /*
   * Solo después del gate de adquisición
   * inspeccionamos el DOM.
   */
  const capture =
    await inspectActiveTabDom();

  if (
    !capture
    || capture.ok !== true
  ) {
    throw new Error(
      capture?.error
      || "QCC_GENERIC_DOM_HARVEST_CAPTURE_INVALID"
    );
  }


  if (
    Number.isInteger(
      capture.tab_id
    )
    && capture.tab_id
      !== initial.tab.id
  ) {
    throw new Error(
      "QCC_GENERIC_DOM_HARVEST_TAB_CHANGED"
    );
  }


  /*
   * Segunda comprobación después de la captura:
   * si el usuario revocó Harvest mientras leíamos,
   * no entregamos dataset.
   */
  const finalPolicy =
    await globalThis
      .QccAcquisitionPolicy
      .resolve(
        initial.tab.url
      );

  if (
    finalPolicy?.mode
      !== globalThis
        .QccAcquisitionPolicy
        .HARVEST_ALLOWED
    || finalPolicy?.allowed
      !== true
  ) {
    throw new Error(
      "QCC_GENERIC_DOM_HARVEST_PERMISSION_REVOKED"
    );
  }


  const dataset =
    buildGenericDomHarvestDataset(
      capture,
      finalPolicy
    );

  return {
    ok:
      true,

    dataset:
      dataset
  };
}



function qccGenericHarvestWorkerDeadline(
  operation,
  timeoutMs,
  errorCode
) {
  return new Promise(
    (
      resolve,
      reject
    ) => {
      let settled =
        false;

      const timer =
        setTimeout(
          () => {
            if (settled) {
              return;
            }

            settled =
              true;

            reject(
              new Error(
                errorCode
              )
            );
          },
          Math.max(
            250,
            Number(
              timeoutMs
              || 3000
            )
          )
        );


      Promise.resolve(
        operation
      )
        .then(
          (value) => {
            if (settled) {
              return;
            }

            settled =
              true;

            clearTimeout(
              timer
            );

            resolve(
              value
            );
          }
        )
        .catch(
          (error) => {
            if (settled) {
              return;
            }

            settled =
              true;

            clearTimeout(
              timer
            );

            reject(
              error
            );
          }
        );
    }
  );
}


async function setGenericHarvestForActiveTab(
  enabled
) {
  /*
   * Este camino tiene deadlines propios.
   *
   * Así un fallo del browser/storage nunca deja
   * el botón esperando indefinidamente y podemos
   * identificar la fase exacta.
   */
  const tab =
    await qccGenericHarvestWorkerDeadline(
      qccGenericHarvestActiveTab(),
      3000,
      "QCC_GENERIC_HARVEST_ACTIVE_TAB_TIMEOUT"
    );


  const policy =
    globalThis.QccAcquisitionPolicy;

  if (!policy) {
    throw new Error(
      "QCC_ACQUISITION_POLICY_NOT_AVAILABLE"
    );
  }


  /*
   * Primero comprobamos que resolve() responde.
   * No confiamos únicamente en enable/disable.
   */
  const before =
    await qccGenericHarvestWorkerDeadline(
      policy.resolve(
        tab.url
      ),
      3000,
      "QCC_GENERIC_HARVEST_POLICY_RESOLVE_TIMEOUT"
    );


  console.debug(
    "[QCC] Generic Harvest policy before:",
    {
      enabled:
        enabled === true,

      tab_id:
        tab.id,

      url:
        tab.url,

      policy:
        before
    }
  );


  if (enabled === true) {
    const result =
      await qccGenericHarvestWorkerDeadline(
        policy.enableHarvestForUrl(
          tab.url
        ),
        3000,
        "QCC_GENERIC_HARVEST_POLICY_ENABLE_TIMEOUT"
      );

    console.debug(
      "[QCC] Generic Harvest enable result:",
      result
    );

    return result;
  }


  const result =
    await qccGenericHarvestWorkerDeadline(
      policy.disableHarvestForUrl(
        tab.url
      ),
      3000,
      "QCC_GENERIC_HARVEST_POLICY_DISABLE_TIMEOUT"
    );

  console.debug(
    "[QCC] Generic Harvest disable result:",
    result
  );

  return result;
}


chrome.runtime.onMessage.addListener(
  (
    message,
    _sender,
    sendResponse
  ) => {
    const type =
      String(
        message?.type
        || ""
      );

    if (
      type
        !== "QCC_GENERIC_HARVEST_POLICY"
      && type
        !== "QCC_GENERIC_HARVEST_ENABLE"
      && type
        !== "QCC_GENERIC_HARVEST_DISABLE"
      && type
        !== "QCC_GENERIC_DOM_HARVEST"
    ) {
      return false;
    }


    let operation;

    if (
      type
        === "QCC_GENERIC_HARVEST_POLICY"
    ) {
      operation =
        resolveGenericHarvestActivePolicy()
          .then(
            (result) => ({
              ok:
                true,

              policy:
                result.policy,

              tab_id:
                result.tab.id,

              url:
                result.tab.url
            })
          );

    } else if (
      type
        === "QCC_GENERIC_HARVEST_ENABLE"
    ) {
      operation =
        setGenericHarvestForActiveTab(
          true
        );

    } else if (
      type
        === "QCC_GENERIC_HARVEST_DISABLE"
    ) {
      operation =
        setGenericHarvestForActiveTab(
          false
        );

    } else {
      operation =
        runGenericDomHarvest();
    }


    operation
      .then(
        sendResponse
      )
      .catch(
        (error) => {
          console.warn(
            "[QCC] Generic DOM Harvest:",
            error
          );

          sendResponse({
            ok:
              false,

            error:
              String(
                error?.message
                || error
                || "QCC_GENERIC_DOM_HARVEST_FAILED"
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



/*
 * ============================================================
 * QCC_GENERIC_DYNAMIC_HARVEST_V1
 * ============================================================
 *
 * Harvest incremental gobernado.
 *
 * Garantías:
 * - HARVEST_ALLOWED obligatorio;
 * - Service Worker es autoridad;
 * - solo scroll vertical de la página principal;
 * - sin clicks;
 * - sin navegación;
 * - sin apertura de pestañas;
 * - máximo acotado de pasos;
 * - revalidación de tab/origin/policy;
 * - document_id debe permanecer exacto;
 * - parada por estancamiento;
 * - restauración best-effort del scroll inicial.
 */


const QCC_GENERIC_DYNAMIC_MAX_STEPS =
  12;

const QCC_GENERIC_DYNAMIC_SCROLL_FRACTION =
  0.75;

const QCC_GENERIC_DYNAMIC_WAIT_MS =
  1500;

const QCC_GENERIC_DYNAMIC_STAGNATION_LIMIT =
  2;

const QCC_GENERIC_DYNAMIC_RESTORE_WAIT_MS =
  120;


function qccGenericDynamicOrigin(
  value
) {
  try {
    return new URL(
      String(
        value
        || ""
      )
    ).origin;

  } catch (_) {
    return "";
  }
}


function qccGenericDynamicCaptureContext(
  capture
) {
  const frames =
    (
      Array.isArray(
        capture?.frames
      )
      ? capture.frames
      : []
    );

  const mainFrame =
    (
      frames.find(
        (frame) =>
          frame?.frame_id === 0
      )
      || frames[0]
      || null
    );

  const url =
    String(
      capture?.main_url
      || ""
    );

  return {
    tab_id:
      (
        Number.isInteger(
          capture?.tab_id
        )
        ? capture.tab_id
        : null
      ),

    document_id:
      String(
        mainFrame?.document_id
        || ""
      ),

    url:
      url,

    origin:
      qccGenericDynamicOrigin(
        url
      )
  };
}


function qccGenericDynamicVerifyCapture(
  capture,
  expected
) {
  const context =
    qccGenericDynamicCaptureContext(
      capture
    );

  if (
    context.tab_id
      !== expected.tab_id
  ) {
    throw new Error(
      "QCC_GENERIC_DYNAMIC_HARVEST_TAB_CHANGED"
    );
  }

  if (
    !context.origin
    || context.origin
      !== expected.origin
  ) {
    throw new Error(
      "QCC_GENERIC_DYNAMIC_HARVEST_ORIGIN_CHANGED"
    );
  }

  if (!context.document_id) {
    throw new Error(
      "QCC_GENERIC_DYNAMIC_HARVEST_DOCUMENT_ID_REQUIRED"
    );
  }

  if (
    context.document_id
      !== expected.document_id
  ) {
    throw new Error(
      "QCC_GENERIC_DYNAMIC_HARVEST_DOCUMENT_CHANGED"
    );
  }

  return context;
}


async function qccGenericDynamicAssertContext(
  expected
) {
  const tab =
    await qccGenericHarvestActiveTab();

  if (
    tab.id
      !== expected.tab_id
  ) {
    throw new Error(
      "QCC_GENERIC_DYNAMIC_HARVEST_TAB_CHANGED"
    );
  }

  const origin =
    qccGenericDynamicOrigin(
      tab.url
    );

  if (
    !origin
    || origin
      !== expected.origin
  ) {
    throw new Error(
      "QCC_GENERIC_DYNAMIC_HARVEST_ORIGIN_CHANGED"
    );
  }

  const policy =
    await globalThis
      .QccAcquisitionPolicy
      .resolve(
        tab.url
      );

  if (
    policy?.mode
      !== globalThis
        .QccAcquisitionPolicy
        .HARVEST_ALLOWED
    || policy?.allowed
      !== true
  ) {
    throw new Error(
      "QCC_GENERIC_DYNAMIC_HARVEST_PERMISSION_REVOKED"
    );
  }

  return {
    tab:
      tab,

    policy:
      policy
  };
}


function qccGenericDynamicReadScrollPage() {
  const root =
    document.documentElement;

  const body =
    document.body;

  const scrollHeight =
    Math.max(
      Number(
        root?.scrollHeight
        || 0
      ),
      Number(
        body?.scrollHeight
        || 0
      )
    );

  const viewportHeight =
    Number(
      window.innerHeight
      || root?.clientHeight
      || 0
    );

  const scrollY =
    Number(
      window.scrollY
      || 0
    );

  const scrollX =
    Number(
      window.scrollX
      || 0
    );

  const maxY =
    Math.max(
      0,
      scrollHeight
        - viewportHeight
    );

  return {
    scroll_x:
      scrollX,

    scroll_y:
      scrollY,

    viewport_height:
      viewportHeight,

    scroll_height:
      scrollHeight,

    max_y:
      maxY,

    at_bottom:
      (
        scrollY
          >= Math.max(
            0,
            maxY - 2
          )
      )
  };
}


function qccGenericDynamicScrollPage(
  fraction
) {
  /*
   * IMPORTANTE:
   * esta función se serializa mediante executeScript().
   * No puede depender de helpers del Service Worker.
   */
  function readState() {
    const root =
      document.documentElement;

    const body =
      document.body;

    const scrollHeight =
      Math.max(
        Number(
          root?.scrollHeight
          || 0
        ),
        Number(
          body?.scrollHeight
          || 0
        )
      );

    const viewportHeight =
      Number(
        window.innerHeight
        || root?.clientHeight
        || 0
      );

    const scrollY =
      Number(
        window.scrollY
        || 0
      );

    const scrollX =
      Number(
        window.scrollX
        || 0
      );

    const maxY =
      Math.max(
        0,
        scrollHeight
          - viewportHeight
      );

    return {
      scroll_x:
        scrollX,

      scroll_y:
        scrollY,

      viewport_height:
        viewportHeight,

      scroll_height:
        scrollHeight,

      max_y:
        maxY,

      at_bottom:
        (
          scrollY
            >= Math.max(
              0,
              maxY - 2
            )
        )
    };
  }


  const before =
    readState();

  const normalizedFraction =
    Math.min(
      1,
      Math.max(
        0.1,
        Number(
          fraction
          || 0.75
        )
      )
    );

  const delta =
    Math.max(
      1,
      Math.floor(
        before.viewport_height
          * normalizedFraction
      )
    );

  const targetY =
    Math.min(
      before.max_y,
      before.scroll_y
        + delta
    );

  window.scrollTo({
    left:
      before.scroll_x,

    top:
      targetY,

    behavior:
      "auto"
  });

  const after =
    readState();

  return {
    before:
      before,

    target_y:
      targetY,

    after:
      after,

    moved:
      (
        Math.abs(
          after.scroll_y
            - before.scroll_y
        )
        > 1
      )
  };
}


function qccGenericDynamicRestorePage(
  x,
  y
) {
  /*
   * También se ejecuta dentro de la página.
   * Debe ser completamente autosuficiente.
   */
  window.scrollTo({
    left:
      Number(
        x
        || 0
      ),

    top:
      Number(
        y
        || 0
      ),

    behavior:
      "auto"
  });


  const root =
    document.documentElement;

  const body =
    document.body;

  const scrollHeight =
    Math.max(
      Number(
        root?.scrollHeight
        || 0
      ),
      Number(
        body?.scrollHeight
        || 0
      )
    );

  const viewportHeight =
    Number(
      window.innerHeight
      || root?.clientHeight
      || 0
    );

  const scrollY =
    Number(
      window.scrollY
      || 0
    );

  const scrollX =
    Number(
      window.scrollX
      || 0
    );

  const maxY =
    Math.max(
      0,
      scrollHeight
        - viewportHeight
    );

  return {
    scroll_x:
      scrollX,

    scroll_y:
      scrollY,

    viewport_height:
      viewportHeight,

    scroll_height:
      scrollHeight,

    max_y:
      maxY,

    at_bottom:
      (
        scrollY
          >= Math.max(
            0,
            maxY - 2
          )
      )
  };
}


async function qccGenericDynamicReadScroll(
  tabId
) {
  const results =
    await chrome.scripting.executeScript({
      target: {
        tabId:
          tabId,

        frameIds: [
          0
        ]
      },

      world:
        "ISOLATED",

      func:
        qccGenericDynamicReadScrollPage
    });

  const state =
    results?.[0]?.result;

  if (!state) {
    throw new Error(
      "QCC_GENERIC_DYNAMIC_SCROLL_STATE_UNAVAILABLE"
    );
  }

  return state;
}


async function qccGenericDynamicScrollStep(
  tabId
) {
  const results =
    await chrome.scripting.executeScript({
      target: {
        tabId:
          tabId,

        frameIds: [
          0
        ]
      },

      world:
        "ISOLATED",

      func:
        qccGenericDynamicScrollPage,

      args: [
        QCC_GENERIC_DYNAMIC_SCROLL_FRACTION
      ]
    });

  const result =
    results?.[0]?.result;

  if (!result) {
    throw new Error(
      "QCC_GENERIC_DYNAMIC_SCROLL_STEP_FAILED"
    );
  }

  return result;
}


async function qccGenericDynamicRestoreScroll(
  tabId,
  initialScroll
) {
  const results =
    await chrome.scripting.executeScript({
      target: {
        tabId:
          tabId,

        frameIds: [
          0
        ]
      },

      world:
        "ISOLATED",

      func:
        qccGenericDynamicRestorePage,

      args: [
        initialScroll.scroll_x,
        initialScroll.scroll_y
      ]

    });
  return (
    results?.[0]?.result
    || null
  );
}


function qccGenericDynamicWait(
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


function qccGenericDynamicIdentity(
  item
) {
  const base =
    qccGenericHarvestIdentity(
      item
    );

  /*
   * Los elementos con selector ya poseen
   * identidad estable dentro del frame.
   */
  if (item?.selector) {
    return base;
  }

  /*
   * En el fallback de source_index añadimos
   * semántica para no confundir un nodo virtualizado
   * cuyo contenido haya cambiado durante el scroll.
   */
  return (
    base
    + "::"
    + qccGenericHarvestText(
        item?.tag
      )
    + "::"
    + qccGenericHarvestText(
        item?.id
      )
    + "::"
    + qccGenericHarvestText(
        item?.name
      )
    + "::"
    + qccGenericHarvestText(
        item?.href
      )
    + "::"
    + qccGenericHarvestText(
        item?.accessible_name
      )
    + "::"
    + qccGenericHarvestText(
        item?.text
      ).slice(
        0,
        220
      )
  );
}


function qccGenericDynamicMergeDataset(
  accumulated,
  dataset,
  step
) {
  let newItems =
    0;

  const sourceItems =
    (
      Array.isArray(
        dataset?.items
      )
      ? dataset.items
      : []
    );

  for (const item of sourceItems) {
    const identity =
      qccGenericDynamicIdentity(
        item
      );

    const existing =
      accumulated.get(
        identity
      );

    if (!existing) {
      accumulated.set(
        identity,
        {
          ...item,

          first_seen_step:
            step,

          last_seen_step:
            step,

          observations:
            1
        }
      );

      newItems +=
        1;

      continue;
    }

    existing.last_seen_step =
      step;

    existing.observations =
      Number(
        existing.observations
        || 0
      ) + 1;

    /*
     * Conservamos la evidencia más reciente
     * de visibilidad/geometría.
     */
    existing.visible =
      item.visible;

    existing.in_viewport =
      item.in_viewport;

    existing.geometry =
      item.geometry;

    /*
     * Si la primera observación no tenía
     * algún dato semántico, completamos
     * sin sobrescribir evidencia previa útil.
     */
    for (
      const field
      of [
        "id",
        "name",
        "type",
        "role",
        "text",
        "accessible_name",
        "href"
      ]
    ) {
      if (
        !existing[field]
        && item[field]
      ) {
        existing[field] =
          item[field];
      }
    }
  }

  return {
    observed_items:
      sourceItems.length,

    new_items:
      newItems
  };
}


async function qccGenericDynamicTryRestore(
  expected,
  initialScroll
) {
  const result = {
    attempted:
      false,

    exact:
      null,

    error:
      null
  };

  try {
    await qccGenericDynamicAssertContext(
      expected
    );

    const capture =
      await inspectActiveTabDom();

    qccGenericDynamicVerifyCapture(
      capture,
      expected
    );

    result.attempted =
      true;

    await qccGenericDynamicRestoreScroll(
      expected.tab_id,
      initialScroll
    );

    await qccGenericDynamicWait(
      QCC_GENERIC_DYNAMIC_RESTORE_WAIT_MS
    );

    const restored =
      await qccGenericDynamicReadScroll(
        expected.tab_id
      );

    result.exact =
      (
        Math.abs(
          Number(
            restored.scroll_x
            || 0
          )
          - Number(
              initialScroll.scroll_x
              || 0
            )
        )
        <= 2
        &&
        Math.abs(
          Number(
            restored.scroll_y
            || 0
          )
          - Number(
              initialScroll.scroll_y
              || 0
            )
        )
        <= 2
      );

  } catch (error) {
    result.error =
      String(
        error?.message
        || error
      );
  }

  return result;
}


async function runGenericDynamicHarvest() {
  const startedAt =
    new Date().toISOString();

  const initial =
    await resolveGenericHarvestActivePolicy();

  if (
    initial.policy?.mode
      !== globalThis
        .QccAcquisitionPolicy
        .HARVEST_ALLOWED
    || initial.policy?.allowed
      !== true
  ) {
    throw new Error(
      "QCC_GENERIC_DYNAMIC_HARVEST_NOT_ALLOWED"
    );
  }


  const initialCapture =
    await inspectActiveTabDom();

  if (
    !initialCapture
    || initialCapture.ok !== true
  ) {
    throw new Error(
      initialCapture?.error
      || "QCC_GENERIC_DYNAMIC_HARVEST_CAPTURE_INVALID"
    );
  }


  const initialContext =
    qccGenericDynamicCaptureContext(
      initialCapture
    );

  if (
    initialContext.tab_id
      !== initial.tab.id
  ) {
    throw new Error(
      "QCC_GENERIC_DYNAMIC_HARVEST_TAB_CHANGED"
    );
  }

  if (!initialContext.origin) {
    throw new Error(
      "QCC_GENERIC_DYNAMIC_HARVEST_ORIGIN_REQUIRED"
    );
  }

  if (!initialContext.document_id) {
    throw new Error(
      "QCC_GENERIC_DYNAMIC_HARVEST_DOCUMENT_ID_REQUIRED"
    );
  }


  const expected = {
    tab_id:
      initial.tab.id,

    origin:
      initialContext.origin,

    document_id:
      initialContext.document_id
  };


  const initialScroll =
    await qccGenericDynamicReadScroll(
      expected.tab_id
    );


  const accumulated =
    new Map();

  const steps =
    [];

  let observedRawItems =
    0;

  let observedFilteredItems =
    0;

  let observedItems =
    0;

  let stagnation =
    0;

  let stopReason =
    "MAX_STEPS";

  let runError =
    null;


  function consumeDataset(
    dataset,
    step,
    scroll
  ) {
    observedRawItems +=
      Number(
        dataset?.raw_item_count
        || 0
      );

    observedFilteredItems +=
      Number(
        dataset?.filtered_out_count
        || 0
      );

    observedItems +=
      Number(
        dataset?.item_count
        || 0
      );

    const merge =
      qccGenericDynamicMergeDataset(
        accumulated,
        dataset,
        step
      );

    steps.push({
      step:
        step,

      captured_at:
        String(
          dataset?.harvested_at
          || ""
        ),

      observed_items:
        merge.observed_items,

      new_items:
        merge.new_items,

      unique_items:
        accumulated.size,

      scroll:
        scroll
        || null
    });

    return merge;
  }


  const initialDataset =
    buildGenericDomHarvestDataset(
      initialCapture,
      initial.policy
    );

  consumeDataset(
    initialDataset,
    0,
    {
      initial:
        true,

      state:
        initialScroll
    }
  );


  try {
    for (
      let step = 1;
      step
        <= QCC_GENERIC_DYNAMIC_MAX_STEPS;
      step += 1
    ) {
      /*
       * Gate ANTES de cualquier nuevo scroll.
       */
      await qccGenericDynamicAssertContext(
        expected
      );


      const scroll =
        await qccGenericDynamicScrollStep(
          expected.tab_id
        );


      await qccGenericDynamicWait(
        QCC_GENERIC_DYNAMIC_WAIT_MS
      );


      /*
       * Gate DESPUÉS del scroll y antes
       * de aceptar nueva evidencia.
       */
      const current =
        await qccGenericDynamicAssertContext(
          expected
        );


      const capture =
        await inspectActiveTabDom();

      qccGenericDynamicVerifyCapture(
        capture,
        expected
      );


      /*
       * La política se vuelve a resolver para
       * construir el dataset con autoridad viva.
       */
      const livePolicy =
        await globalThis
          .QccAcquisitionPolicy
          .resolve(
            current.tab.url
          );

      if (
        livePolicy?.mode
          !== globalThis
            .QccAcquisitionPolicy
            .HARVEST_ALLOWED
        || livePolicy?.allowed
          !== true
      ) {
        throw new Error(
          "QCC_GENERIC_DYNAMIC_HARVEST_PERMISSION_REVOKED"
        );
      }


      const dataset =
        buildGenericDomHarvestDataset(
          capture,
          livePolicy
        );


      const merge =
        consumeDataset(
          dataset,
          step,
          scroll
        );


      if (
        merge.new_items === 0
      ) {
        stagnation +=
          1;

      } else {
        stagnation =
          0;
      }


      if (
        stagnation
          >= QCC_GENERIC_DYNAMIC_STAGNATION_LIMIT
      ) {
        stopReason =
          "STAGNATION_LIMIT";

        break;
      }


      if (
        scroll?.after?.at_bottom === true
        && merge.new_items === 0
      ) {
        stopReason =
          "BOTTOM_REACHED";

        break;
      }


      if (
        scroll?.moved !== true
        && merge.new_items === 0
      ) {
        stopReason =
          "NO_SCROLL_PROGRESS";

        break;
      }
    }

  } catch (error) {
    runError =
      error;
  }


  /*
   * Restauración best-effort.
   *
   * Solo se ejecuta si siguen siendo válidos
   * tab/origin/policy/document.
   */
  const restoration =
    await qccGenericDynamicTryRestore(
      expected,
      initialScroll
    );


  if (runError) {
    throw runError;
  }


  const items =
    Array.from(
      accumulated.values()
    );


  const completedAt =
    new Date().toISOString();


  return {
    ok:
      true,

    dataset: {
      schema_version:
        1,

      artifact_type:
        "QCC_GENERIC_DYNAMIC_HARVEST",

      acquisition_mode:
        globalThis
          .QccAcquisitionPolicy
          .HARVEST_ALLOWED,

      source:
        String(
          initial.policy?.source
          || ""
        ),

      started_at:
        startedAt,

      completed_at:
        completedAt,

      origin:
        initialContext.origin,

      pathname:
        (() => {
          try {
            return new URL(
              initialContext.url
            ).pathname;

          } catch (_) {
            return "";
          }
        })(),

      url:
        initialContext.url,

      tab_id:
        expected.tab_id,

      document_id:
        expected.document_id,

      config: {
        max_steps:
          QCC_GENERIC_DYNAMIC_MAX_STEPS,

        scroll_fraction:
          QCC_GENERIC_DYNAMIC_SCROLL_FRACTION,

        wait_ms:
          QCC_GENERIC_DYNAMIC_WAIT_MS,

        stagnation_limit:
          QCC_GENERIC_DYNAMIC_STAGNATION_LIMIT
      },

      snapshot_count:
        steps.length,

      scroll_steps_completed:
        Math.max(
          0,
          steps.length - 1
        ),

      stop_reason:
        stopReason,

      observed_raw_item_count:
        observedRawItems,

      filtered_out_count:
        observedFilteredItems,

      observed_item_count:
        observedItems,

      item_count:
        items.length,

      deduplicated_count:
        items.length,

      duplicates_removed:
        Math.max(
          0,
          observedItems
            - items.length
        ),

      initial_scroll:
        initialScroll,

      restoration:
        restoration,

      steps:
        steps,

      items:
        items
    }
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
        !== "QCC_GENERIC_DYNAMIC_HARVEST"
    ) {
      return false;
    }


    runGenericDynamicHarvest()
      .then(
        sendResponse
      )
      .catch(
        (error) => {
          console.warn(
            "[QCC] Generic Dynamic Harvest:",
            error
          );

          sendResponse({
            ok:
              false,

            error:
              String(
                error?.message
                || error
                || "QCC_GENERIC_DYNAMIC_HARVEST_FAILED"
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
