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

importScripts(
  "../shared/catalog_dependency_planner.js"
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

/*
 * Human discovery interaction window.
 *
 * The listener remains:
 * - exact-document bound;
 * - exact-frame bound;
 * - exact-tab bound;
 * - selector constrained;
 * - single-shot.
 *
 * A human operator must not be forced to act within 30 seconds.
 */
const QCC_HUMAN_LISTENER_TTL_MS =
  30 * 60 * 1000;

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
  ttlMs,
  eventMode
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
    (
      message,
      waitForAck = false
    ) =>
      new Promise(
        (resolve, reject) => {
          try {
            const port =
              chrome.runtime.connect({
                name:
                  "QCC_HUMAN_DOM_ACTION_PORT"
              });


            if (
              waitForAck !== true
            ) {
              /*
               * Legacy POINTERDOWN:
               * navigation may destroy the document immediately.
               */
              port.postMessage(
                message
              );

              resolve({
                ok:
                  true,

                queued:
                  true
              });

              return;
            }


            /*
             * QCC_RIGHT_CLICK_CAUSAL_ACK_V2
             *
             * CONTEXTMENU itself does not navigate.
             * We can wait until:
             *
             * fresh capture
             *   -> fresh evidence
             *   -> Bridge accepted action
             *
             * before telling the user to LEFT CLICK.
             */
            let settled = false;


            const timer =
              setTimeout(
                () => {
                  if (settled) {
                    return;
                  }

                  settled = true;

                  reject(
                    new Error(
                      "QCC_HUMAN_DOM_ACTION_ACK_TIMEOUT"
                    )
                  );
                },
                10000
              );


            const settle =
              (
                callback,
                value
              ) => {
                if (settled) {
                  return;
                }

                settled = true;

                try {
                  clearTimeout(
                    timer
                  );
                } catch (_) {
                  // No-op.
                }

                callback(
                  value
                );
              };


            port.onMessage.addListener(
              (response) => {
                if (
                  response?.type
                    !== "QCC_HUMAN_DOM_ACTION_ACK"
                ) {
                  return;
                }


                if (
                  response?.ok === true
                ) {
                  settle(
                    resolve,
                    response
                  );

                  return;
                }


                settle(
                  reject,
                  new Error(
                    String(
                      response?.error
                      || "QCC_HUMAN_DOM_ACTION_ACK_REJECTED"
                    )
                  )
                );
              }
            );


            port.onDisconnect.addListener(
              () => {
                if (settled) {
                  return;
                }

                settle(
                  reject,
                  new Error(
                    "QCC_HUMAN_DOM_ACTION_ACK_DISCONNECTED"
                  )
                );
              }
            );


            port.postMessage(
              message
            );

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


  const normalizedEventMode =
    String(
      eventMode
      || "POINTERDOWN"
    )
      .trim()
      .toUpperCase();


  const listenerEventName =
    (
      normalizedEventMode
      === "CONTEXTMENU"
      ? "contextmenu"
      : "pointerdown"
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

      document.removeEventListener(
        "contextmenu",
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
        listenerEventName,
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


  /*
   * QCC_ONCLICK_STRUCTURAL_RUNTIME_MATCH_V1
   *
   * Site Architecture sanitiza el selector ONCLICK durable para que
   * el literal real jamás entre en identidad de addressability
   * (p.ej. continuar('INI') se persiste como continuar();). El DOM
   * físico de Mercurio sigue teniendo el literal en el atributo
   * onclick real.
   *
   * Este fallback SOLO existe para volver a encontrar, en runtime y
   * dentro de este mismo boundary inyectado, el mismo elemento físico
   * que ya fue canonicalizado por Site Architecture. Nunca evalúa
   * JavaScript, nunca infiere expresiones dinámicas y nunca emite el
   * literal observado: únicamente se transporta `selector`, el
   * candidato canónico ya sanitizado recibido como parámetro.
   *
   * Debe ser autocontenido: esta función se inyecta vía
   * chrome.scripting.executeScript, así que cualquier helper que
   * necesite debe vivir dentro de este mismo scope inyectado.
   */
  const ONCLICK_SAFE_HANDLER_RE =
    /^(?:return\s+)?(?:window\.)?[A-Za-z_$][A-Za-z0-9_$]*\(\s*(?:(?:'[A-Za-z0-9_ .:/-]{0,128}'|"[A-Za-z0-9_ .:/-]{0,128}"|-?[0-9]+(?:\.[0-9]+)?|true|false|null)(?:\s*,\s*(?:'[A-Za-z0-9_ .:/-]{0,128}'|"[A-Za-z0-9_ .:/-]{0,128}"|-?[0-9]+(?:\.[0-9]+)?|true|false|null))*)?\s*\)\s*;?$/;

  const ONCLICK_HANDLER_NAME_RE =
    /^(?:return\s+)?(?:window\.)?([A-Za-z_$][A-Za-z0-9_$]*)\s*\(/;

  const ONCLICK_UNSAFE_HANDLER_NAMES =
    new Set([
      "alert",
      "confirm",
      "prompt",
      "eval",
      "function",
      "settimeout",
      "setinterval"
    ]);

  /*
   * Solo reconoce EXACTAMENTE la forma canónica que Site
   * Architecture puede emitir para ONCLICK: tag + handler seguro
   * (simple/return/window) sin literal, porque el literal nunca
   * sobrevive a la sanitización durable. El sufijo opcional
   * :qcc-nth-onclick(N) es la disambiguación posicional privacy-safe
   * (QCC_ONCLICK_STRUCTURAL_POSITIONAL_DISAMBIGUATION_V1): nunca es
   * CSS nativo válido (por diseño, para que .matches()/.closest()
   * fallen de forma segura y este fallback estructural sea quien
   * realmente lo resuelva), y jamás contiene el literal físico.
   */
  const ONCLICK_SELECTOR_RE =
    /^([A-Za-z][A-Za-z0-9]*)\[onclick="((?:return\s+)?(?:window\.)?[A-Za-z_$][A-Za-z0-9_$]*\(\)\s*;?)"\](?::qcc-nth-onclick\((\d+)\))?$/;

  function qccOnclickStructuralSignature(
    rawValue
  ) {
    const value =
      String(
        rawValue
        || ""
      );

    if (
      !ONCLICK_SAFE_HANDLER_RE.test(
        value
      )
    ) {
      return null;
    }

    const nameMatch =
      value.match(
        ONCLICK_HANDLER_NAME_RE
      );

    if (!nameMatch) {
      return null;
    }

    if (
      ONCLICK_UNSAFE_HANDLER_NAMES.has(
        nameMatch[1].toLowerCase()
      )
    ) {
      return null;
    }

    const trailingSemicolon =
      value.trim().endsWith(";");

    /*
     * El literal jamás se preserva: la firma solo conserva
     * handler + aridad-cero, igual que la sanitización durable
     * de Site Architecture.
     */
    return (
      nameMatch[0]
      + ")"
      + (
        trailingSemicolon
        ? ";"
        : ""
      )
    );
  }

  function qccParseOnclickStructuralSelector(
    selector
  ) {
    const match =
      ONCLICK_SELECTOR_RE.exec(
        selector
      );

    if (!match) {
      return null;
    }

    const position =
      match[3] !== undefined
      ? Number(match[3])
      : null;

    if (
      position !== null
      && (
        !Number.isInteger(position)
        || position < 1
      )
    ) {
      return null;
    }

    return {
      tag:
        match[1].toLowerCase(),

      signature:
        match[2],

      position:
        position
    };
  }

  /*
   * QCC_ONCLICK_STRUCTURAL_POSITIONAL_DISAMBIGUATION_V1
   *
   * Cuando varios controles físicos comparten una misma firma
   * estructural (p.ej. validarYEnviar('AB') y validarYEnviar('IN')
   * colapsan ambos a validarYEnviar()), Site Architecture puede haber
   * emitido un selector con el sufijo :qcc-nth-onclick(N): el rango
   * 1-based de `node` entre TODOS los elementos del documento que
   * comparten exactamente (tag, firma estructural), en orden de
   * documento. Nunca lee ni transporta el literal físico; solo cuenta
   * ocurrencias estructurales.
   */
  function qccOnclickStructuralPosition(
    node,
    parsed
  ) {
    let candidates;

    try {
      candidates =
        document.querySelectorAll(
          parsed.tag
        );
    } catch (_) {
      return null;
    }

    let rank = 0;

    for (
      const candidate
      of candidates
    ) {
      let rawOnclick;

      try {
        rawOnclick =
          candidate.getAttribute(
            "onclick"
          );
      } catch (_) {
        continue;
      }

      if (!rawOnclick) {
        continue;
      }

      const signature =
        qccOnclickStructuralSignature(
          rawOnclick
        );

      if (
        signature === null
        || signature
          !== parsed.signature
      ) {
        continue;
      }

      rank += 1;

      if (candidate === node) {
        return rank;
      }
    }

    return null;
  }

  function qccMatchesOnclickStructural(
    node,
    parsed
  ) {
    if (
      !node
      || node.nodeType !== 1
      || typeof node.getAttribute
        !== "function"
    ) {
      return false;
    }

    if (
      String(
        node.tagName
        || ""
      ).toLowerCase()
        !== parsed.tag
    ) {
      return false;
    }

    let rawOnclick;

    try {
      rawOnclick =
        node.getAttribute(
          "onclick"
        );
    } catch (_) {
      return false;
    }

    if (!rawOnclick) {
      return false;
    }

    const signature =
      qccOnclickStructuralSignature(
        rawOnclick
      );

    /*
     * rawOnclick puede contener el literal físico (p.ej. 'INI' o un
     * valor tipo PII). Solo se usa aquí, de forma transitoria, para
     * derivar `signature`. Nunca se asigna a `matched`, nunca se
     * transporta y nunca se persiste.
     */
    if (
      signature === null
      || signature !== parsed.signature
    ) {
      return false;
    }

    if (parsed.position === null) {
      return true;
    }

    const position =
      qccOnclickStructuralPosition(
        node,
        parsed
      );

    return (
      position !== null
      && position === parsed.position
    );
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

      /*
       * Fallback estructural ONCLICK.
       *
       * Solo se activa cuando:
       * - el camino exacto (closest/matches) no encontró nada;
       * - el candidato es EXACTAMENTE la forma canónica ONCLICK
       *   sanitizada (misma familia segura que Site Architecture).
       *
       * Selectores exactos ordinarios (#id, [data-testid], etc.)
       * jamás entran aquí y siguen usando solo closest/matches.
       */
      if (!found) {
        const parsedOnclick =
          qccParseOnclickStructuralSelector(
            selector
          );

        if (parsedOnclick) {
          const composedChain =
            (
              typeof event.composedPath
                === "function"
              ? event.composedPath()
              : []
            );

          const structuralChain =
            composedChain.length > 0
            ? composedChain
            : (
                () => {
                  const built = [];
                  let cursor = target;

                  while (cursor) {
                    built.push(
                      cursor
                    );

                    cursor =
                      cursor.parentElement
                      || null;
                  }

                  return built;
                }
              )();

          for (
            const candidate
            of structuralChain
          ) {
            if (
              qccMatchesOnclickStructural(
                candidate,
                parsedOnclick
              )
            ) {
              found =
                true;

              break;
            }
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


  function showQccRightClickCausalFeedback(
    message,
    success
  ) {
    const TOAST_ID =
      "__qcc_right_click_causal_feedback_v2__";

    try {
      const previous =
        document.getElementById(
          TOAST_ID
        );

      if (previous) {
        previous.remove();
      }


      const toast =
        document.createElement(
          "div"
        );

      toast.id =
        TOAST_ID;

      toast.textContent =
        String(
          message
          || ""
        );


      Object.assign(
        toast.style,
        {
          position:
            "fixed",

          top:
            "16px",

          right:
            "16px",

          zIndex:
            "2147483647",

          padding:
            "10px 14px",

          borderRadius:
            "8px",

          fontFamily:
            "Arial, sans-serif",

          fontSize:
            "13px",

          fontWeight:
            "600",

          color:
            "#ffffff",

          background:
            (
              success === true
              ? "#176b3a"
              : "#8b1e1e"
            ),

          boxShadow:
            "0 3px 12px rgba(0,0,0,.28)",

          pointerEvents:
            "none"
        }
      );


      (
        document.body
        || document.documentElement
      ).appendChild(
        toast
      );


      setTimeout(
        () => {
          try {
            toast.remove();
          } catch (_) {
            // No-op.
          }
        },
        2800
      );

    } catch (_) {
      // Feedback is fail-open.
    }
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


    /*
     * QCC_RIGHT_CLICK_CAUSAL_CAPTURE_V1
     *
     * In Twin Discovery the human explicitly declares:
     *
     *   "this is the action I am about to execute"
     *
     * Right click must not execute the site action and must
     * not open the browser/page context menu.
     *
     * We only suppress it AFTER resolving exactly one
     * canonical governed selector.
     */
    if (
      normalizedEventMode
      === "CONTEXTMENU"
    ) {
      try {
        event.preventDefault();
        event.stopPropagation();
      } catch (_) {
        // No-op.
      }
    }


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
      const waitForAck =
        (
          normalizedEventMode
          === "CONTEXTMENU"
        );


      const promise =
        qccHumanPortSend(
          {
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
          },
          waitForAck
        );


      if (
        promise
        && typeof promise.then
          === "function"
      ) {
        if (
          waitForAck
        ) {
          promise
            .then(
              () => {
                showQccRightClickCausalFeedback(
                  "✓ AUTO TWIN · acción capturada · pulsa clic izquierdo",
                  true
                );
              }
            )
            .catch(
              (error) => {
                showQccRightClickCausalFeedback(
                  (
                    "✕ AUTO TWIN · captura causal fallida · "
                    + String(
                        error?.message
                        || error
                        || "UNKNOWN"
                      )
                  ),
                  false
                );
              }
            );

        } else {
          promise.catch(
            () => {}
          );
        }
      }

    } catch (_) {
      // Fail closed:
      // si Service Worker no responde,
      // no se aprende nada.
    }
  }


  document.addEventListener(
    listenerEventName,
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


/*
 * QCC_DISCOVERY_HUMAN_LISTENER_AUTO_ARM_V1
 *
 * Arms the human listener only after backend has already:
 * - resolved the technical observation scope;
 * - projected CURRENT A;
 * - canonicalized addressable actions;
 * - returned a locator-only listener plan.
 *
 * capture.frames comes from the exact executeScript snapshot A:
 *
 *   [{ frame_id, document_id, result }]
 *
 * No authority fields are reconstructed in Chrome.
 */
async function autoArmDiscoveryHumanListener(
  backendResult,
  tabId,
  capture
) {
  if (
    backendResult
      ?.human_listener_auto_arm
      !== true
  ) {
    return {
      armed:
        false,

      reason:
        "AUTO_ARM_NOT_REQUESTED"
    };
  }


  const normalizedTabId =
    Number(
      tabId
    );

  const scopeId =
    String(
      backendResult
        ?.human_listener_scope_id
      || ""
    ).trim();

  const listenerPlan =
    backendResult
      ?.human_listener_plan;

  const evidenceId =
    String(
      backendResult
        ?.human_listener_evidence_id
      || ""
    ).trim();

  const targets =
    (
      Array.isArray(
        listenerPlan?.targets
      )
      ? listenerPlan.targets
      : []
    );

  const frameDocuments =
    (
      Array.isArray(
        capture?.frames
      )
      ? capture.frames
      : []
    );


  if (
    !Number.isInteger(
      normalizedTabId
    )
    || !scopeId
    || !evidenceId
    || targets.length === 0
    || frameDocuments.length === 0
  ) {
    return {
      armed:
        false,

      reason:
        "AUTO_ARM_INPUT_INCOMPLETE"
    };
  }


  try {
    const result =
      await armQccHumanClickListeners({
        tab_id:
          normalizedTabId,

        /*
         * Compatibility carrier.
         *
         * For Discovery this is an ObservationScope id,
         * not a PresentationSession.
         */
        session_id:
          scopeId,

        evidence_id:
          evidenceId,

        /*
         * Twin Discovery causal authority is explicit.
         *
         * The user RIGHT-CLICKS the control first,
         * then LEFT-CLICKS normally to navigate.
         */
        event_mode:
          "CONTEXTMENU",

        targets:
          targets,

        frame_documents:
          frameDocuments
      });


    console.debug(
      "[QCC] Discovery human listener auto-arm:",
      {
        armed:
          result?.armed
          === true,

        target_count:
          Number(
            result?.target_count
            || 0
          )
      }
    );


    return result;

  } catch (error) {
    /*
     * Fail-open for Site Architecture capture.
     * Fail-closed for causal human observation.
     */
    console.debug(
      "[QCC] Discovery human listener auto-arm skipped:",
      String(
        error?.message
        || error
      )
    );


    return {
      armed:
        false,

      reason:
        String(
          error?.message
          || error
        )
    };
  }
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

  const evidenceId =
    String(
      request?.evidence_id
      || ""
    ).trim();


  const eventMode =
    String(
      request?.event_mode
      || "POINTERDOWN"
    )
      .trim()
      .toUpperCase();


  if (
    eventMode !== "POINTERDOWN"
    && eventMode !== "CONTEXTMENU"
  ) {
    throw new Error(
      "QCC_HUMAN_LISTENER_EVENT_MODE_INVALID"
    );
  }


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

        evidence_id:
          evidenceId,

        event_mode:
          eventMode,

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
            QCC_HUMAN_LISTENER_TTL_MS,
            eventMode
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

    } catch (error) {

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


/*
 * QCC_RIGHT_CLICK_FRESH_EVIDENCE_V1
 *
 * Explicit Twin Discovery causality:
 *
 *   trusted RIGHT CLICK X
 *       ↓
 *   fresh capture A
 *       ↓
 *   fresh backend evidence_id(A)
 *       ↓
 *   A --X--> ?
 *
 * We do NOT trust the evidence_id belonging to the previous
 * automatic arm as causal authority for CONTEXTMENU.
 */

async function qccCaptureFreshRightClickCausalEvidence(
  arm,
  selector,
  framePath
) {
  const tabId =
    Number(
      arm?.tab_id
    );


  if (
    !Number.isInteger(
      tabId
    )
  ) {
    throw new Error(
      "QCC_RIGHT_CLICK_TAB_INVALID"
    );
  }


  const expectedDocumentId =
    String(
      arm?.document_id
      || ""
    ).trim();


  if (!expectedDocumentId) {
    throw new Error(
      "QCC_RIGHT_CLICK_DOCUMENT_REQUIRED"
    );
  }


  /*
   * Fresh DOM/geometry/catalog snapshot taken only after
   * the trusted contextmenu event has identified the action,
   * but BEFORE any left-click navigation.
   */
  const capture =
    await inspectSpecificTabDom(
      tabId
    );


  const documentId =
    qccAutomaticMainDocumentId(
      capture
    );


  /*
   * Exact-document invariant.
   *
   * If navigation somehow occurred between right-click intent
   * and capture, fail closed rather than joining across pages.
   */
  if (
    !documentId
    || documentId
      !== expectedDocumentId
  ) {
    throw new Error(
      "QCC_RIGHT_CLICK_DOCUMENT_CHANGED"
    );
  }


  /*
   * Backend remains authority for:
   * - canonical functional state;
   * - fingerprint;
   * - addressable actions;
   * - LiveActionEvidence / evidence_id.
   */
  const backendResult =
    await qccSubmitAutomaticDomCapture(
      capture
    );


  const evidenceId =
    String(
      backendResult
        ?.human_listener_evidence_id
      || ""
    ).trim();


  if (!evidenceId) {
    throw new Error(
      "QCC_RIGHT_CLICK_FRESH_EVIDENCE_MISSING"
    );
  }


  const targets =
    (
      Array.isArray(
        backendResult
          ?.human_listener_plan
          ?.targets
      )
      ? backendResult
          .human_listener_plan
          .targets
      : []
    );


  const exactTargets =
    targets.filter(
      (target) =>
        String(
          target?.selector
          || ""
        ).trim()
          === selector
        && String(
          target?.frame_path
          || ""
        ).trim()
          === framePath
    );


  /*
   * The selector received from the trusted right-click must
   * also exist in the NEW canonical capture.
   *
   * No stale selector/evidence combinations.
   */
  if (
    exactTargets.length !== 1
  ) {
    throw new Error(
      "QCC_RIGHT_CLICK_FRESH_TARGET_NOT_CANONICAL"
    );
  }


  /*
   * Rearm from the fresh capture.
   *
   * This keeps the document usable if the user marks another
   * action without navigating. Failure here does NOT invalidate
   * the fresh evidence already obtained for this event.
   */
  try {
    await autoArmDiscoveryHumanListener(
      backendResult,
      tabId,
      capture
    );

  } catch (error) {
    console.debug(
      "[QCC] Right-click fresh rearm skipped:",
      String(
        error?.message
        || error
      )
    );
  }


  return {
    evidence_id:
      evidenceId,

    /*
     * IMPORTANT:
     *
     * The physical contextmenu occurred BEFORE the fresh capture.
     * Backend evidence was created DURING this operation.
     *
     * For causal ordering we timestamp the accepted causal
     * declaration AFTER the evidence exists.
     *
     * isTrusted authority still comes from the original event.
     */
    observed_at:
      new Date()
        .toISOString(),

    capture_id:
      String(
        backendResult
          ?.capture_id
        || ""
      ).trim()
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


  let effectiveEvidenceId =
    String(
      arm?.evidence_id
      || ""
    ).trim();


  let effectiveObservedAt =
    observedAt;


  const armEventMode =
    String(
      arm?.event_mode
      || "POINTERDOWN"
    )
      .trim()
      .toUpperCase();


  if (
    armEventMode
      === "CONTEXTMENU"
  ) {
    const freshEvidence =
      await qccCaptureFreshRightClickCausalEvidence(
        arm,
        selector,
        framePath
      );


    effectiveEvidenceId =
      String(
        freshEvidence
          ?.evidence_id
        || ""
      ).trim();


    effectiveObservedAt =
      String(
        freshEvidence
          ?.observed_at
        || ""
      ).trim();



    if (
      !effectiveEvidenceId
      || !effectiveObservedAt
    ) {
      throw new Error(
        "QCC_RIGHT_CLICK_FRESH_EVIDENCE_INVALID"
      );
    }
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

              evidence_id:
                effectiveEvidenceId,

              observed_at:
                effectiveObservedAt
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

      const tag =
        String(
          element.tagName
          || ""
        ).toLowerCase();

      const selector =
        (
          tag
          || "*"
        )
        + '[name="'
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


  function customCatalogComboboxOf(
    element
  ) {
    if (
      !element
      || !element.shadowRoot
    ) {
      return null;
    }

    try {
      return (
        element.shadowRoot.querySelector(
          '[role="combobox"][aria-haspopup="listbox"]'
        )
        || element.shadowRoot.querySelector(
          '[role="combobox"]'
        )
      );
    } catch (_) {
      return null;
    }
  }


  function customCatalogOptionSurfaceOf(
    element
  ) {
    if (
      !element
      || !element.shadowRoot
    ) {
      return null;
    }

    try {
      return (
        element.shadowRoot.querySelector(
          '[role="option"]'
        )
      );
    } catch (_) {
      return null;
    }
  }


  function customCatalogHiddenInputOf(
    element
  ) {
    if (!element) {
      return null;
    }

    try {
      return (
        element.querySelector(
          'input[slot="hidden"]'
        )
        || element.querySelector(
          'input[type="hidden"]'
        )
      );
    } catch (_) {
      return null;
    }
  }


  function customCatalogSelectedLabel(
    element,
    combobox
  ) {
    const candidates = [
      combobox,
      element
    ];

    for (
      const candidate
      of candidates
    ) {
      if (!candidate) {
        continue;
      }

      try {
        if (
          candidate.value !== undefined
          && candidate.value !== null
          && typeof candidate.value
            !== "object"
        ) {
          const value =
            cleanText(
              String(
                candidate.value
              ),
              300
            );

          if (value) {
            return value;
          }
        }
      } catch (_) {
        // Continúa.
      }

      try {
        const attributeValue =
          cleanText(
            candidate.getAttribute(
              "value"
            )
            || "",
            300
          );

        if (attributeValue) {
          return attributeValue;
        }
      } catch (_) {
        // Continúa.
      }
    }

    return "";
  }


  function customCatalogScalarValue(
    element
  ) {
    if (!element) {
      return "";
    }

    const candidates = [
      element
    ];


    /*
     * Algunos custom selects conservan el valor
     * seleccionado en un input interno.
     *
     * Solo lectura:
     * - light DOM;
     * - open Shadow DOM.
     */
    try {
      const hidden =
        (
          element.querySelector(
            'input[type="hidden"],input[slot="hidden"]'
          )
          || element.shadowRoot
            ?.querySelector(
              'input[type="hidden"],input[slot="hidden"]'
            )
          || null
        );

      if (
        hidden
        && hidden !== element
      ) {
        candidates.push(
          hidden
        );
      }
    } catch (_) {
      // Fail-open.
    }


    for (
      const candidate
      of candidates
    ) {
      try {
        if (
          candidate.value !== undefined
          && candidate.value !== null
          && typeof candidate.value
            !== "object"
        ) {
          const propertyValue =
            cleanText(
              String(
                candidate.value
              ),
              300
            );

          if (propertyValue) {
            return propertyValue;
          }
        }
      } catch (_) {
        // Continúa.
      }


      try {
        const attributeValue =
          cleanText(
            candidate.getAttribute(
              "value"
            )
            || "",
            300
          );

        if (attributeValue) {
          return attributeValue;
        }
      } catch (_) {
        // Continúa.
      }
    }


    /*
     * RAW desconocido permanece vacío.
     * Nunca inferimos ni fabricamos códigos.
     */
    return "";
  }


  function customCatalogOptionsOf(
    element
  ) {
    const result = [];

    if (!element) {
      return result;
    }

    let candidates = [];

    try {
      candidates =
        Array.from(
          element.children
          || []
        );
    } catch (_) {
      candidates = [];
    }

    for (
      const option
      of candidates
    ) {
      const surface =
        customCatalogOptionSurfaceOf(
          option
        );

      if (!surface) {
        continue;
      }

      const value =
        customCatalogScalarValue(
          option
        );

      let label = "";

      try {
        if (
          option.label !== undefined
          && option.label !== null
          && typeof option.label
            !== "object"
        ) {
          label =
            cleanText(
              String(
                option.label
              ),
              300
            );
        }
      } catch (_) {
        // Continúa.
      }

      if (!label) {
        label =
          cleanText(
            surface.textContent
            || option.textContent
            || "",
            300
          );
      }

      let selected = false;

      try {
        selected =
          Boolean(
            option.selected
          );
      } catch (_) {
        // Continúa con aria-selected.
      }

      if (!selected) {
        try {
          selected =
            (
              String(
                surface.getAttribute(
                  "aria-selected"
                )
                || ""
              ).toLowerCase()
              === "true"
            );
        } catch (_) {
          // Fail-open.
        }
      }

      let disabled = false;

      try {
        disabled =
          Boolean(
            option.disabled
          );
      } catch (_) {
        // Continúa.
      }

      if (!disabled) {
        try {
          disabled =
            (
              option.hasAttribute(
                "disabled"
              )
              || String(
                surface.getAttribute(
                  "aria-disabled"
                )
                || ""
              ).toLowerCase()
                === "true"
            );
        } catch (_) {
          // Fail-open.
        }
      }

            result.push({
        value,
        label,
        selected,
        disabled
      });
    }

    return result;
  }


  function customCatalogLabelOf(
    element,
    combobox
  ) {
    const attributes =
      attributesOf(
        element
      );

    const explicit =
      cleanText(
        attributes[
          "select-label"
        ]
        || attributes[
          "aria-label"
        ]
        || "",
        300
      );

    if (explicit) {
      return explicit;
    }

    if (combobox) {
      try {
        const ariaLabel =
          cleanText(
            combobox.getAttribute(
              "aria-label"
            )
            || "",
            300
          );

        if (ariaLabel) {
          return ariaLabel;
        }
      } catch (_) {
        // Fail-open.
      }
    }

    return catalogLabelOf(
      element
    );
  }


  function captureCustomCatalogs() {
    const elements =
      Array.from(
        document.querySelectorAll(
          "*"
        )
      );

    const catalogs = [];

    for (
      const element
      of elements
    ) {
      const combobox =
        customCatalogComboboxOf(
          element
        );

      if (!combobox) {
        continue;
      }

      const options =
        customCatalogOptionsOf(
          element
        );

      const selectedValue =
        customCatalogScalarValue(
          element
        );

      const selectedLabel =
        customCatalogSelectedLabel(
          element,
          combobox
        );

      let disabled = false;

      try {
        disabled =
          Boolean(
            element.disabled
          )
          || element.hasAttribute(
            "disabled"
          );
      } catch (_) {
        // Fail-open.
      }

      let required = false;

      try {
        required =
          Boolean(
            element.required
          )
          || element.hasAttribute(
            "required"
          );
      } catch (_) {
        // Fail-open.
      }

      let selectedIndex = -1;

      if (selectedValue) {
        selectedIndex =
          options.findIndex(
            function (option) {
              return (
                String(
                  option.value
                  || ""
                )
                === selectedValue
              );
            }
          );
      }

      if (
        selectedIndex < 0
        && selectedLabel
      ) {
        selectedIndex =
          options.findIndex(
            function (option) {
              return (
                String(
                  option.label
                  || ""
                )
                === selectedLabel
              );
            }
          );
      }

      catalogs.push({
        catalog_type:
          "custom_select",

        implementation:
          String(
            element.tagName
            || ""
          ).toLowerCase(),

        selector:
          catalogSelectorOf(
            element
          ),

        element: {
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

          name:
            String(
              element.getAttribute(
                "name"
              )
              || ""
            ),

          classes:
            Array.from(
              element.classList
              || []
            ),

          label_text:
            customCatalogLabelOf(
              element,
              combobox
            ),

          attributes:
            attributesOf(
              element
            )
        },

        state: {
          selected_value:
            selectedValue,

          selected_label:
            selectedLabel,

          selected_values:
            (
              selectedValue
              ? [
                  selectedValue
                ]
              : []
            ),

          selected_index:
            selectedIndex,

          disabled,
          required,
          multiple:
            false
        },

        options_count:
          options.length,

        options,

                dependency_hints:
          catalogDependencyHintsOf(
            element
          )
      });
    }

    return catalogs;
  }


  function captureCatalogProbe() {
    const nativeCatalogs =
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

    const customCatalogs =
      captureCustomCatalogs();

    const catalogs = [
      ...nativeCatalogs,
      ...customCatalogs
    ];

    return {
      schema_version:
        1,

      catalog_count:
        catalogs.length,

      native_catalog_count:
        nativeCatalogs.length,

      custom_catalog_count:
        customCatalogs.length,

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


  /*
   * Captura gobernada de Constructable Stylesheets.
   *
   * Un mismo CSS puede estar adoptado por cientos de instancias
   * de un Web Component. No repetimos el texto completo dentro de
   * cada ShadowRoot: mantenemos un catálogo por frame y cada root
   * conserva únicamente referencias ordenadas.
   *
   * Es evidencia de render, no lógica específica de proveedor.
   */
  const shadowAdoptedStyleSheetCatalog = [];

  const shadowAdoptedStyleSheetKeyToId =
    new Map();


  function adoptedStyleSheetRefsOf(
    shadowRoot
  ) {
    let sheets = [];

    try {
      sheets =
        Array.from(
          shadowRoot.adoptedStyleSheets
          || []
        );

    } catch (_) {
      return [];
    }


    return sheets.map(
      (
        sheet
      ) => {
        let rules = [];
        let cssText = "";
        let readable = true;
        let readError = null;

        try {
          rules =
            Array.from(
              sheet.cssRules
              || []
            );

          cssText =
            rules.map(
              (rule) =>
                String(
                  rule.cssText
                  || ""
                )
            ).join(
              "\n"
            );

        } catch (error) {
          readable = false;

          readError =
            String(
              error?.name
              || "CSS_RULES_UNREADABLE"
            );
        }


        let media = "";

        try {
          media =
            String(
              sheet.media?.mediaText
              || ""
            );

        } catch (_) {
          media = "";
        }


        let disabled = false;

        try {
          disabled =
            Boolean(
              sheet.disabled
            );

        } catch (_) {
          disabled = false;
        }


        let href = null;

        try {
          href =
            (
              sheet.href
              ? String(
                  sheet.href
                )
              : null
            );

        } catch (_) {
          href = null;
        }


        /*
         * Constructable Stylesheets normalmente no tienen href.
         * Conservamos el documento actual como base de resolución
         * para futuros url(...) relativos en Renderer V3.
         */
        const sourceUrl =
          (
            href
            || String(
              window.location.href
              || ""
            )
          );


        const identityKey =
          JSON.stringify({
            css_text:
              cssText,

            media:
              media,

            disabled:
              disabled,

            href:
              href,

            source_url:
              sourceUrl,

            readable:
              readable,

            read_error:
              readError
          });


        let stylesheetId =
          shadowAdoptedStyleSheetKeyToId
            .get(
              identityKey
            );


        if (!stylesheetId) {
          stylesheetId =
            (
              "shadow-sheet-"
              + String(
                  shadowAdoptedStyleSheetCatalog
                    .length
                  + 1
                ).padStart(
                  4,
                  "0"
                )
            );


          shadowAdoptedStyleSheetKeyToId
            .set(
              identityKey,
              stylesheetId
            );


          shadowAdoptedStyleSheetCatalog
            .push({
              stylesheet_id:
                stylesheetId,

              readable:
                readable,

              read_error:
                readError,

              rule_count:
                rules.length,

              media:
                media,

              disabled:
                disabled,

              href:
                href,

              source_url:
                sourceUrl,

              css_text:
                cssText
            });
        }


        return stylesheetId;
      }
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

        const adoptedStyleSheetRefs =
          adoptedStyleSheetRefsOf(
            shadowRoot
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

          adopted_stylesheet_refs:
            adoptedStyleSheetRefs,

          adopted_stylesheet_count:
            adoptedStyleSheetRefs.length,

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


  /*
   * QCC_COMPOSED_ACTION_SURFACE_V1
   *
   * Descubre de forma PASIVA una única superficie accionable
   * dentro del open Shadow DOM de un host Light DOM.
   *
   * IMPORTANTE:
   * - no genera selector canónico;
   * - no hace click;
   * - no ejecuta handlers;
   * - no usa texto como identidad;
   * - si existen varias superficies, devuelve null.
   *
   * El backend seguirá siendo la autoridad del locator.
   */
  function qccComposedActionKindOf(
    element
  ) {
    if (!element) {
      return null;
    }

    const tag =
      String(
        element.tagName
        || ""
      )
        .trim()
        .toLowerCase();

    const role =
      String(
        element.getAttribute?.(
          "role"
        )
        || ""
      )
        .trim()
        .toLowerCase();

    const type =
      String(
        element.getAttribute?.(
          "type"
        )
        || ""
      )
        .trim()
        .toLowerCase();

    if (role === "tab") {
      return "TAB";
    }

    if (
      tag === "a"
      || role === "link"
      || role === "menuitem"
    ) {
      return "LINK";
    }

    if (
      (
        tag === "button"
        || tag === "input"
      )
      && type === "submit"
    ) {
      return "SUBMIT";
    }

    if (
      tag === "button"
      || role === "button"
      || (
        tag === "input"
        && [
          "button",
          "reset",
          "image"
        ].includes(
          type
        )
      )
    ) {
      return "BUTTON";
    }

    return null;
  }


  function composedActionSurfaceOf(
    host
  ) {
    if (
      !host
      || !host.shadowRoot
    ) {
      return null;
    }

    const visitedRoots =
      new Set();

    const surfaces = [];


    function walk(
      root,
      depth
    ) {
      if (
        !root
        || visitedRoots.has(
          root
        )
        || depth > 12
      ) {
        return;
      }

      visitedRoots.add(
        root
      );

      let nodes = [];

      try {
        nodes =
          Array.from(
            root.querySelectorAll(
              "*"
            )
          );
      } catch (_) {
        return;
      }


      for (
        const node
        of nodes
      ) {
        const kind =
          qccComposedActionKindOf(
            node
          );

        if (kind) {
          surfaces.push({
            kind:
              kind,

            leaf_tag:
              String(
                node.tagName
                || ""
              )
                .trim()
                .toLowerCase(),

            leaf_role:
              String(
                node.getAttribute?.(
                  "role"
                )
                || ""
              )
                .trim()
                .toLowerCase(),

            shadow_depth:
              depth
          });
        }

        try {
          if (
            node.shadowRoot
          ) {
            walk(
              node.shadowRoot,
              depth + 1
            );
          }
        } catch (_) {
          // Open-shadow traversal fail-open.
        }
      }
    }


    walk(
      host.shadowRoot,
      1
    );


    /*
     * Exactamente una superficie.
     *
     * 0 = no conocemos acción.
     * >1 = causalidad ambigua.
     */
    if (
      surfaces.length !== 1
    ) {
      return null;
    }

    return {
      locator_basis:
        "COMPOSED_PATH_HOST",

      kind:
        surfaces[0].kind,

      leaf_tag:
        surfaces[0].leaf_tag,

      leaf_role:
        surfaces[0].leaf_role,

      shadow_depth:
        surfaces[0].shadow_depth
    };
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
            ),

          composed_action_surface:
            composedActionSurfaceOf(
              element
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
        shadowRoots.length,

      shadow_adopted_stylesheets:
        shadowAdoptedStyleSheetCatalog.length
    },

    catalog_probe:
      captureCatalogProbe(),

    elements:
      inventory,

    shadow_adopted_stylesheets:
      shadowAdoptedStyleSheetCatalog,

    shadow_roots:
      shadowRoots
  };
}



/*
 * QCC_GENERIC_ACTIVE_NORMAL_WEB_TAB_V1
 *
 * Resuelve la pestaña activa de la última ventana
 * Chrome de tipo "normal".
 *
 * DevTools / Side Panel pueden ser la superficie
 * enfocada, por lo que NO usamos lastFocusedWindow
 * en chrome.tabs.query().
 *
 * Si Chrome no expone tab.url, obtenemos location.href
 * de forma PASIVA mediante scripting en el main frame.
 *
 * No hace click.
 * No navega.
 * No muta DOM.
 */
async function qccResolveActiveNormalWebTab() {
  const browserWindow =
    await chrome.windows.getLastFocused({
      populate:
        true,

      windowTypes: [
        "normal"
      ]
    });


  if (
    !browserWindow
    || browserWindow.type
      !== "normal"
  ) {
    throw new Error(
      "QCC_ACTIVE_NORMAL_WINDOW_NOT_FOUND"
    );
  }


  const tab =
    (
      Array.isArray(
        browserWindow.tabs
      )
      ? browserWindow.tabs.find(
          (candidate) =>
            candidate?.active === true
        )
      : null
    );


  if (
    !tab
    || !Number.isInteger(
      tab.id
    )
  ) {
    throw new Error(
      "QCC_ACTIVE_NORMAL_TAB_NOT_FOUND"
    );
  }


  let url =
    String(
      tab.url
      || tab.pendingUrl
      || ""
    ).trim();


  if (!url) {
    let probe;

    try {
      probe =
        await chrome.scripting.executeScript({
          target: {
            tabId:
              tab.id,

            frameIds:
              [0]
          },

          world:
            "ISOLATED",

          func:
            () => ({
              href:
                String(
                  globalThis.location?.href
                  || ""
                ),

              ready_state:
                String(
                  globalThis.document
                    ?.readyState
                  || ""
                )
            })
        });

    } catch (_) {
      throw new Error(
        "QCC_ACTIVE_NORMAL_WEB_TAB_URL_UNAVAILABLE"
      );
    }


    url =
      String(
        probe?.[0]?.result?.href
        || ""
      ).trim();
  }


  if (!url) {
    throw new Error(
      "QCC_ACTIVE_NORMAL_WEB_TAB_URL_UNAVAILABLE"
    );
  }


  let parsed;

  try {
    parsed =
      new URL(
        url
      );

  } catch (_) {
    throw new Error(
      "QCC_ACTIVE_NORMAL_WEB_TAB_URL_INVALID"
    );
  }


  if (
    parsed.protocol !== "http:"
    && parsed.protocol !== "https:"
  ) {
    throw new Error(
      "QCC_ACTIVE_NORMAL_WEB_TAB_PROTOCOL_REJECTED"
    );
  }


  return {
    ...tab,

    url:
      url
  };
}


async function inspectActiveTabDom() {
  const tab =
    await qccResolveActiveNormalWebTab();


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



/*
 * ============================================================
 * QCC_GENERIC_CATALOG_CAUSAL_EXECUTOR_V1
 * ============================================================
 *
 * Executor provider-neutral para aprendizaje causal
 * entre catálogos.
 *
 * Seguridad REAL:
 *
 *   HARVEST_ALLOWED
 *          +
 *   Bridge active_catalog_probe == true
 *          ↓
 *       mutación
 *
 * La restauración pertenece a la misma operación autorizada
 * y se ejecuta en finally incluso si la policy cambia después.
 *
 * Soporta:
 * - native_select;
 * - custom_select con open Shadow DOM;
 * - identidad RAW cuando existe;
 * - identidad semántica por label cuando RAW no existe;
 * - restauración a selección previa;
 * - restauración de custom select vacío mediante un único
 *   control ARIA de limpieza.
 *
 * No:
 * - submit;
 * - navegación;
 * - lógica específica de proveedor.
 */


const QCC_AUTO_TWIN_CATALOG_PROBE_DECISION_URL =
  (
    QCC_HUMAN_ACTION_BRIDGE_BASE_URL
    + "/qcc/auto-twin/catalog-probe-decision"
  );


const QCC_GENERIC_CATALOG_PROBE_TIMEOUT_MS =
  2500;


function qccGenericCatalogPageSetSelection(
  selector,
  requestedValue,
  requestedLabel
) {
  const clean =
    (value) =>
      String(
        value
        ?? ""
      )
        .replace(
          /\s+/g,
          " "
        )
        .trim();


  const scalarValue =
    (element) => {
      if (!element) {
        return "";
      }

      try {
        if (
          element.value !== undefined
          && element.value !== null
          && typeof element.value
            !== "object"
        ) {
          const value =
            clean(
              element.value
            );

          if (value) {
            return value;
          }
        }
      } catch (_) {
        // Continue.
      }

      try {
        const attr =
          clean(
            element.getAttribute(
              "value"
            )
          );

        if (attr) {
          return attr;
        }
      } catch (_) {
        // Continue.
      }

      try {
        const hidden =
          element.querySelector(
            'input[slot="hidden"],input[type="hidden"]'
          );

        if (hidden) {
          return clean(
            hidden.value
            ?? hidden.getAttribute(
              "value"
            )
          );
        }
      } catch (_) {
        // Continue.
      }

      return "";
    };


  const customLabel =
    (
      element,
      combobox
    ) => {
      const candidates = [
        combobox,
        element
      ];

      for (
        const candidate
        of candidates
      ) {
        if (!candidate) {
          continue;
        }

        try {
          if (
            candidate.value !== undefined
            && candidate.value !== null
            && typeof candidate.value
              !== "object"
          ) {
            const value =
              clean(
                candidate.value
              );

            if (value) {
              return value;
            }
          }
        } catch (_) {
          // Continue.
        }

        try {
          const value =
            clean(
              candidate.getAttribute(
                "value"
              )
            );

          if (value) {
            return value;
          }
        } catch (_) {
          // Continue.
        }
      }

      return "";
    };


  const normalizedSelector =
    clean(
      selector
    );

  const wantedValue =
    clean(
      requestedValue
    );

  const wantedLabel =
    clean(
      requestedLabel
    );


  if (!normalizedSelector) {
    throw new Error(
      "QCC_GENERIC_CATALOG_SELECTOR_REQUIRED"
    );
  }

  if (
    !wantedValue
    && !wantedLabel
  ) {
    throw new Error(
      "QCC_GENERIC_CATALOG_IDENTITY_REQUIRED"
    );
  }


  const element =
    document.querySelector(
      normalizedSelector
    );

  if (!element) {
    throw new Error(
      "QCC_GENERIC_CATALOG_NOT_FOUND"
    );
  }


  /*
   * ----------------------------------------------------------
   * Native <select>
   * ----------------------------------------------------------
   */
  if (
    String(
      element.tagName
      || ""
    ).toUpperCase()
      === "SELECT"
  ) {
    if (element.disabled) {
      throw new Error(
        "QCC_GENERIC_CATALOG_DISABLED"
      );
    }

    if (element.multiple) {
      throw new Error(
        "QCC_GENERIC_CATALOG_MULTIPLE_UNSUPPORTED"
      );
    }

    const options =
      Array.from(
        element.options
        || []
      );

    const originalOption =
      options[
        element.selectedIndex
      ]
      || null;

    const originalValue =
      clean(
        element.value
      );

    const originalLabel =
      clean(
        originalOption?.label
        || originalOption?.textContent
      );

    let target = null;

    if (wantedValue) {
      target =
        options.find(
          (option) => (
            option.disabled !== true
            && clean(
              option.value
            ) === wantedValue
          )
        )
        || null;
    }

    if (
      !target
      && wantedLabel
    ) {
      target =
        options.find(
          (option) => (
            option.disabled !== true
            && clean(
              option.label
              || option.textContent
            ) === wantedLabel
          )
        )
        || null;
    }

    if (!target) {
      throw new Error(
        "QCC_GENERIC_CATALOG_OPTION_NOT_FOUND"
      );
    }

    element.value =
      String(
        target.value
        ?? ""
      );

    element.dispatchEvent(
      new Event(
        "input",
        {
          bubbles: true
        }
      )
    );

    element.dispatchEvent(
      new Event(
        "change",
        {
          bubbles: true
        }
      )
    );

    return {
      catalog_type:
        "native_select",

      selector:
        normalizedSelector,

      original_value:
        originalValue,

      original_label:
        originalLabel,

      requested_value:
        wantedValue,

      requested_label:
        wantedLabel,

      test_value:
        clean(
          target.value
        ),

      test_label:
        clean(
          target.label
          || target.textContent
        ),

      interaction:
        "VALUE_CHANGE"
    };
  }


  /*
   * ----------------------------------------------------------
   * Open-shadow custom select
   * ----------------------------------------------------------
   */
  const shadowRoot =
    element.shadowRoot;

  if (!shadowRoot) {
    throw new Error(
      "QCC_GENERIC_CUSTOM_CATALOG_SHADOW_REQUIRED"
    );
  }

  const combobox =
    (
      shadowRoot.querySelector(
        '[role="combobox"][aria-haspopup="listbox"]'
      )
      || shadowRoot.querySelector(
        '[role="combobox"]'
      )
    );

  if (!combobox) {
    throw new Error(
      "QCC_GENERIC_CUSTOM_CATALOG_COMBOBOX_REQUIRED"
    );
  }

  if (
    element.disabled === true
    || element.hasAttribute(
      "disabled"
    )
    || combobox.getAttribute(
      "aria-disabled"
    ) === "true"
  ) {
    throw new Error(
      "QCC_GENERIC_CATALOG_DISABLED"
    );
  }


  const originalValue =
    scalarValue(
      element
    );

  const originalLabel =
    customLabel(
      element,
      combobox
    );


  const options = [];

  for (
    const optionHost
    of Array.from(
      element.children
      || []
    )
  ) {
    let surface = null;

    try {
      surface =
        optionHost.shadowRoot
          ?.querySelector(
            '[role="option"]'
          )
        || null;
    } catch (_) {
      surface = null;
    }

    if (!surface) {
      continue;
    }

    const value =
      scalarValue(
        optionHost
      );

    const label =
      clean(
        surface.textContent
        || optionHost.textContent
      );

    const disabled =
      (
        optionHost.disabled === true
        || optionHost.hasAttribute(
          "disabled"
        )
        || surface.getAttribute(
          "aria-disabled"
        ) === "true"
      );

    options.push({
      host:
        optionHost,

      surface,

      value,

      label,

      disabled
    });
  }


  let target = null;

  if (wantedValue) {
    target =
      options.find(
        (option) => (
          !option.disabled
          && option.value
            === wantedValue
        )
      )
      || null;
  }

  /*
   * Los Web Components pueden no exponer RAW en cada option.
   * En ese caso la identidad observada estable es el label.
   */
  if (
    !target
    && wantedLabel
  ) {
    target =
      options.find(
        (option) => (
          !option.disabled
          && option.label
            === wantedLabel
        )
      )
      || null;
  }

  if (!target) {
    throw new Error(
      "QCC_GENERIC_CUSTOM_CATALOG_OPTION_NOT_FOUND"
    );
  }


  /*
   * Interacción física del componente:
   * abrimos el combobox y accionamos su option ARIA.
   *
   * No generamos códigos RAW.
   */
  combobox.click();

  target.surface.click();


  return {
    catalog_type:
      "custom_select",

    selector:
      normalizedSelector,

    original_value:
      originalValue,

    original_label:
      originalLabel,

    requested_value:
      wantedValue,

    requested_label:
      wantedLabel,

    test_value:
      target.value,

    test_label:
      target.label,

    interaction:
      "ARIA_OPTION_CLICK"
  };
}


function qccGenericCatalogPageRestoreSelection(
  selector,
  originalValue,
  originalLabel
) {
  const clean =
    (value) =>
      String(
        value
        ?? ""
      )
        .replace(
          /\s+/g,
          " "
        )
        .trim();


  const scalarValue =
    (element) => {
      if (!element) {
        return "";
      }

      try {
        if (
          element.value !== undefined
          && element.value !== null
          && typeof element.value
            !== "object"
        ) {
          const value =
            clean(
              element.value
            );

          if (value) {
            return value;
          }
        }
      } catch (_) {
        // Continue.
      }

      try {
        const hidden =
          element.querySelector(
            'input[slot="hidden"],input[type="hidden"]'
          );

        if (hidden) {
          return clean(
            hidden.value
            ?? hidden.getAttribute(
              "value"
            )
          );
        }
      } catch (_) {
        // Continue.
      }

      return "";
    };


  const selectedLabel =
    (
      element,
      combobox
    ) => {
      for (
        const candidate
        of [
          combobox,
          element
        ]
      ) {
        if (!candidate) {
          continue;
        }

        try {
          const value =
            clean(
              candidate.value
            );

          if (value) {
            return value;
          }
        } catch (_) {
          // Continue.
        }

        try {
          const value =
            clean(
              candidate.getAttribute(
                "value"
              )
            );

          if (value) {
            return value;
          }
        } catch (_) {
          // Continue.
        }
      }

      return "";
    };


  const normalizedSelector =
    clean(
      selector
    );

  const expectedValue =
    clean(
      originalValue
    );

  const expectedLabel =
    clean(
      originalLabel
    );


  const element =
    document.querySelector(
      normalizedSelector
    );

  if (!element) {
    throw new Error(
      "QCC_GENERIC_CATALOG_RESTORE_NOT_FOUND"
    );
  }


  /*
   * Native.
   */
  if (
    String(
      element.tagName
      || ""
    ).toUpperCase()
      === "SELECT"
  ) {
    const options =
      Array.from(
        element.options
        || []
      );

    let target = null;

    if (
      expectedValue
      || expectedValue === ""
    ) {
      target =
        options.find(
          (option) => (
            clean(
              option.value
            ) === expectedValue
          )
        )
        || null;
    }

    if (
      !target
      && expectedLabel
    ) {
      target =
        options.find(
          (option) => (
            clean(
              option.label
              || option.textContent
            ) === expectedLabel
          )
        )
        || null;
    }

    if (!target) {
      throw new Error(
        "QCC_GENERIC_CATALOG_RESTORE_OPTION_NOT_FOUND"
      );
    }

    element.value =
      String(
        target.value
        ?? ""
      );

    element.dispatchEvent(
      new Event(
        "input",
        {
          bubbles: true
        }
      )
    );

    element.dispatchEvent(
      new Event(
        "change",
        {
          bubbles: true
        }
      )
    );

    return {
      catalog_type:
        "native_select",

      selector:
        normalizedSelector,

      restoration_method:
        "VALUE_CHANGE"
    };
  }


  /*
   * Custom.
   */
  const shadowRoot =
    element.shadowRoot;

  const combobox =
    (
      shadowRoot
        ?.querySelector(
          '[role="combobox"][aria-haspopup="listbox"]'
        )
      || shadowRoot
        ?.querySelector(
          '[role="combobox"]'
        )
      || null
    );

  if (!combobox) {
    throw new Error(
      "QCC_GENERIC_CUSTOM_RESTORE_COMBOBOX_REQUIRED"
    );
  }


  const currentValue =
    scalarValue(
      element
    );

  const currentLabel =
    selectedLabel(
      element,
      combobox
    );


  /*
   * Restauración del estado vacío.
   *
   * No conocemos nombres de proveedor ni idioma.
   * Exigimos exactamente un control ARIA de limpieza
   * dentro del combobox.
   */
  if (
    !expectedValue
    && !expectedLabel
  ) {
    if (
      !currentValue
      && !currentLabel
    ) {
      return {
        catalog_type:
          "custom_select",

        selector:
          normalizedSelector,

        restoration_method:
          "ALREADY_EMPTY"
      };
    }

    const clearControls =
      Array.from(
        combobox.querySelectorAll(
          '[role="button"][aria-label]'
        )
      );

    if (
      clearControls.length
      !== 1
    ) {
      throw new Error(
        "QCC_GENERIC_CUSTOM_RESTORE_CLEAR_CONTROL_AMBIGUOUS"
      );
    }

    clearControls[0].click();

    return {
      catalog_type:
        "custom_select",

      selector:
        normalizedSelector,

      restoration_method:
        "ARIA_CLEAR_CLICK"
    };
  }


  const options = [];

  for (
    const optionHost
    of Array.from(
      element.children
      || []
    )
  ) {
    const surface =
      optionHost.shadowRoot
        ?.querySelector(
          '[role="option"]'
        )
      || null;

    if (!surface) {
      continue;
    }

    options.push({
      surface,

      value:
        scalarValue(
          optionHost
        ),

      label:
        clean(
          surface.textContent
          || optionHost.textContent
        )
    });
  }


  let target = null;

  if (expectedValue) {
    target =
      options.find(
        (option) => (
          option.value
            === expectedValue
        )
      )
      || null;
  }

  if (
    !target
    && expectedLabel
  ) {
    target =
      options.find(
        (option) => (
          option.label
            === expectedLabel
        )
      )
      || null;
  }

  if (!target) {
    throw new Error(
      "QCC_GENERIC_CUSTOM_RESTORE_OPTION_NOT_FOUND"
    );
  }

  combobox.click();

  target.surface.click();

  return {
    catalog_type:
      "custom_select",

    selector:
      normalizedSelector,

    restoration_method:
      "ARIA_OPTION_CLICK"
  };
}


function qccGenericCatalogSelectionMatches(
  catalog,
  requestedValue,
  requestedLabel
) {
  if (!catalog) {
    return false;
  }

  const value =
    String(
      catalog.state
        ?.selected_value
      || ""
    ).trim();

  const label =
    String(
      catalog.state
        ?.selected_label
      || ""
    ).trim();

  const expectedValue =
    String(
      requestedValue
      || ""
    ).trim();

  const expectedLabel =
    String(
      requestedLabel
      || ""
    ).trim();


  if (expectedValue) {
    if (value === expectedValue) {
      return true;
    }

    /*
     * Option RAW puede ser inaccesible en custom_select.
     * Si también aportamos label, este conserva la identidad
     * semántica observada.
     */
    if (
      expectedLabel
      && label === expectedLabel
    ) {
      return true;
    }

    return false;
  }

  return (
    Boolean(
      expectedLabel
    )
    && label === expectedLabel
  );
}


async function qccGenericCatalogProbeAuthority(
  tab
) {
  if (
    !tab
    || !Number.isInteger(
      tab.id
    )
    || !tab.url
  ) {
    throw new Error(
      "QCC_GENERIC_CATALOG_ACTIVE_TAB_REQUIRED"
    );
  }


  const acquisition =
    globalThis
      .QccAcquisitionPolicy;

  if (
    !acquisition
    || typeof acquisition.resolve
      !== "function"
    || typeof acquisition.enableHarvestForUrl
      !== "function"
  ) {
    throw new Error(
      "QCC_GENERIC_CATALOG_ACQUISITION_POLICY_UNAVAILABLE"
    );
  }


  const identity =
    globalThis
      .QccBrowserIdentity;

  if (
    !identity
    || typeof identity.read
      !== "function"
  ) {
    throw new Error(
      "QCC_GENERIC_CATALOG_BROWSER_IDENTITY_UNAVAILABLE"
    );
  }


  const profileKey =
    String(
      await identity.read()
      || ""
    ).trim();

  if (!profileKey) {
    throw new Error(
      "QCC_GENERIC_CATALOG_PROFILE_UNBOUND"
    );
  }


  /*
   * ==========================================================
   * BACKEND AUTHORITY FIRST
   * ==========================================================
   *
   * El opt-in HARVEST nunca se autoeleva por conocer una URL.
   *
   * Primero el Bridge debe confirmar:
   * - browser profile registrado;
   * - managed AUTO TWIN;
   * - active_discovery;
   * - active_catalog_probe;
   * - URL dentro del TWIN gobernado.
   */
  const decisionUrl =
    new URL(
      QCC_AUTO_TWIN_CATALOG_PROBE_DECISION_URL
    );

  decisionUrl.searchParams.set(
    "browser_profile_key",
    profileKey
  );

  decisionUrl.searchParams.set(
    "url",
    String(
      tab.url
    )
  );


  const controller =
    new AbortController();

  const timeoutId =
    setTimeout(
      () => controller.abort(),
      QCC_GENERIC_CATALOG_PROBE_TIMEOUT_MS
    );


  let response;

  try {
    response =
      await fetch(
        decisionUrl.toString(),
        {
          method:
            "GET",

          cache:
            "no-store",

          signal:
            controller.signal
        }
      );

  } catch (_) {
    throw new Error(
      "QCC_GENERIC_CATALOG_PROBE_AUTHORITY_UNAVAILABLE"
    );

  } finally {
    clearTimeout(
      timeoutId
    );
  }


  if (!response.ok) {
    throw new Error(
      "QCC_GENERIC_CATALOG_PROBE_AUTHORITY_HTTP_"
      + String(
          response.status
        )
    );
  }


  const decision =
    await response.json();

  const profilePolicy =
    decision
      ?.profile_policy
    || {};


  if (
    !decision
    || decision.allowed !== true
    || profilePolicy
      ?.active_discovery !== true
    || profilePolicy
      ?.active_catalog_probe !== true
  ) {
    throw new Error(
      "QCC_GENERIC_CATALOG_PROBE_DENIED::"
      + String(
          decision?.reason
          || "POLICY_DENIED"
        )
    );
  }


  /*
   * ==========================================================
   * GOVERNED HARVEST BOOTSTRAP
   * ==========================================================
   *
   * AcquisitionPolicy sigue siendo un segundo gate.
   *
   * Si la extensión se recargó y perdió el opt-in efímero,
   * únicamente una decisión backend Discovery positiva puede
   * regenerarlo para esta origin durante esta sesión.
   *
   * enableHarvestForUrl() conserva además cualquier provider
   * lock SNAPSHOT_ONLY.
   */
  let acquisitionDecision =
    await acquisition.resolve(
      tab.url
    );


  if (
    acquisitionDecision?.mode
      !== acquisition.HARVEST_ALLOWED
    || acquisitionDecision?.allowed
      !== true
  ) {
    const bootstrap =
      await acquisition.enableHarvestForUrl(
        tab.url
      );


    if (
      bootstrap?.ok !== true
      || bootstrap?.enabled !== true
    ) {
      throw new Error(
        "QCC_GENERIC_CATALOG_GOVERNED_HARVEST_BOOTSTRAP_DENIED::"
        + String(
            bootstrap?.reason
            || "ACQUISITION_DENIED"
          )
      );
    }


    acquisitionDecision =
      bootstrap?.policy
      || await acquisition.resolve(
          tab.url
        );
  }


  /*
   * Defensa final:
   * incluso después del bootstrap exigimos el contrato normal
   * de AcquisitionPolicy.
   */
  if (
    acquisitionDecision?.mode
      !== acquisition.HARVEST_ALLOWED
    || acquisitionDecision?.allowed
      !== true
  ) {
    throw new Error(
      "QCC_GENERIC_CATALOG_HARVEST_NOT_ALLOWED"
    );
  }


  return {
    browser_profile_key:
      profileKey,

    acquisition:
      acquisitionDecision,

    auto_twin:
      decision
  };
}



/*
 * ============================================================
 * QCC_GENERIC_CATALOG_HARD_DOCUMENT_RESTORE_V1
 * ============================================================
 *
 * Restauración dura (recarga real de la pestaña) cuando la
 * restauración blanda en página no reproduce exactamente la
 * selección original del catálogo.
 *
 * Requiere que la política de Discovery siga vigente
 * (active_discovery + active_catalog_probe) sobre el MISMO
 * contexto físico: pestaña, URL, perfil y Twin. Cualquier
 * cambio de contexto aborta antes de tocar la pestaña.
 *
 * Usa chrome.tabs.reload, nunca location.reload/
 * window.location.reload, y espera document.readyState
 * "complete" antes de continuar.
 *
 * Provider-neutral: sin acoplar a ningún proveedor concreto.
 */


async function qccGenericCatalogHardRestoreAuthority(
  originalTab,
  initialAuthority
) {
  if (
    !originalTab
    || !Number.isInteger(
      originalTab.id
    )
    || !originalTab.url
  ) {
    throw new Error(
      "QCC_GENERIC_CATALOG_HARD_RESTORE_ORIGINAL_TAB_INVALID"
    );
  }


  const initialProfile =
    String(
      initialAuthority
        ?.browser_profile_key
      || ""
    ).trim();

  const initialTwin =
    String(
      initialAuthority
        ?.auto_twin
        ?.twin_key
      || ""
    ).trim();

  const initialPolicy =
    initialAuthority
      ?.auto_twin
      ?.profile_policy
    || {};


  if (
    !initialProfile
    || !initialTwin
    || initialAuthority
      ?.auto_twin
      ?.allowed !== true
    || initialPolicy
      ?.active_discovery !== true
    || initialPolicy
      ?.active_catalog_probe !== true
  ) {
    throw new Error(
      "QCC_GENERIC_CATALOG_HARD_RESTORE_INITIAL_AUTHORITY_DENIED"
    );
  }


  const currentTab =
    await qccResolveActiveNormalWebTab();


  if (
    currentTab.id
      !== originalTab.id
  ) {
    throw new Error(
      "QCC_GENERIC_CATALOG_HARD_RESTORE_TAB_CHANGED"
    );
  }


  if (
    String(
      currentTab.url
      || ""
    )
    !== String(
      originalTab.url
      || ""
    )
  ) {
    throw new Error(
      "QCC_GENERIC_CATALOG_HARD_RESTORE_URL_CHANGED"
    );
  }


  const identity =
    globalThis
      ?.QccBrowserIdentity;

  if (
    !identity
    || typeof identity.read
      !== "function"
  ) {
    throw new Error(
      "QCC_GENERIC_CATALOG_HARD_RESTORE_IDENTITY_UNAVAILABLE"
    );
  }


  const currentProfile =
    String(
      await identity.read()
      || ""
    ).trim();


  if (
    currentProfile
      !== initialProfile
  ) {
    throw new Error(
      "QCC_GENERIC_CATALOG_HARD_RESTORE_PROFILE_CHANGED"
    );
  }


  /*
   * Revalidamos directamente la autoridad backend.
   *
   * No exigimos nuevamente HARVEST_ALLOWED aquí:
   * la restauración es cleanup de una mutación que ya fue
   * autorizada y debe poder completarse incluso si el opt-in
   * fuese revocado mientras la operación estaba en curso.
   */
  const decisionUrl =
    new URL(
      QCC_AUTO_TWIN_CATALOG_PROBE_DECISION_URL
    );

  decisionUrl.searchParams.set(
    "browser_profile_key",
    currentProfile
  );

  decisionUrl.searchParams.set(
    "url",
    String(
      currentTab.url
    )
  );


  const controller =
    new AbortController();

  const timeoutId =
    setTimeout(
      () => controller.abort(),
      QCC_GENERIC_CATALOG_PROBE_TIMEOUT_MS
    );


  let response;

  try {
    response =
      await fetch(
        decisionUrl.toString(),
        {
          method:
            "GET",

          cache:
            "no-store",

          signal:
            controller.signal
        }
      );

  } catch (_) {
    throw new Error(
      "QCC_GENERIC_CATALOG_HARD_RESTORE_AUTHORITY_UNAVAILABLE"
    );

  } finally {
    clearTimeout(
      timeoutId
    );
  }


  if (!response.ok) {
    throw new Error(
      "QCC_GENERIC_CATALOG_HARD_RESTORE_AUTHORITY_HTTP_"
      + String(
          response.status
        )
    );
  }


  const decision =
    await response.json();

  const policy =
    decision
      ?.profile_policy
    || {};


  if (
    decision?.allowed !== true
    || policy
      ?.active_discovery !== true
    || policy
      ?.active_catalog_probe !== true
  ) {
    throw new Error(
      "QCC_GENERIC_CATALOG_HARD_RESTORE_POLICY_DENIED"
    );
  }


  if (
    String(
      decision?.twin_key
      || ""
    )
    !== initialTwin
  ) {
    throw new Error(
      "QCC_GENERIC_CATALOG_HARD_RESTORE_TWIN_CHANGED"
    );
  }


  return {
    tab:
      currentTab,

    browser_profile_key:
      currentProfile,

    twin_key:
      initialTwin,

    decision:
      decision
  };
}


async function qccGenericCatalogHardDocumentRestore(
  originalTab,
  initialAuthority
) {
  const authority =
    await qccGenericCatalogHardRestoreAuthority(
      originalTab,
      initialAuthority
    );


  await chrome.tabs.reload(
    authority.tab.id
  );


  /*
   * Dejamos que Chrome entre realmente en navegación antes
   * de empezar a observar status=complete.
   */
  await waitForCatalogExperiment(
    500
  );


  let completed = false;

  for (
    let attempt = 0;
    attempt < 40;
    attempt += 1
  ) {
    let current;

    try {
      current =
        await chrome.tabs.get(
          authority.tab.id
        );

    } catch (_) {
      current = null;
    }


    if (
      current
      && current.status
        === "complete"
    ) {
      completed = true;
      break;
    }


    await waitForCatalogExperiment(
      250
    );
  }


  if (!completed) {
    throw new Error(
      "QCC_GENERIC_CATALOG_HARD_RESTORE_DOCUMENT_TIMEOUT"
    );
  }


  /*
   * Espera corta adicional para que Web Components y
   * framework terminen su bootstrap tras load.
   */
  await waitForCatalogExperiment(
    700
  );


  const restoredTab =
    await qccResolveActiveNormalWebTab();


  if (
    restoredTab.id
      !== originalTab.id
  ) {
    throw new Error(
      "QCC_GENERIC_CATALOG_HARD_RESTORE_POST_TAB_CHANGED"
    );
  }


  if (
    String(
      restoredTab.url
      || ""
    )
    !== String(
      originalTab.url
      || ""
    )
  ) {
    throw new Error(
      "QCC_GENERIC_CATALOG_HARD_RESTORE_POST_URL_CHANGED"
    );
  }


  return {
    attempted:
      true,

    completed:
      true,

    method:
      "DOCUMENT_RELOAD",

    tab_id:
      restoredTab.id,

    url:
      restoredTab.url,

    browser_profile_key:
      authority.browser_profile_key,

    twin_key:
      authority.twin_key
  };
}


async function runGenericCatalogCausalProbe(
  sourceSelector,
  targetSelector,
  requestedValue = "",
  requestedLabel = "",
  expectedTabId = null,
  expectedUrl = ""
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
      "QCC_GENERIC_CATALOG_SOURCE_TARGET_SAME"
    );
  }


  const wantedValue =
    String(
      requestedValue
      || ""
    ).trim();

  const wantedLabel =
    String(
      requestedLabel
      || ""
    ).trim();

  if (
    !wantedValue
    && !wantedLabel
  ) {
    throw new Error(
      "QCC_GENERIC_CATALOG_IDENTITY_REQUIRED"
    );
  }


  const tab =
    await qccGenericHarvestActiveTab();


  /*
   * El scheduler automático puede originarse desde cualquier
   * evento Chrome. Antes de mutar exigimos que siga siendo
   * exactamente la pestaña/documento que produjo el plan.
   */
  if (
    expectedTabId !== null
    && Number.isInteger(
      Number(
        expectedTabId
      )
    )
    && tab.id
      !== Number(
        expectedTabId
      )
  ) {
    throw new Error(
      "QCC_GENERIC_CATALOG_EXPECTED_TAB_CHANGED"
    );
  }


  const normalizedExpectedUrl =
    String(
      expectedUrl
      || ""
    ).trim();


  if (
    normalizedExpectedUrl
    && String(
      tab.url
      || ""
    ) !== normalizedExpectedUrl
  ) {
    throw new Error(
      "QCC_GENERIC_CATALOG_EXPECTED_URL_CHANGED"
    );
  }


  /*
   * Doble gate ANTES de cualquier mutación.
   */
  const authority =
    await qccGenericCatalogProbeAuthority(
      tab
    );


  const before =
    await inspectActiveTabDom();

  const sourceBefore =
    catalogFromMainCapture(
      before,
      source
    );

  const targetBefore =
    catalogFromMainCapture(
      before,
      target
    );

  if (
    !sourceBefore
    || !targetBefore
  ) {
    throw new Error(
      "QCC_GENERIC_CATALOG_PAIR_NOT_FOUND"
    );
  }


  const supportedTypes =
    new Set([
      "native_select",
      "custom_select"
    ]);

  if (
    !supportedTypes.has(
      String(
        sourceBefore.catalog_type
        || ""
      )
    )
  ) {
    throw new Error(
      "QCC_GENERIC_CATALOG_TYPE_UNSUPPORTED"
    );
  }


  const originalValue =
    String(
      sourceBefore.state
        ?.selected_value
      || ""
    );

  const originalLabel =
    String(
      sourceBefore.state
        ?.selected_label
      || ""
    );

  const expectedTargetOptions =
    sanitizedCatalogOptions(
      targetBefore
    );

  let mutation = null;
  let observation = null;
  let restored = null;
  let restoration = null;
  let restorationVerification = null;
  let hardDocumentRestore = null;


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
          qccGenericCatalogPageSetSelection,

        args: [
          source,
          wantedValue,
          wantedLabel
        ]
      });

    mutation =
      mutationResults?.[0]?.result
      || null;

    if (!mutation) {
      throw new Error(
        "QCC_GENERIC_CATALOG_MUTATION_EMPTY"
      );
    }


    await waitForCatalogExperiment(
      700
    );


    let previousFingerprint = null;
    let stableObservations = 0;

    for (
      let attempt = 0;
      attempt < 12;
      attempt += 1
    ) {
      const capture =
        await inspectActiveTabDom();

      const sourceCurrent =
        catalogFromMainCapture(
          capture,
          source
        );

      const targetCurrent =
        catalogFromMainCapture(
          capture,
          target
        );

      if (
        !qccGenericCatalogSelectionMatches(
          sourceCurrent,
          wantedValue,
          wantedLabel
        )
      ) {
        previousFingerprint =
          null;

        stableObservations =
          0;

        await waitForCatalogExperiment(
          250
        );

        continue;
      }


      const fingerprint =
        catalogOptionsFingerprint(
          targetCurrent
        );

      if (
        previousFingerprint !== null
        && fingerprint
          === previousFingerprint
      ) {
        stableObservations += 1;

      } else {
        stableObservations = 0;
      }

      previousFingerprint =
        fingerprint;

      if (stableObservations >= 1) {
        observation = {
          capture,

          source: {
            selector:
              source,

            catalog_type:
              sourceCurrent
                ?.catalog_type
              || null,

            selected_value:
              String(
                sourceCurrent
                  ?.state
                  ?.selected_value
                || ""
              ),

            selected_label:
              String(
                sourceCurrent
                  ?.state
                  ?.selected_label
                || ""
              )
          },

          target: {
            selector:
              target,

            catalog_type:
              targetCurrent
                ?.catalog_type
              || null,

            options_count:
              Number(
                targetCurrent
                  ?.options
                  ?.length
                || 0
              ),

            options:
              sanitizedCatalogOptions(
                targetCurrent
              )
          },

          stabilization: {
            stable:
              true,

            attempts:
              attempt + 1
          }
        };

        break;
      }

      await waitForCatalogExperiment(
        250
      );
    }


    if (!observation) {
      throw new Error(
        "QCC_GENERIC_CATALOG_TARGET_NOT_STABLE"
      );
    }

  } finally {
    /*
     * IMPORTANTE:
     *
     * Si la mutación llegó a ejecutarse, la restauración
     * se intenta siempre. No exigimos un nuevo HARVEST gate
     * aquí porque podría dejar REAL mutado si el permiso
     * fuese revocado durante la operación.
     */
    if (mutation) {
      try {
        const restoreResults =
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
              qccGenericCatalogPageRestoreSelection,

            args: [
              source,
              originalValue,
              originalLabel
            ]
          });

        restoration =
          restoreResults?.[0]?.result
          || null;

      } catch (error) {
        /*
         * Una restauración local fallida NO puede dejar REAL
         * mutado. Conservamos el fallo como evidencia y dejamos
         * que la verificación posterior fuerce DOCUMENT_RELOAD.
         */
        restoration = {
          catalog_type:
            sourceBefore?.catalog_type
            || null,

          selector:
            source,

          restoration_method:
            "LOCAL_RESTORE_FAILED",

          local_restore_error:
            String(
              error?.message
              || error
              || "UNKNOWN"
            )
        };
      }


      await waitForCatalogExperiment(
        700
      );


      for (
        let attempt = 0;
        attempt < 16;
        attempt += 1
      ) {
        restored =
          await inspectActiveTabDom();

        restorationVerification =
          compareMainCatalogCaptures(
            before,
            restored
          );

        if (
          restorationVerification
            ?.exact === true
        ) {
          break;
        }

        await waitForCatalogExperiment(
          250
        );
      }


      /*
       * El componente puede restaurar su selección pero
       * conservar memoria dependiente dentro del documento.
       *
       * Solo entonces y solo bajo autoridad Discovery
       * ejecutamos HARD DOCUMENT RESTORE.
       */
      if (
        restorationVerification
          ?.exact !== true
      ) {
        hardDocumentRestore =
          await qccGenericCatalogHardDocumentRestore(
            tab,
            authority
          );


        /*
         * El reload crea un documento limpio. Aun así,
         * no declaramos éxito hasta comparar físicamente
         * el nuevo estado con BEFORE.
         */
        for (
          let attempt = 0;
          attempt < 16;
          attempt += 1
        ) {
          restored =
            await inspectActiveTabDom();

          restorationVerification =
            compareMainCatalogCaptures(
              before,
              restored
            );


          if (
            restorationVerification
              ?.exact === true
          ) {
            break;
          }


          await waitForCatalogExperiment(
            250
          );
        }
      }
    }
  }


  if (
    !restoration
    || !restorationVerification
    || restorationVerification.exact
      !== true
  ) {
    throw new Error(
      "QCC_GENERIC_CATALOG_EXACT_RESTORE_FAILED"
    );
  }


  return {
    ok:
      true,

    schema_version:
      1,

    artifact_type:
      "QCC_GENERIC_CATALOG_CAUSAL_PROBE",

    safety_mode:
      "GOVERNED_REAL_PROBE",

    source_selector:
      source,

    target_selector:
      target,

    requested_value:
      wantedValue,

    requested_label:
      wantedLabel,

    authority:
      authority,

    before: {
      source_value:
        originalValue,

      source_label:
        originalLabel,

      target_options:
        expectedTargetOptions
    },

    mutation:
      mutation,

    observation:
      observation,

    restoration:
      {
        ...restoration,

        hard_document_restore:
          hardDocumentRestore
      },

    restoration_verification:
      restorationVerification
  };
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
 * QCC_ARCHITECTURE_PROFILE_MODE_BOOTSTRAP_V1
 *
 * Solo se consulta el Browser Registry cuando el OWN profile
 * todavía no tiene default inicializado.
 *
 * Después del seed:
 * - MANUAL queda protegido;
 * - LEGACY queda protegido;
 * - MODE_* queda protegido;
 * - la captura automática ya depende únicamente
 *   de la policy persistida.
 *
 * Fallo de Bridge / inventario / modo:
 * - no inventa modo;
 * - no modifica policy;
 * - el gate posterior continúa fail-closed.
 */
const QCC_BROWSER_MODE_SEED_BROWSERS_URL =
  "http://127.0.0.1:8766/qcc/browsers";

const QCC_BROWSER_MODE_SEED_TIMEOUT_MS =
  1200;


async function qccSeedArchitectureProfileDefaultFromRegistry(
  profileKey,
  policy
) {
  if (
    !profileKey
    || !policy
    || typeof policy.snapshotForProfile
      !== "function"
    || typeof policy.seedProfileDefaultFromMode
      !== "function"
    || typeof policy.normalizeBrowserSessionMode
      !== "function"
  ) {
    return {
      seeded:
        false,

      reason:
        "MODE_SEED_RUNTIME_UNAVAILABLE"
    };
  }


  let snapshot;

  try {
    snapshot =
      await policy.snapshotForProfile(
        profileKey
      );

  } catch (_) {
    return {
      seeded:
        false,

      reason:
        "MODE_SEED_POLICY_READ_ERROR"
    };
  }


  if (
    snapshot?.storage_error
    === true
  ) {
    return {
      seeded:
        false,

      reason:
        "MODE_SEED_STORAGE_ERROR"
    };
  }


  if (
    snapshot?.default_initialized
    === true
  ) {
    return {
      seeded:
        false,

      reason:
        "MODE_SEED_ALREADY_INITIALIZED",

      default_source:
        snapshot?.default_source
        || null
    };
  }


  const controller =
    new AbortController();

  const timeoutId =
    setTimeout(
      () => controller.abort(),
      QCC_BROWSER_MODE_SEED_TIMEOUT_MS
    );


  try {
    const response =
      await fetch(
        QCC_BROWSER_MODE_SEED_BROWSERS_URL,
        {
          method:
            "GET",

          cache:
            "no-store",

          signal:
            controller.signal
        }
      );


    if (!response.ok) {
      return {
        seeded:
          false,

        reason:
          `MODE_SEED_HTTP_${response.status}`
      };
    }


    const payload =
      await response.json();


    if (
      !payload
      || payload.protocol_version !== 1
      || !Array.isArray(
          payload.browsers
        )
    ) {
      return {
        seeded:
          false,

        reason:
          "MODE_SEED_RESPONSE_INVALID"
      };
    }


    const normalizedProfile =
      String(
        profileKey
        || ""
      ).trim();


    const ownBrowser =
      payload.browsers.find(
        (item) =>
          String(
            item?.browser_profile_key
            || ""
          ).trim()
          === normalizedProfile
      );


    if (!ownBrowser) {
      return {
        seeded:
          false,

        reason:
          "MODE_SEED_PROFILE_NOT_REGISTERED"
      };
    }


    const mode =
      policy.normalizeBrowserSessionMode(
        ownBrowser
          ?.browser_session_mode
      );


    if (!mode) {
      return {
        seeded:
          false,

        reason:
          "MODE_SEED_SESSION_MODE_UNKNOWN"
      };
    }


    return await policy
      .seedProfileDefaultFromMode(
        normalizedProfile,
        mode
      );

  } catch (_) {
    return {
      seeded:
        false,

      reason:
        "MODE_SEED_BRIDGE_UNAVAILABLE"
    };

  } finally {
    clearTimeout(
      timeoutId
    );
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


  /*
   * ARCH-1E2:
   * bootstrap únicamente si este profile todavía
   * no tiene un default persistido/inicializado.
   *
   * El helper es fail-open respecto al runtime QCC,
   * pero el resolve posterior sigue siendo fail-closed.
   */
  await qccSeedArchitectureProfileDefaultFromRegistry(
    profileKey,
    policy
  );


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


    /*
     * Backend response belongs to this exact capture A.
     * Rearm against capture.frames/documentIds before
     * any later asynchronous phase.
     */
    await autoArmDiscoveryHumanListener(
      backendResult,
      normalizedTabId,
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
    /*
     * QCC_NEW_DOCUMENT_CAPTURE_RETRY_V1
     *
     * A navigation occurring while the previous document
     * is completing its capture must never be lost.
     */
    scheduleAutomaticSiteArchitectureCapture(
      normalizedTabId,
      "CAPTURE_RETRY_AFTER_IN_FLIGHT"
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
      /*
       * Site Architecture puede estar ya persistida mientras
       * Causal Discovery todavía no ha aprendido sus relaciones.
       *
       * El dedupe documental NO debe bloquear aprendizaje causal.
       */
      try {
        const causalDiscoveryResult =
          await runAutomaticCatalogCausalDiscovery(
            normalizedTabId,
            capture,
            trigger
          );

        console.log(
          "[QCC] Automatic Catalog Causal Discovery result:",
          causalDiscoveryResult
        );

      } catch (error) {
        console.debug(
          "[QCC] Automatic Catalog Causal Discovery dispatch skipped:",
          String(
            error?.message
            || error
          )
        );
      }


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
    /*
     * QCC_CAPTURE_HANDOFF_LOW_LATENCY_V1
     *
     * Start visual evidence immediately, but do NOT await it
     * before CURRENT projection + human listener arm.
     *
     * This preserves early visual acquisition while removing
     * viewport/MHTML latency from the human-listener gap.
     */
    const viewportPromise =
      qccCaptureAutomaticViewport(
        tab
      ).catch(
        (error) => {
          console.debug(
            "[QCC] Auto viewport skipped:",
            String(
              error?.message
              || error
            )
          );

          return null;
        }
      );


    const mhtmlPromise =
      (
        permissions.page_capture_granted
        === true
        ? qccCaptureAutomaticMhtml(
            normalizedTabId
          ).catch(
            (error) => {
              console.debug(
                "[QCC] Auto MHTML skipped:",
                String(
                  error?.message
                  || error
                )
              );

              return null;
            }
          )
        : Promise.resolve(
            null
          )
      );


    /*
     * Backend DOM/state projection is the critical path.
     * Human observation must be armed before waiting for
     * optional heavy artifacts.
     */
    const backendResult =
      await qccSubmitAutomaticDomCapture(
        capture
      );


    /*
     * Backend response belongs to this exact capture A.
     * Rearm against capture.frames/documentIds before
     * any later asynchronous phase.
     */
    await autoArmDiscoveryHumanListener(
      backendResult,
      normalizedTabId,
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
     * QCC_CAPTURE_HANDOFF_RELEASE_V1
     *
     * At this point:
     * - DOM/state is persisted by Bridge;
     * - CURRENT is projected;
     * - the exact document listener is armed.
     *
     * Remember the document BEFORE releasing the tab lock.
     * Everything after this point is optional/post-processing.
     */
    await qccRememberAutomaticCapture(
      normalizedTabId,
      documentId,
      capture.main_url,
      captureId,
      fingerprint
    );


    qccAutomaticCaptureInFlight.delete(
      normalizedTabId
    );


    const [
      viewportBlob,
      mhtmlBlob
    ] = await Promise.all([
      viewportPromise,
      mhtmlPromise
    ]);


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


    /*
     * Site Architecture ya está persistida.
     *
     * Causal Discovery es una fase posterior, independiente
     * y fail-open. Nunca bloquea ni invalida la captura.
     */
    try {
      const causalDiscoveryResult =
        await runAutomaticCatalogCausalDiscovery(
          normalizedTabId,
          capture,
          trigger
        );

      console.log(
        "[QCC] Automatic Catalog Causal Discovery result:",
        causalDiscoveryResult
      );

    } catch (error) {
      /*
       * Fail-open local:
       * Site Architecture ya está persistida.
       *
       * El fallo causal nunca invalida la captura,
       * pero tampoco se silencia.
       */
      console.debug(
        "[QCC] Automatic Catalog Causal Discovery dispatch skipped:",
        String(
          error?.message
          || error
        )
      );
    }


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



/*
 * ============================================================
 * QCC_AUTO_TWIN_AUTOMATIC_CATALOG_CAUSAL_DISCOVERY_V1
 * ============================================================
 *
 * Se ejecuta únicamente DESPUÉS de una captura automática
 * persistida correctamente.
 *
 * Fail-open:
 * nunca invalida Site Architecture.
 *
 * El planner propone.
 * El executor prueba físicamente.
 * El backend vuelve a autorizar y declara causalidad.
 */

const QCC_AUTO_TWIN_CATALOG_DEPENDENCY_PROBE_URL =
  (
    "http://127.0.0.1:8766"
    + "/qcc/auto-twin/catalog-dependency-probe"
  );


const qccAutomaticCatalogProbeInFlight =
  new Set();


const qccAutomaticCatalogProbeAttempted =
  new Set();


async function qccPersistGenericCatalogCausalProbe(
  artifact
) {
  const browserProfileKey =
    String(
      artifact
        ?.authority
        ?.browser_profile_key
      || ""
    ).trim();


  const pageUrl =
    String(
      artifact
        ?.authority
        ?.auto_twin
        ?.url
      || ""
    ).trim();


  if (
    !browserProfileKey
    || !pageUrl
  ) {
    throw new Error(
      "QCC_GENERIC_CATALOG_DEPENDENCY_TRANSPORT_CONTEXT_INVALID"
    );
  }


  /*
   * La versión de protocolo pertenece al contrato ya
   * autorizado por Bridge.
   *
   * No duplicamos una constante local en la extensión.
   */
  const protocolVersion =
    Number(
      artifact
        ?.authority
        ?.auto_twin
        ?.protocol_version
    );


  if (
    !Number.isInteger(
      protocolVersion
    )
    || protocolVersion <= 0
  ) {
    throw new Error(
      "QCC_GENERIC_CATALOG_DEPENDENCY_PROTOCOL_VERSION_INVALID"
    );
  }


  const controller =
    new AbortController();


  const timeoutId =
    setTimeout(
      () =>
        controller.abort(),
      QCC_GENERIC_CATALOG_PROBE_TIMEOUT_MS
    );


  let response;


  try {
    response =
      await fetch(
        QCC_AUTO_TWIN_CATALOG_DEPENDENCY_PROBE_URL,
        {
          method:
            "POST",

          headers: {
            "Content-Type":
              "application/json"
          },

          cache:
            "no-store",

          signal:
            controller.signal,

          body:
            JSON.stringify({
              protocol_version:
                protocolVersion,

              browser_profile_key:
                browserProfileKey,

              url:
                pageUrl,

              probe:
                artifact
            })
        }
      );

  } finally {
    clearTimeout(
      timeoutId
    );
  }


  const body =
    await response.json();


  if (!response.ok) {
    throw new Error(
      String(
        body?.error
        || (
          "QCC_GENERIC_CATALOG_DEPENDENCY_HTTP_"
          + response.status
        )
      )
    );
  }


  return body;
}


function qccAutomaticCatalogProbeKey(
  tab,
  plan
) {
  return [
    Number(
      tab?.id
    ),
    String(
      tab?.url
      || ""
    ),
    String(
      plan?.source_selector
      || ""
    ),
    String(
      plan?.target_selector
      || ""
    ),
    String(
      plan?.requested_value
      || ""
    ),
    String(
      plan?.requested_label
      || ""
    )
  ].join(
    "::"
  );
}


async function runAutomaticCatalogCausalDiscovery(
  tabId,
  capture,
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

      probed:
        false,

      reason:
        "TAB_INVALID"
    };
  }


  if (
    qccAutomaticCatalogProbeInFlight.has(
      normalizedTabId
    )
  ) {
    return {
      ok:
        true,

      probed:
        false,

      reason:
        "PROBE_ALREADY_IN_FLIGHT"
    };
  }


  const planner =
    globalThis
      .QccCatalogDependencyPlanner;


  if (
    !planner
    || typeof planner.planCapture
      !== "function"
  ) {
    return {
      ok:
        true,

      probed:
        false,

      reason:
        "PLANNER_UNAVAILABLE"
    };
  }


  const plans =
    planner.planCapture(
      capture,
      {
        /*
         * El planner puede enumerar todos los candidatos seguros.
         *
         * El runner selecciona posteriormente el primer candidato
         * todavía no intentado y ejecuta SOLO una mutación física
         * por ciclo.
         */
        max_plans:
          Number.MAX_SAFE_INTEGER
      }
    );


  if (
    !Array.isArray(
      plans
    )
    || plans.length === 0
  ) {
    return {
      ok:
        true,

      probed:
        false,

      reason:
        "NO_CAUSAL_CANDIDATE"
    };
  }


  qccAutomaticCatalogProbeInFlight.add(
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
    ) {
      return {
        ok:
          true,

        probed:
          false,

        reason:
          "TAB_NOT_STABLE"
      };
    }


    /*
     * runGenericCatalogCausalProbe opera exclusivamente
     * sobre la pestaña web activa.
     *
     * Nunca cambiamos de pestaña ni robamos foco.
     */
    const activeTab =
      await qccResolveActiveNormalWebTab();


    if (
      activeTab.id
        !== tab.id
      || String(
          activeTab.url
          || ""
        ) !== String(
          tab.url
          || ""
        )
    ) {
      return {
        ok:
          true,

        probed:
          false,

        reason:
          "TAB_NOT_ACTIVE_ANYMORE"
      };
    }


    const pendingPlan =
      plans
        .map(
          (plan) => ({
            plan,

            attemptKey:
              qccAutomaticCatalogProbeKey(
                tab,
                plan
              )
          })
        )
        .find(
          (entry) =>
            !qccAutomaticCatalogProbeAttempted.has(
              entry.attemptKey
            )
        );


    if (!pendingPlan) {
      return {
        ok:
          true,

        probed:
          false,

        reason:
          "ALL_CAUSAL_CANDIDATES_ATTEMPTED",

        candidate_count:
          plans.length
      };
    }


    const plan =
      pendingPlan.plan;


    const attemptKey =
      pendingPlan.attemptKey;


    /*
     * Marcamos ANTES de mutar para evitar loops producidos
     * por MutationObserver / hard document restore.
     */
    qccAutomaticCatalogProbeAttempted.add(
      attemptKey
    );


    if (
      qccAutomaticCatalogProbeAttempted.size
      > 500
    ) {
      qccAutomaticCatalogProbeAttempted.clear();

      qccAutomaticCatalogProbeAttempted.add(
        attemptKey
      );
    }


    const artifact =
      await runGenericCatalogCausalProbe(
        plan.source_selector,
        plan.target_selector,
        plan.requested_value,
        plan.requested_label,
        tab.id,
        String(
          tab.url
          || ""
        )
      );


    const beforeFingerprint =
      planner.optionsFingerprint(
        artifact
          ?.before
          ?.target_options
      );


    const afterFingerprint =
      planner.optionsFingerprint(
        artifact
          ?.observation
          ?.target
          ?.options
      );


    /*
     * El planner propone, pero no declara causalidad.
     *
     * Si el target no cambió no enviamos falsa evidencia
     * al Store.
     */
    if (
      beforeFingerprint
        === afterFingerprint
    ) {
      const targetUnchangedDiagnostic = {
        persisted:
          false,

        reason:
          "TARGET_UNCHANGED",

        source_selector:
          plan.source_selector,

        target_selector:
          plan.target_selector,

        requested_value:
          String(
            plan.requested_value
            || ""
          ),

        requested_label:
          String(
            plan.requested_label
            || ""
          ),

        before: {
          source_value:
            String(
              artifact
                ?.before
                ?.source_value
              || ""
            ),

          source_label:
            String(
              artifact
                ?.before
                ?.source_label
              || ""
            ),

          target_options_count:
            (
              Array.isArray(
                artifact
                  ?.before
                  ?.target_options
              )
              ? artifact
                  .before
                  .target_options
                  .length
              : 0
            )
        },

        mutation:
          artifact?.mutation
          || null,

        observation: {
          source:
            artifact
              ?.observation
              ?.source
            || null,

          target_options_count:
            Number(
              artifact
                ?.observation
                ?.target
                ?.options_count
              || 0
            ),

          stabilization:
            artifact
              ?.observation
              ?.stabilization
            || null
        },

        restoration_verification:
          artifact
            ?.restoration_verification
          || null
      };


      console.debug(
        "[QCC] Automatic Catalog Causal Discovery:",
        targetUnchangedDiagnostic
      );


      return {
        ok:
          true,

        probed:
          true,

        persisted:
          false,

        reason:
          "TARGET_UNCHANGED",

        diagnostic:
          targetUnchangedDiagnostic
      };
    }


    const persistence =
      await qccPersistGenericCatalogCausalProbe(
        artifact
      );


    console.log(
      "[QCC] Automatic Catalog Causal Discovery:",
      {
        persisted:
          true,

        trigger:
          String(
            trigger
            || ""
          ),

        source_selector:
          plan.source_selector,

        target_selector:
          plan.target_selector,

        persistence
      }
    );


    return {
      ok:
        true,

      probed:
        true,

      persisted:
        true,

      persistence
    };


  } catch (error) {
    /*
     * Fail-open absoluto.
     * Site Architecture ya está persistida.
     */
    console.debug(
      "[QCC] Automatic Catalog Causal Discovery skipped:",
      String(
        error?.message
        || error
      )
    );


    return {
      ok:
        true,

      probed:
        false,

      reason:
        String(
          error?.message
          || error
        )
    };


  } finally {
    qccAutomaticCatalogProbeInFlight.delete(
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
          .then(
            (result) => {
              try {
                port.postMessage({
                  type:
                    "QCC_HUMAN_DOM_ACTION_ACK",

                  ok:
                    true,

                  event_id:
                    (
                      result?.event_id
                      || null
                    )
                });

              } catch (_) {
                // Legacy document may already be gone.
              }
            }
          )
          .catch(
            (error) => {
              const errorText =
                String(
                  error?.message
                  || error
                  || "UNKNOWN"
                );


              try {
                port.postMessage({
                  type:
                    "QCC_HUMAN_DOM_ACTION_ACK",

                  ok:
                    false,

                  error:
                    errorText
                });

              } catch (_) {
                // No-op.
              }


              console.warn(
                "[QCC] Human DOM action port:",
                errorText
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
  try {
    return (
      await qccResolveActiveNormalWebTab()
    );

  } catch (error) {
    throw new Error(
      "QCC_GENERIC_DOM_HARVEST_ACTIVE_TAB_NOT_FOUND::"
      + String(
          error?.message
          || error
          || "UNKNOWN"
        )
    );
  }
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



/*
 * QCC_GENERIC_CATALOG_CAUSAL_PROBE_MESSAGE_V1
 *
 * Entrada programática única al executor causal.
 * La autoridad sigue residiendo dentro del Service Worker.
 */
chrome.runtime.onMessage.addListener(
  (
    message,
    _sender,
    sendResponse
  ) => {
    if (
      !message
      || message.type
        !== "QCC_GENERIC_CATALOG_CAUSAL_PROBE"
    ) {
      return false;
    }


    runGenericCatalogCausalProbe(
      message.source_selector,
      message.target_selector,
      message.requested_value,
      message.requested_label
    )
      .then(
        sendResponse
      )
      .catch(
        (error) => {
          sendResponse({
            ok:
              false,

            error:
              String(
                error?.message
                || error
                || "QCC_GENERIC_CATALOG_CAUSAL_PROBE_FAILED"
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
