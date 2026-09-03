const QCC_BRIDGE_BASE_URL =
  "http://127.0.0.1:8766";

const QCC_BRIDGE_HEALTH_URL =
  `${QCC_BRIDGE_BASE_URL}/qcc/health`;

const QCC_CONTEXT_URL =
  `${QCC_BRIDGE_BASE_URL}/qcc/context`;

const QCC_BROWSERS_URL =
  `${QCC_BRIDGE_BASE_URL}/qcc/browsers`;

const QCC_SITE_ARCHITECTURE_CAPTURE_URL =
  `${QCC_BRIDGE_BASE_URL}/qcc/site-architecture/capture`;

const QCC_CATALOG_EXPERIMENT_URL =
  `${QCC_BRIDGE_BASE_URL}`
  + "/qcc/site-architecture/catalog-experiment";

const QCC_HEALTH_INTERVAL_MS = 2000;
const QCC_REQUEST_TIMEOUT_MS = 1200;

const QCC_SITE_ARCHITECTURE_REQUEST_TIMEOUT_MS =
  30000;

/*
 * QCC_SIDEPANEL_MULTI_BROWSER_V1
 *
 * OWN:
 * identidad persistente del Chrome que contiene
 * este Side Panel.
 *
 * VIEWED:
 * navegador cuyo estado se está consultando.
 *
 * H2-B introduce el modelo.
 * H2-C separará definitivamente autoridad de acción.
 */
let qccOwnBrowserProfileKey = null;
let qccViewedBrowserProfileKey = null;

let qccOwnSessionId = null;
let qccViewedSessionId = null;

let qccKnownBrowsers = [];

const qccPendingActionIds =
  new Map();



function element(id) {
  return document.getElementById(id);
}


function setText(
  id,
  value
) {
  const target = element(id);

  if (target) {
    target.textContent = value;
  }
}


function normalizeLabel(value) {
  if (
    value === null ||
    value === undefined ||
    String(value).trim() === ""
  ) {
    return "—";
  }

  return String(value)
    .replaceAll("_", " ");
}


async function fetchJson(url) {
  const controller =
    new AbortController();

  const timeoutId =
    setTimeout(
      () => controller.abort(),
      QCC_REQUEST_TIMEOUT_MS
    );

  try {
    const response =
      await fetch(
        url,
        {
          method: "GET",
          cache: "no-store",
          signal: controller.signal
        }
      );

    if (!response.ok) {
      throw new Error(
        `HTTP_${response.status}`
      );
    }

    return await response.json();
  } finally {
    clearTimeout(timeoutId);
  }
}


async function postJson(
  url,
  payload,
  timeoutMs = QCC_REQUEST_TIMEOUT_MS
) {
  const controller =
    new AbortController();

  const timeoutId =
    setTimeout(
      () => controller.abort(),
      timeoutMs
    );

  try {
    const response =
      await fetch(
        url,
        {
          method: "POST",
          cache: "no-store",
          headers: {
            "Content-Type":
              "application/json"
          },
          body: JSON.stringify(
            payload
          ),
          signal: controller.signal
        }
      );

    const responsePayload =
      await response.json();

    if (!response.ok) {
      throw new Error(
        responsePayload?.error
        || `HTTP_${response.status}`
      );
    }

    return responsePayload;
  } finally {
    clearTimeout(timeoutId);
  }
}


/*
 * QCC_VISUAL_EVIDENCE_VIEWPORT_V1
 *
 * La evidencia visual se captura ANTES de enviar
 * la arquitectura al Bridge para minimizar drift
 * entre DOM/Geometry y screenshot.
 *
 * El PNG permanece fuera de qcc_capture.json.
 * Una vez el backend asigna capture_id, se adjunta
 * mediante el endpoint binario dedicado.
 */

const QCC_SITE_ARCHITECTURE_VISUAL_ARTIFACT_URL =
  QCC_SITE_ARCHITECTURE_CAPTURE_URL.replace(
    "/capture",
    "/visual-artifact"
  );


async function captureActiveViewportScreenshot(
  domCapture
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
    || !Number.isInteger(tab.windowId)
  ) {
    throw new Error(
      "QCC_VISUAL_ACTIVE_TAB_NOT_FOUND"
    );
  }


  const expectedTabId =
    Number(
      domCapture?.tab_id
    );

  if (
    Number.isInteger(expectedTabId)
    && expectedTabId !== tab.id
  ) {
    throw new Error(
      "QCC_VISUAL_ACTIVE_TAB_CHANGED"
    );
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
    throw new Error(
      "QCC_VISUAL_VIEWPORT_CAPTURE_INVALID"
    );
  }


  const response =
    await fetch(
      dataUrl
    );

  if (!response.ok) {
    throw new Error(
      "QCC_VISUAL_VIEWPORT_DECODE_FAILED"
    );
  }


  const blob =
    await response.blob();

  if (
    !blob
    || blob.size <= 0
  ) {
    throw new Error(
      "QCC_VISUAL_VIEWPORT_EMPTY"
    );
  }


  return {
    kind:
      "viewport",

    captured_at:
      new Date()
        .toISOString(),

    tab_id:
      tab.id,

    window_id:
      tab.windowId,

    blob:
      blob
  };
}



/*
 * QCC_VISUAL_LOCAL_FALLBACK_V1
 *
 * Si Bridge/CRM no está disponible, la captura visual
 * sigue siendo recuperable por el usuario.
 *
 * No requiere chrome.downloads:
 * reutiliza el patrón de descarga local iniciado
 * desde el Side Panel.
 */
function downloadVisualEvidence(
  visualEvidence,
  domDownload
) {
  if (
    !visualEvidence
    || visualEvidence.kind !== "viewport"
    || !(visualEvidence.blob instanceof Blob)
  ) {
    throw new Error(
      "QCC_VISUAL_EVIDENCE_NOT_AVAILABLE"
    );
  }


  const domFilename =
    String(
      domDownload?.filename
      || ""
    );


  let filename =
    (
      "qcc_site_architecture_"
      + new Date()
          .toISOString()
          .replace(
            /[:.]/g,
            "-"
          )
      + ".viewport.png"
    );


  if (
    domFilename
    && domFilename.endsWith(".json")
  ) {
    filename =
      (
        domFilename.slice(
          0,
          -5
        )
        + ".viewport.png"
      );
  }


  const objectUrl =
    URL.createObjectURL(
      visualEvidence.blob
    );

  const anchor =
    document.createElement(
      "a"
    );

  anchor.href =
    objectUrl;

  anchor.download =
    filename;

  anchor.style.display =
    "none";

  document.body.appendChild(
    anchor
  );

  anchor.click();
  anchor.remove();


  setTimeout(
    () => {
      URL.revokeObjectURL(
        objectUrl
      );
    },
    1000
  );


  return {
    ok: true,
    filename,
    bytes:
      visualEvidence.blob.size,
  };
}


async function submitVisualArtifact(
  captureId,
  visualEvidence
) {
  const normalizedCaptureId =
    String(
      captureId
      || ""
    ).trim();

  const kind =
    String(
      visualEvidence?.kind
      || ""
    ).trim();

  const blob =
    visualEvidence?.blob;


  if (!normalizedCaptureId) {
    throw new Error(
      "QCC_VISUAL_CAPTURE_ID_REQUIRED"
    );
  }

  if (!kind) {
    throw new Error(
      "QCC_VISUAL_KIND_REQUIRED"
    );
  }

  if (
    !blob
    || typeof blob.size !== "number"
    || blob.size <= 0
  ) {
    throw new Error(
      "QCC_VISUAL_BLOB_INVALID"
    );
  }


  const controller =
    new AbortController();

  const timeoutId =
    setTimeout(
      () => {
        controller.abort();
      },
      QCC_SITE_ARCHITECTURE_REQUEST_TIMEOUT_MS
    );


  try {
    const response =
      await fetch(
        QCC_SITE_ARCHITECTURE_VISUAL_ARTIFACT_URL,
        {
          method:
            "POST",

          cache:
            "no-store",

          headers: {
            "Content-Type":
              "image/png",

            "X-QCC-Protocol-Version":
              "1",

            "X-QCC-Capture-Id":
              normalizedCaptureId,

            "X-QCC-Visual-Kind":
              kind
          },

          body:
            blob,

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


    if (!response.ok) {
      throw new Error(
        payload?.error
        || (
          "QCC_VISUAL_ARTIFACT_HTTP_"
          + String(
              response.status
            )
        )
      );
    }


    if (
      !payload
      || payload.ok !== true
    ) {
      throw new Error(
        "QCC_VISUAL_ARTIFACT_RESPONSE_INVALID"
      );
    }


    return payload;

  } finally {
    clearTimeout(
      timeoutId
    );
  }
}


async function submitSiteArchitectureCapture(
  capture
) {
  const browserProfileKey =
    await globalThis
      .QccBrowserIdentity
      .read();

  return await postJson(
    QCC_SITE_ARCHITECTURE_CAPTURE_URL,
    {
      protocol_version: 1,

      browser_profile_key:
        browserProfileKey,

      capture
    },
    QCC_SITE_ARCHITECTURE_REQUEST_TIMEOUT_MS
  );
}


async function armHumanListenerFromCapture(
  capture,
  backendResult
) {
  const plan =
    backendResult?.human_listener_plan;

  const sessionId =
    String(
      backendResult?.session_id
      || ""
    ).trim();

  const tabId =
    Number(
      capture?.tab_id
    );

  const targets =
    (
      Array.isArray(
        plan?.targets
      )
      ? plan.targets
      : []
    );


  if (
    !sessionId
    || !Number.isInteger(
      tabId
    )
    || targets.length === 0
  ) {
    return null;
  }


  /*
   * Browser routing metadata procedente
   * exactamente de capture A.
   *
   * document_id no se usa como identidad
   * semántica de la acción y no se envía
   * al Bridge human-dom-action.
   */
  const frameDocuments =
    (
      capture?.frames
      || []
    )
      .map(
        (frame) => ({
          frame_id:
            Number(
              frame?.frame_id
            ),

          document_id:
            String(
              frame?.document_id
              || ""
            ).trim()
        })
      )
      .filter(
        (frame) => (
          Number.isInteger(
            frame.frame_id
          )
          && Boolean(
            frame.document_id
          )
        )
      );


  return await chrome.runtime.sendMessage({
    type:
      "QCC_ARM_HUMAN_LISTENER",

    session_id:
      sessionId,

    tab_id:
      tabId,

    targets:
      targets,

    frame_documents:
      frameDocuments
  });
}


async function submitCatalogExperiment(
  experiment
) {
  return await postJson(
    QCC_CATALOG_EXPERIMENT_URL,
    {
      protocol_version:
        1,

      experiment:
        experiment
    },
    QCC_SITE_ARCHITECTURE_REQUEST_TIMEOUT_MS
  );
}


function buildActionIdentityKey(
  sessionId,
  action,
  payload = {}
) {
  const documentIndex =
    payload?.document_index ?? "";

  const value =
    payload?.value ?? "";

  return (
    `${sessionId}:${action}:`
    + `${documentIndex}:${value}`
  );
}


function getClientActionId(
  sessionId,
  action,
  payload = {}
) {
  const key =
    buildActionIdentityKey(
      sessionId,
      action,
      payload
    );

  let clientActionId =
    qccPendingActionIds.get(
      key
    );

  if (!clientActionId) {
    clientActionId =
      crypto.randomUUID();

    qccPendingActionIds.set(
      key,
      clientActionId
    );
  }

  return clientActionId;
}


async function submitSessionAction(
  action,
  payload = {}
) {
  const sessionId =
    qccOwnSessionId;

  /*
   * Autoridad operativa = OWN.
   *
   * Una sesión VIEWED remota nunca puede
   * provocar una acción, ni siquiera si
   * un control apareciera por error.
   */
  if (
    !qccIsOwnBrowserView()
    || !sessionId
    || qccViewedSessionId
      !== sessionId
  ) {
    throw new Error(
      "QCC_REMOTE_VIEW_READ_ONLY"
    );
  }

  const clientActionId =
    getClientActionId(
      sessionId,
      action,
      payload
    );

  const url =
    (
      `${QCC_BRIDGE_BASE_URL}`
      + `/qcc/session/${encodeURIComponent(sessionId)}`
      + "/action"
    );

  return await postJson(
    url,
    {
      protocol_version: 1,
      client_action_id:
        clientActionId,
      action,
      payload
    }
  );
}


function setBridgeState(
  connected,
  description
) {
  const dot = element("bridge-dot");

  if (dot) {
    dot.classList.toggle(
      "qcc-status-dot--online",
      connected
    );

    dot.classList.toggle(
      "qcc-status-dot--offline",
      !connected
    );
  }

  setText(
    "bridge-status",
    connected
      ? "CRM conectado"
      : "CRM desconectado"
  );

  setText(
    "bridge-description",
    description
  );
}


function qccBrowserContextUrl(
  profileKey
) {
  return (
    QCC_CONTEXT_URL
    + "?browser_profile_key="
    + encodeURIComponent(
        String(
          profileKey
          || ""
        )
      )
  );
}


function qccIsOwnBrowserView() {
  return (
    Boolean(
      qccOwnBrowserProfileKey
    )
    && qccViewedBrowserProfileKey
      === qccOwnBrowserProfileKey
  );
}


function qccBrowserSummaryFor(
  profileKey
) {
  const normalized =
    String(
      profileKey
      || ""
    ).trim();

  return (
    qccKnownBrowsers.find(
      (item) =>
        String(
          item?.browser_profile_key
          || ""
        ).trim()
        === normalized
    )
    || null
  );
}


/*
 * QCC_ARCHITECTURE_OWN_PROFILE_MODE_SEED_V1
 *
 * El Side Panel puede reflejar el default correcto incluso
 * antes de que ocurra una captura automática.
 *
 * Autoridad:
 *   qccOwnBrowserProfileKey
 *
 * Nunca:
 * - qccViewedBrowserProfileKey;
 * - perfil remoto;
 * - heurística por nombre.
 */
async function qccSeedOwnArchitectureProfileDefault() {
  const profileKey =
    String(
      qccOwnBrowserProfileKey
      || ""
    ).trim();

  const policy =
    globalThis
      ?.QccArchitectureCapturePolicy;


  if (
    !profileKey
    || !policy
    || typeof policy.snapshotForProfile
      !== "function"
    || typeof policy.seedProfileDefaultFromMode
      !== "function"
  ) {
    return {
      seeded:
        false,

      reason:
        "OWN_MODE_SEED_RUNTIME_UNAVAILABLE"
    };
  }


  const snapshot =
    await policy.snapshotForProfile(
      profileKey
    );


  if (
    snapshot?.storage_error
    === true
  ) {
    return {
      seeded:
        false,

      reason:
        "OWN_MODE_SEED_STORAGE_ERROR"
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
        "OWN_MODE_SEED_ALREADY_INITIALIZED"
    };
  }


  const summary =
    qccBrowserSummaryFor(
      profileKey
    );


  if (!summary) {
    return {
      seeded:
        false,

      reason:
        "OWN_MODE_SEED_PROFILE_NOT_REGISTERED"
    };
  }


  const mode =
    policy.normalizeBrowserSessionMode(
      summary
        ?.browser_session_mode
    );


  if (!mode) {
    return {
      seeded:
        false,

      reason:
        "OWN_MODE_SEED_SESSION_MODE_UNKNOWN"
    };
  }


  return await policy
    .seedProfileDefaultFromMode(
      profileKey,
      mode
    );
}


async function refreshKnownBrowsers() {
  const payload =
    await fetchJson(
      QCC_BROWSERS_URL
    );

  if (
    !payload
    || payload.protocol_version !== 1
    || !Array.isArray(
        payload.browsers
      )
  ) {
    throw new Error(
      "QCC_BROWSERS_RESPONSE_INVALID"
    );
  }

  qccKnownBrowsers =
    payload.browsers;

  /*
   * Si OWN ya está vinculado, el inventario recién
   * recibido puede inicializar su default una sola vez.
   */
  await qccSeedOwnArchitectureProfileDefault();

  return payload;
}


function qccBrowserOptionLabel(
  profileKey
) {
  const summary =
    qccBrowserSummaryFor(
      profileKey
    );

  const parts = [
    profileKey
  ];

  if (
    profileKey
    === qccOwnBrowserProfileKey
  ) {
    parts.push(
      "ESTE NAVEGADOR"
    );
  }

  if (summary?.provider) {
    parts.push(
      normalizeLabel(
        summary.provider
      )
    );
  }

  parts.push(
    summary?.active
      ? "activo"
      : "sin sesión"
  );

  return parts.join(
    " · "
  );
}


function renderOwnBrowserBinding() {
  const mode =
    element(
      "browser-view-mode"
    );

  const note =
    element(
      "browser-context-note"
    );

  const input =
    element(
      "browser-profile-bind-input"
    );

  const selector =
    element(
      "browser-profile-selector"
    );

  /*
   * Un Chrome sin binding no adopta
   * identidades encontradas en el registry.
   */
  const profileKeys =
    qccOwnBrowserProfileKey
      ? Array.from(
          new Set(
            [
              qccOwnBrowserProfileKey,
              ...qccKnownBrowsers.map(
                (item) =>
                  String(
                    item?.browser_profile_key
                    || ""
                  ).trim()
              )
            ].filter(Boolean)
          )
        )
      : [];

  profileKeys.sort(
    (left, right) => {
      if (
        left === qccOwnBrowserProfileKey
      ) {
        return -1;
      }

      if (
        right === qccOwnBrowserProfileKey
      ) {
        return 1;
      }

      return left.localeCompare(
        right
      );
    }
  );

  if (selector) {
    selector.replaceChildren();

    if (profileKeys.length === 0) {
      const option =
        document.createElement(
          "option"
        );

      option.value = "";

      option.textContent =
        "Navegador sin vincular";

      selector.appendChild(
        option
      );

    } else {
      for (
        const profileKey
        of profileKeys
      ) {
        const option =
          document.createElement(
            "option"
          );

        option.value =
          profileKey;

        option.textContent =
          qccBrowserOptionLabel(
            profileKey
          );

        selector.appendChild(
          option
        );
      }

      selector.value =
        qccViewedBrowserProfileKey
        || qccOwnBrowserProfileKey;
    }

    selector.disabled =
      profileKeys.length <= 1;
  }

  if (
    input
    && qccOwnBrowserProfileKey
    && document.activeElement
      !== input
  ) {
    input.value =
      qccOwnBrowserProfileKey;
  }

  const ownView =
    qccIsOwnBrowserView();

  if (mode) {
    mode.classList.remove(
      "qcc-browser-view-mode--own",
      "qcc-browser-view-mode--remote"
    );

    if (!qccOwnBrowserProfileKey) {
      mode.textContent =
        "SIN VINCULAR";

    } else if (ownView) {
      mode.textContent =
        "ESTE NAVEGADOR";

      mode.classList.add(
        "qcc-browser-view-mode--own"
      );

    } else {
      mode.textContent =
        "VISTA REMOTA";

      mode.classList.add(
        "qcc-browser-view-mode--remote"
      );
    }
  }

  if (note) {
    note.classList.toggle(
      "qcc-browser-context-note--remote",
      Boolean(
        qccOwnBrowserProfileKey
        && !ownView
      )
    );

    if (!qccOwnBrowserProfileKey) {
      note.textContent =
        (
          "Este Chrome no está vinculado. "
          + "Indica su profile_key."
        );

    } else if (ownView) {
      note.textContent =
        (
          "Perfil propio: "
          + qccOwnBrowserProfileKey
        );

    } else {
      note.textContent =
        (
          "Vista remota de "
          + String(
              qccViewedBrowserProfileKey
            )
          + ". Solo lectura."
        );
    }
  }
}


async function handleBrowserProfileSelection(
  profileKey
) {
  const normalized =
    String(
      profileKey
      || ""
    ).trim();

  if (
    !qccOwnBrowserProfileKey
    || !normalized
  ) {
    return false;
  }

  const known =
    (
      normalized
      === qccOwnBrowserProfileKey
      || Boolean(
          qccBrowserSummaryFor(
            normalized
          )
        )
    );

  if (!known) {
    return false;
  }

  /*
   * VIEW cambia.
   * OWN nunca cambia desde el selector.
   */
  qccViewedBrowserProfileKey =
    normalized;

  qccViewedSessionId =
    null;

  await checkContext();

  return true;
}


async function handleBrowserProfileBind() {
  const input =
    element(
      "browser-profile-bind-input"
    );

  const button =
    element(
      "browser-profile-bind"
    );

  const profileKey =
    String(
      input?.value
      || ""
    ).trim();

  if (!profileKey) {
    setText(
      "browser-context-note",
      "Introduce un profile_key válido."
    );

    return;
  }

  if (button) {
    button.disabled = true;
  }

  try {
    const bound =
      await globalThis
        .QccBrowserIdentity
        .bind(
          profileKey
        );

    qccOwnBrowserProfileKey =
      bound;

    qccViewedBrowserProfileKey =
      bound;

    qccOwnSessionId =
      null;

    qccViewedSessionId =
      null;

    renderOwnBrowserBinding();

    await checkContext();

  } finally {
    if (button) {
      button.disabled = false;
    }
  }
}


function showEmptyContext(
  title = "Sin actividad en curso",
  description = (
    "Cuando una presentación o automatización "
    + "se conecte a QCC, aparecerá aquí su contexto."
  )
) {
  qccViewedSessionId = null;

  hideLiveNavigation();

  const empty =
    element("qcc-empty-state");

  const session =
    element("qcc-session-state");

  const provider =
    element("session-provider");

  if (empty) {
    empty.classList.remove(
      "qcc-hidden"
    );
  }

  if (session) {
    session.classList.add(
      "qcc-hidden"
    );
  }

  if (provider) {
    provider.classList.add(
      "qcc-hidden"
    );
  }

  setText(
    "qcc-empty-title",
    title
  );

  setText(
    "qcc-empty-description",
    description
  );
}


function renderSession(session) {
  qccViewedSessionId =
    session.session_id || null;


  const empty =
    element("qcc-empty-state");

  const sessionState =
    element("qcc-session-state");

  const provider =
    element("session-provider");

  if (empty) {
    empty.classList.add(
      "qcc-hidden"
    );
  }

  if (sessionState) {
    sessionState.classList.remove(
      "qcc-hidden"
    );
  }

  if (provider) {
    provider.classList.remove(
      "qcc-hidden"
    );

    provider.textContent =
      normalizeLabel(
        session.provider
      );
  }

  setText(
    "session-procedure",
    normalizeLabel(
      session.procedure
    )
  );

  setText(
    "session-expedient",
    String(
      session.expedient_id ?? "—"
    )
  );

  setText(
    "session-client",
    String(
      session.client_id ?? "—"
    )
  );

  setText(
    "session-runtime",
    normalizeLabel(
      session.runtime
    )
  );

  setText(
    "session-status",
    normalizeLabel(
      session.status
    )
  );

  const statusElement =
    element("session-status");

  if (statusElement) {
    const statusClasses = [
      "qcc-session-status--automating",
      "qcc-session-status--waiting-user",
      "qcc-session-status--user-action-detected",
      "qcc-session-status--resuming",
      "qcc-session-status--completed",
      "qcc-session-status--error"
    ];

    statusElement.classList.remove(
      ...statusClasses
    );

    const statusClass =
      String(session.status || "")
        .toLowerCase()
        .replaceAll("_", "-");

    if (statusClass) {
      statusElement.classList.add(
        `qcc-session-status--${statusClass}`
      );
    }
  }

  setText(
    "session-step",
    normalizeLabel(
      session.current_step
    )
  );

  const lastEvent =
    session.last_event || null;

  const lastEventText =
    lastEvent
      ? (
          lastEvent.message
          || lastEvent.event
          || "Evento QCC"
        )
      : "—";

  setText(
    "session-last-event",
    normalizeLabel(
      lastEventText
    )
  );

  const progress =
    Math.max(
      0,
      Math.min(
        100,
        Number(session.progress) || 0
      )
    );

  setText(
    "session-progress-label",
    `${progress} %`
  );

  const progressValue =
    element("session-progress-value");

  if (progressValue) {
    progressValue.style.width =
      `${progress}%`;
  }

  const warning =
    element("user-action-warning");

  const requiresUserAction =
    Boolean(
      session.requires_user_action
    ) ||
    session.status === "WAITING_USER";

  if (warning) {
    warning.classList.toggle(
      "qcc-hidden",
      !requiresUserAction
    );
  }

  const actionControls =
    element(
      "session-action-controls"
    );

  const startDocuments =
    element(
      "action-documents-start"
    );

  const documentPanel =
    element(
      "document-action-panel"
    );

  const documentPrepare =
    element(
      "action-document-prepare"
    );

  const documentSkip =
    element(
      "action-document-skip"
    );

  const documentForce =
    element(
      "action-document-force"
    );

  const documentForceInput =
    element(
      "document-force-type"
    );

  const ownInteractiveSession =
    (
      qccIsOwnBrowserView()
      && Boolean(
        qccOwnSessionId
      )
      && session.session_id
        === qccOwnSessionId
    );

  const canStartDocuments =
    (
      ownInteractiveSession
      && requiresUserAction
      && session.current_step
        === "DOCUMENTS_READY"
    );

  const documentIndex =
    Number(
      lastEvent?.document_index
    );

  const documentTotal =
    Number(
      lastEvent?.document_total
    );

  const documentName =
    String(
      lastEvent?.document_name
      || ""
    ).trim();

  const documentTypeCode =
    String(
      lastEvent?.document_type_code
      || ""
    ).trim();

  const canReviewDocument =
    (
      ownInteractiveSession
      && requiresUserAction
      && session.current_step
        === "DOCUMENT_READY"
      && Number.isInteger(documentIndex)
      && documentIndex > 0
      && Number.isInteger(documentTotal)
      && documentTotal > 0
      && Boolean(documentName)
    );

  if (actionControls) {
    actionControls.classList.toggle(
      "qcc-hidden",
      !(
        canStartDocuments
        || canReviewDocument
      )
    );
  }

  if (startDocuments) {
    startDocuments.classList.toggle(
      "qcc-hidden",
      !canStartDocuments
    );

    startDocuments.disabled =
      !canStartDocuments;
  }

  if (documentPanel) {
    documentPanel.classList.toggle(
      "qcc-hidden",
      !canReviewDocument
    );
  }

  if (canReviewDocument) {
    const documentIdentity =
      (
        `${session.session_id}:`
        + `${documentIndex}`
      );

    if (
      documentPanel
      && documentPanel.dataset
        .documentIdentity
        !== documentIdentity
    ) {
      documentPanel.dataset
        .documentIdentity =
          documentIdentity;

      documentPanel.dataset
        .documentIndex =
          String(documentIndex);

      documentPanel.dataset
        .submitted =
          "false";

      if (documentForceInput) {
        documentForceInput.value = "";
      }

      setText(
        "action-feedback",
        ""
      );
    }

    const submitted =
      (
        documentPanel?.dataset
          .submitted
        === "true"
      );

    setText(
      "document-position",
      `${documentIndex} de ${documentTotal}`
    );

    setText(
      "document-name",
      documentName
    );

    setText(
      "document-type-code",
      documentTypeCode || "—"
    );

    if (documentPrepare) {
      documentPrepare.disabled =
        submitted;
    }

    if (documentSkip) {
      documentSkip.disabled =
        submitted;
    }

    if (documentForce) {
      documentForce.disabled =
        submitted;
    }

    if (documentForceInput) {
      documentForceInput.disabled =
        submitted;
    }

    setText(
      "user-action-text",
      (
        "Revisa el documento actual y "
        + "elige cómo debe continuar la presentación."
      )
    );

  } else if (canStartDocuments) {
    setText(
      "user-action-text",
      (
        "La presentación está preparada para "
        + "iniciar la fase documental."
      )
    );

  } else {
    setText(
      "user-action-text",
      (
        "La presentación está esperando "
        + "una acción manual antes de continuar."
      )
    );

    setText(
      "action-feedback",
      ""
    );
  }
}


function hideLiveNavigation() {
  const navigation =
    element(
      "qcc-live-navigation"
    );

  if (navigation) {
    navigation.classList.add(
      "qcc-hidden"
    );
  }
}


function navigationDecisionLabel(
  decision
) {
  const labels = {
    HUMAN_ONLY:
      "Intervención humana",

    AUTOMATION_ALLOWED:
      "Automatización permitida",

    DENY:
      "Acción bloqueada",

    NO_ACTION_REQUIRED:
      "Objetivo alcanzado",

    OBSERVE_ONLY:
      "Solo observación"
  };

  return (
    labels[decision]
    || normalizeLabel(
      decision
    )
  );
}


function renderLiveNavigation(
  navigation,
  activeSessionId
) {
  const container =
    element(
      "qcc-live-navigation"
    );

  if (
    !container
    || !navigation
    || !activeSessionId
    || navigation.session_id
       !== activeSessionId
  ) {
    hideLiveNavigation();
    return;
  }

  container.classList.remove(
    "qcc-hidden"
  );

  const current =
    navigation.current || {};

  const target =
    navigation.target || {};

  const route =
    navigation.route || {};

  const nextStep =
    navigation.next_step || null;

  const governance =
    navigation.governance || null;

  const display =
    navigation.display || {};

  setText(
    "navigation-title",
    display.title
      || "Navegación viva"
  );

  setText(
    "navigation-current",
    normalizeLabel(
      current.state
    )
  );

  setText(
    "navigation-target",
    normalizeLabel(
      target.state
    )
  );

  let routeText = "—";

  if (
    route.reachable === true
  ) {
    const remaining =
      Number(
        route.remaining_steps
      );

    if (
      Number.isInteger(
        remaining
      )
      && remaining >= 0
    ) {
      if (remaining === 0) {
        routeText =
          "Objetivo alcanzado";

      } else if (
        remaining === 1
      ) {
        routeText =
          "1 paso restante";

      } else {
        routeText =
          `${remaining} pasos restantes`;
      }

    } else {
      routeText =
        "Ruta disponible";
    }

  } else if (
    route.reachable === false
  ) {
    routeText =
      "Sin ruta conocida";
  }

  setText(
    "navigation-route",
    routeText
  );

  let nextStepText = "—";

  if (nextStep) {
    nextStepText =
      normalizeLabel(
        nextStep.kind
      );

  } else if (
    route.reachable === true
    && route.remaining_steps === 0
  ) {
    nextStepText =
      "Sin acción pendiente";
  }

  setText(
    "navigation-next-step",
    nextStepText
  );

  const decision =
    governance?.decision || null;

  const decisionElement =
    element(
      "navigation-decision"
    );

  if (decisionElement) {
    const decisionClasses = [
      "qcc-navigation-decision--human-only",
      "qcc-navigation-decision--automation-allowed",
      "qcc-navigation-decision--deny",
      "qcc-navigation-decision--no-action-required",
      "qcc-navigation-decision--observe-only"
    ];

    decisionElement.classList.remove(
      ...decisionClasses
    );

    if (decision) {
      const decisionClass =
        String(decision)
          .toLowerCase()
          .replaceAll(
            "_",
            "-"
          );

      decisionElement.classList.add(
        (
          "qcc-navigation-decision--"
          + decisionClass
        )
      );
    }
  }

  setText(
    "navigation-decision",
    decision
      ? navigationDecisionLabel(
          decision
        )
      : "Pendiente"
  );

  const instruction =
    element(
      "navigation-instruction"
    );

  const instructionText =
    (
      display.instruction
      || governance?.reason
      || ""
    );

  if (instruction) {
    instruction.classList.toggle(
      "qcc-hidden",
      !instructionText
    );
  }

  setText(
    "navigation-instruction",
    normalizeLabel(
      instructionText
    )
  );
}


function renderContext(payload) {
  if (
    !payload ||
    payload.protocol_version !== 1
  ) {
    showEmptyContext(
      "Contexto no disponible",
      "El Bridge devolvió un contexto QCC no válido."
    );

    return;
  }

  if (
    !payload.active ||
    !payload.active_session
  ) {
    showEmptyContext();

    return;
  }

  renderSession(
    payload.active_session
  );

  renderLiveNavigation(
    payload.live_navigation,
    payload.active_session.session_id
  );
}


async function checkContext() {
  try {
    await refreshKnownBrowsers();

    if (!qccOwnBrowserProfileKey) {
      qccOwnSessionId =
        null;

      qccViewedBrowserProfileKey =
        null;

      qccViewedSessionId =
        null;

      renderOwnBrowserBinding();

      showEmptyContext(
        "Navegador sin vincular",
        (
          "Vincula este Chrome a su profile_key "
          + "para identificar su actividad propia."
        )
      );

      return;
    }

    const ownContext =
      await fetchJson(
        qccBrowserContextUrl(
          qccOwnBrowserProfileKey
        )
      );

    qccOwnSessionId =
      (
        ownContext?.active
        && ownContext?.active_session
        ? (
            ownContext
              .active_session
              .session_id
            || null
          )
        : null
      );

    if (!qccViewedBrowserProfileKey) {
      qccViewedBrowserProfileKey =
        qccOwnBrowserProfileKey;
    }

    /*
     * Un perfil remoto desaparecido del registry
     * no queda retenido como vista fantasma.
     */
    if (
      qccViewedBrowserProfileKey
        !== qccOwnBrowserProfileKey
      && !qccBrowserSummaryFor(
          qccViewedBrowserProfileKey
        )
    ) {
      qccViewedBrowserProfileKey =
        qccOwnBrowserProfileKey;
    }

    const viewedContext =
      (
        qccViewedBrowserProfileKey
        === qccOwnBrowserProfileKey
      )
        ? ownContext
        : await fetchJson(
            qccBrowserContextUrl(
              qccViewedBrowserProfileKey
            )
          );

    renderContext(
      viewedContext
    );

    renderOwnBrowserBinding();

  } catch (_) {
    qccOwnSessionId =
      null;

    qccViewedSessionId =
      null;

    showEmptyContext(
      "Contexto no disponible",
      "No se pudo leer el estado del navegador."
    );

    renderOwnBrowserBinding();
  }
}


async function checkBridgeHealth() {
  try {
    const payload =
      await fetchJson(
        QCC_BRIDGE_HEALTH_URL
      );

    const connected =
      payload &&
      payload.service === "qcc_bridge" &&
      payload.status === "ok" &&
      payload.protocol_version === 1;

    if (!connected) {
      throw new Error(
        "QCC_HEALTH_INVALID"
      );
    }

    setBridgeState(
      true,
      "QCC Bridge disponible."
    );

    await checkContext();
  } catch (_) {
    qccOwnSessionId =
      null;

    qccViewedSessionId =
      null;

    setBridgeState(
      false,
      "QCC Bridge todavía no está disponible."
    );

    showEmptyContext();

    renderOwnBrowserBinding();
  }
}


async function handleDocumentsStart() {
  const button =
    element(
      "action-documents-start"
    );

  if (!button) {
    return;
  }

  button.disabled = true;

  setText(
    "action-feedback",
    "Enviando acción..."
  );

  try {
    const result =
      await submitSessionAction(
        "DOCUMENTS_START",
        {}
      );

    if (
      !result
      || result.ok !== true
    ) {
      throw new Error(
        "QCC_ACTION_RESPONSE_INVALID"
      );
    }

    setText(
      "action-feedback",
      "Acción enviada al runtime."
    );

  } catch (_) {
    // Conservamos client_action_id para que
    // un reintento manual sea idempotente.
    setText(
      "action-feedback",
      (
        "No se pudo confirmar la acción. "
        + "Puedes volver a intentarlo."
      )
    );

    button.disabled = false;
  }
}


function currentDocumentIndex() {
  const panel =
    element(
      "document-action-panel"
    );

  const value =
    Number(
      panel?.dataset
        .documentIndex
    );

  if (
    !Number.isInteger(value)
    || value <= 0
  ) {
    throw new Error(
      "QCC_DOCUMENT_INDEX_INVALID"
    );
  }

  return value;
}


function setDocumentControlsDisabled(
  disabled
) {
  for (const id of [
    "action-document-prepare",
    "action-document-skip",
    "action-document-force",
    "document-force-type"
  ]) {
    const control =
      element(id);

    if (control) {
      control.disabled =
        Boolean(disabled);
    }
  }
}


async function submitDocumentAction(
  action,
  payload
) {
  const panel =
    element(
      "document-action-panel"
    );

  setDocumentControlsDisabled(
    true
  );

  setText(
    "action-feedback",
    "Enviando decisión..."
  );

  try {
    const result =
      await submitSessionAction(
        action,
        payload
      );

    if (
      !result
      || result.ok !== true
    ) {
      throw new Error(
        "QCC_ACTION_RESPONSE_INVALID"
      );
    }

    if (panel) {
      panel.dataset.submitted =
        "true";
    }

    setText(
      "action-feedback",
      "Decisión enviada al runtime."
    );

  } catch (_) {
    if (panel) {
      panel.dataset.submitted =
        "false";
    }

    setDocumentControlsDisabled(
      false
    );

    setText(
      "action-feedback",
      (
        "No se pudo confirmar la decisión. "
        + "Puedes volver a intentarlo."
      )
    );
  }
}


async function handleDocumentPrepare() {
  const documentIndex =
    currentDocumentIndex();

  await submitDocumentAction(
    "DOCUMENT_PREPARE",
    {
      document_index:
        documentIndex
    }
  );
}


async function handleDocumentSkip() {
  const documentIndex =
    currentDocumentIndex();

  await submitDocumentAction(
    "DOCUMENT_SKIP",
    {
      document_index:
        documentIndex
    }
  );
}


async function handleDocumentForceType() {
  const documentIndex =
    currentDocumentIndex();

  const input =
    element(
      "document-force-type"
    );

  const value =
    String(
      input?.value
      || ""
    ).trim();

  if (!value) {
    setText(
      "action-feedback",
      "Introduce un código documental."
    );

    return;
  }

  await submitDocumentAction(
    "DOCUMENT_FORCE_TYPE",
    {
      document_index:
        documentIndex,
      value
    }
  );
}



async function initializeQccShell() {
  const manifest =
    chrome.runtime.getManifest();

  setText(
    "qcc-version",
    `QCC ${manifest.version}`
  );

  setText(
    "qcc-build",
    "Presentation Context"
  );

  const browserSelector =
    element(
      "browser-profile-selector"
    );

  if (browserSelector) {
    browserSelector.addEventListener(
      "change",
      () => {
        handleBrowserProfileSelection(
          browserSelector.value
        ).catch(
          () => {}
        );
      }
    );
  }

  const browserBindButton =
    element(
      "browser-profile-bind"
    );

  const browserBindInput =
    element(
      "browser-profile-bind-input"
    );

  if (browserBindButton) {
    browserBindButton.addEventListener(
      "click",
      () => {
        handleBrowserProfileBind()
          .catch(
            () => {}
          );
      }
    );
  }

  if (browserBindInput) {
    browserBindInput.addEventListener(
      "keydown",
      (event) => {
        if (event.key === "Enter") {
          handleBrowserProfileBind()
            .catch(
              () => {}
            );
        }
      }
    );
  }

  const documentsStartButton =
    element(
      "action-documents-start"
    );

  if (documentsStartButton) {
    documentsStartButton.addEventListener(
      "click",
      handleDocumentsStart
    );
  }

  const documentPrepareButton =
    element(
      "action-document-prepare"
    );

  const documentSkipButton =
    element(
      "action-document-skip"
    );

  const documentForceButton =
    element(
      "action-document-force"
    );

  if (documentPrepareButton) {
    documentPrepareButton.addEventListener(
      "click",
      handleDocumentPrepare
    );
  }

  if (documentSkipButton) {
    documentSkipButton.addEventListener(
      "click",
      handleDocumentSkip
    );
  }

  if (documentForceButton) {
    documentForceButton.addEventListener(
      "click",
      handleDocumentForceType
    );
  }

  qccOwnBrowserProfileKey =
    await globalThis
      .QccBrowserIdentity
      .read();

  qccViewedBrowserProfileKey =
    qccOwnBrowserProfileKey;

  renderOwnBrowserBinding();

  await checkBridgeHealth();

  window.setInterval(
    checkBridgeHealth,
    QCC_HEALTH_INTERVAL_MS
  );
}


const QCC_CATALOG_HARVEST_MAX_VALUES =
  5;


function mainCatalogFromCapture(
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

  const matches =
    catalogs.filter(
      (catalog) =>
        catalog?.catalog_type
          === "native_select"
        && String(
          catalog?.selector
          || ""
        ) === selector
    );

  if (matches.length !== 1) {
    throw new Error(
      "QCC_CATALOG_HARVEST_SOURCE_NOT_FOUND"
    );
  }

  return matches[0];
}


function catalogHarvestValues(
  catalog,
  limit = QCC_CATALOG_HARVEST_MAX_VALUES
) {
  const currentValue =
    String(
      catalog
      ?.state
      ?.selected_value
      || ""
    );

  const options =
    (
      Array.isArray(
        catalog?.options
      )
      ? catalog.options
      : []
    );

  const values = [];

  for (const option of options) {
    const value =
      String(
        option?.value
        || ""
      );

    if (
      !value
      || option?.disabled === true
      || value === currentValue
    ) {
      continue;
    }

    if (!values.includes(value)) {
      values.push(value);
    }

    if (values.length >= limit) {
      break;
    }
  }

  return values;
}


function causalRelationSignature(
  relation
) {
  return (
    String(
      relation?.relation
      || ""
    )
    + "::"
    + String(
      relation?.source
      || ""
    )
    + "::"
    + String(
      relation?.target
      || ""
    )
  );
}


async function handleCatalogHarvest() {
  const button =
    element(
      "tool-catalog-harvest"
    );

  const selectorInput =
    element(
      "catalog-experiment-selector"
    );

  if (
    !button
    || !selectorInput
  ) {
    return;
  }

  const selector =
    String(
      selectorInput.value
      || ""
    ).trim();

  if (!selector) {
    setText(
      "catalog-harvest-feedback",
      "Indica el selector del catálogo."
    );

    return;
  }

  button.disabled =
    true;

  setText(
    "catalog-harvest-feedback",
    "Preparando cartografiado Twin..."
  );

  try {
    const permissionGranted =
      await requestDomInspectionPermission();

    if (!permissionGranted) {
      throw new Error(
        "QCC_DOM_HOST_PERMISSION_DENIED"
      );
    }

    const initialCapture =
      await chrome.runtime.sendMessage({
        type:
          "QCC_DOM_INSPECT"
      });

    if (
      !initialCapture
      || initialCapture.ok !== true
    ) {
      throw new Error(
        initialCapture?.error
        || "QCC_CATALOG_HARVEST_CAPTURE_INVALID"
      );
    }

    const sourceCatalog =
      mainCatalogFromCapture(
        initialCapture,
        selector
      );

    if (
      sourceCatalog
      ?.state
      ?.disabled === true
      || sourceCatalog
      ?.state
      ?.multiple === true
    ) {
      throw new Error(
        "QCC_CATALOG_HARVEST_SOURCE_UNSAFE"
      );
    }

    const values =
      catalogHarvestValues(
        sourceCatalog
      );

    if (values.length === 0) {
      throw new Error(
        "QCC_CATALOG_HARVEST_NO_VALUES"
      );
    }

    let completed =
      0;

    let totalEvidence =
      0;

    const causalRelations =
      new Map();

    for (const requestedValue of values) {
      setText(
        "catalog-harvest-feedback",
        (
          "Cartografiando "
          + `${completed + 1}/${values.length}`
          + "..."
        )
      );

      const experiment =
        await chrome.runtime.sendMessage({
          type:
            "QCC_CATALOG_EXPERIMENT",

          selector:
            selector,

          requested_value:
            requestedValue
        });

      if (
        !experiment
        || experiment.ok !== true
      ) {
        throw new Error(
          experiment?.error
          || "QCC_CATALOG_HARVEST_EXPERIMENT_FAILED"
        );
      }

      const verification =
        (
          experiment
          ?.restoration_verification
          || {}
        );

      if (verification.exact !== true) {
        throw new Error(
          "QCC_CATALOG_HARVEST_RESTORE_NOT_EXACT"
        );
      }

      /*
       * No continuamos haciendo mutaciones si
       * el backend no puede analizar el resultado.
       */
      const analysis =
        await submitCatalogExperiment(
          experiment
        );

      if (
        !analysis
        || analysis.ok !== true
      ) {
        throw new Error(
          "QCC_CATALOG_HARVEST_ANALYSIS_FAILED"
        );
      }

      totalEvidence +=
        Number(
          analysis.evidence_count
          || 0
        );

      for (
        const relation
        of (
          analysis.causal_relations
          || []
        )
      ) {
        const signature =
          causalRelationSignature(
            relation
          );

        if (signature) {
          causalRelations.set(
            signature,
            relation
          );
        }
      }

      completed += 1;
    }

    setText(
      "catalog-harvest-feedback",
      (
        `Cartografiado ${completed}/${values.length}`
        + " · evidencia "
        + `${totalEvidence}`
        + " · relaciones únicas "
        + `${causalRelations.size}`
        + " · restauración exacta · OK"
      )
    );

  } catch (error) {
    const detail =
      String(
        error?.message
        || error
        || "QCC_CATALOG_HARVEST_FAILED"
      );

    setText(
      "catalog-harvest-feedback",
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


function sanitizedOptionsForHarvest(
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


function downloadSiteCatalogHarvest(
  payload,
  filenamePrefix = "qcc_site_catalog_harvest"
) {
  const blob =
    new Blob(
      [
        JSON.stringify(
          payload,
          null,
          2
        )
      ],
      {
        type:
          "application/json"
      }
    );

  const url =
    URL.createObjectURL(
      blob
    );

  const stamp =
    new Date()
      .toISOString()
      .replace(
        /[:.]/g,
        "-"
      );

  const link =
    document.createElement(
      "a"
    );

  link.href =
    url;

  link.download =
    (
      sanitizeDownloadToken(
        filenamePrefix
      )
      + "_"
      + stamp
      + ".json"
    );

  document.body.appendChild(
    link
  );

  link.click();
  link.remove();

  window.setTimeout(
    () => {
      URL.revokeObjectURL(
        url
      );
    },
    1000
  );
}


function realCatalogSelector(
  elementId
) {
  return String(
    element(
      elementId
    )?.value
    || ""
  ).trim();
}



let qccCatalogBrowserCapture =
  null;


function mainCatalogsFromCapture(
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

  return (
    mainFrame
      ?.result
      ?.catalog_probe
      ?.elements
    || []
  ).filter(
    (catalog) =>
      catalog?.catalog_type
        === "native_select"
  );
}


function humanizeCatalogSelector(
  selector
) {
  return String(
    selector
    || ""
  )
    .replace(/^#/, "")
    .replace(
      /([a-z])([A-Z])/g,
      "$1 $2"
    )
    .replace(
      /[_-]+/g,
      " "
    )
    .trim();
}


function catalogBrowserLabel(
  catalog
) {
  const label =
    String(
      catalog?.label
      || catalog?.element?.label
      || catalog?.element?.accessible_name
      || ""
    ).trim();

  if (label) {
    return label;
  }

  return humanizeCatalogSelector(
    catalog?.selector
  );
}



function collectCatalogDependencyHintTokens(
  value,
  target
) {
  if (typeof value === "string") {
    const raw =
      value.trim();

    if (!raw) {
      return;
    }

    target.add(raw);

    raw
      .split(
        /[\s,;|]+/
      )
      .map(
        (token) =>
          token.trim()
      )
      .filter(Boolean)
      .forEach(
        (token) =>
          target.add(token)
      );

    return;
  }

  if (Array.isArray(value)) {
    value.forEach(
      (item) =>
        collectCatalogDependencyHintTokens(
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
    Object.values(value)
      .forEach(
        (item) =>
          collectCatalogDependencyHintTokens(
            item,
            target
          )
      );
  }
}


function normalizedCatalogReference(
  value
) {
  return String(
    value
    || ""
  )
    .trim()
    .replace(
      /^#/,
      ""
    );
}


function catalogDependencyCandidates(
  sourceCatalog,
  catalogs
) {
  if (!sourceCatalog) {
    return [];
  }

  const rawTokens =
    new Set();

  collectCatalogDependencyHintTokens(
    sourceCatalog.dependency_hints,
    rawTokens
  );

  const references =
    new Set(
      Array.from(
        rawTokens
      )
        .map(
          normalizedCatalogReference
        )
        .filter(Boolean)
    );

  const sourceSelector =
    String(
      sourceCatalog?.selector
      || ""
    );

  const candidates =
    [];

  for (const catalog of catalogs) {
    const selector =
      String(
        catalog?.selector
        || ""
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
          normalizedCatalogReference
        )
        .filter(Boolean);

    const referenced =
      aliases.some(
        (alias) =>
          references.has(alias)
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


function updateCatalogRelationButtonState(
  manualSelection = false
) {
  const source =
    element(
      "catalog-real-source-selector"
    );

  const target =
    element(
      "catalog-real-target-selector"
    );

  const button =
    element(
      "tool-catalog-relation-harvest"
    );

  if (
    !source
    || !target
    || !button
  ) {
    return;
  }

  const sourceSelector =
    String(
      source.value
      || ""
    );

  const targetSelector =
    String(
      target.value
      || ""
    );

  const valid =
    Boolean(
      sourceSelector
      && targetSelector
      && sourceSelector
        !== targetSelector
    );

  button.disabled =
    !valid;

  if (
    manualSelection
    && valid
  ) {
    setText(
      "catalog-relation-harvest-feedback",
      (
        "Dependencia seleccionada · "
        + sourceSelector
        + " → "
        + targetSelector
      )
    );
  }
}


function applyCatalogDependencySuggestion() {
  const source =
    element(
      "catalog-real-source-selector"
    );

  const target =
    element(
      "catalog-real-target-selector"
    );

  const button =
    element(
      "tool-catalog-relation-harvest"
    );

  if (
    !source
    || !target
    || !button
    || !qccCatalogBrowserCapture
  ) {
    return;
  }

  const catalogs =
    mainCatalogsFromCapture(
      qccCatalogBrowserCapture
    );

  const sourceSelector =
    String(
      source.value
      || ""
    );

  const sourceCatalog =
    catalogs.find(
      (catalog) =>
        String(
          catalog?.selector
          || ""
        ) === sourceSelector
    )
    || null;

  const candidates =
    catalogDependencyCandidates(
      sourceCatalog,
      catalogs
    );

  if (candidates.length === 1) {
    target.value =
      candidates[0];

    button.disabled =
      false;

    setText(
      "catalog-relation-harvest-feedback",
      (
        "Dependencia detectada · "
        + sourceSelector
        + " → "
        + candidates[0]
      )
    );

    return;
  }

  /*
   * No elegimos arbitrariamente cuando
   * existen cero o varias dependencias.
   */
  target.selectedIndex =
    -1;

  button.disabled =
    true;

  if (candidates.length > 1) {
    setText(
      "catalog-relation-harvest-feedback",
      (
        `${candidates.length} dependencias detectadas`
        + " · selecciona destino"
      )
    );

    return;
  }

  setText(
    "catalog-relation-harvest-feedback",
    "Sin dependencia detectada · captura individual disponible"
  );
}


function populateCatalogBrowserSelect(
  selectId,
  catalogs,
  preferredSelector
) {
  const select =
    element(selectId);

  if (!select) {
    return;
  }

  const previous =
    String(
      select.value
      || preferredSelector
      || select.dataset
        ?.defaultSelector
      || ""
    );

  select.replaceChildren();

  for (const catalog of catalogs) {
    const selector =
      String(
        catalog?.selector
        || ""
      );

    if (!selector) {
      continue;
    }

    const option =
      document.createElement(
        "option"
      );

    option.value =
      selector;

    option.textContent =
      (
        selector
        + " · "
        + String(
            catalog?.options
              ?.length
            || 0
          )
        + " opciones"
      );

    select.appendChild(
      option
    );
  }

  const previousExists =
    Array.from(
      select.options
    ).some(
      (option) =>
        option.value === previous
    );

  if (previousExists) {
    select.value =
      previous;
  }
}


async function refreshCatalogBrowser() {
  const permissionGranted =
    await requestDomInspectionPermission();

  if (!permissionGranted) {
    throw new Error(
      "QCC_DOM_HOST_PERMISSION_DENIED"
    );
  }

  setText(
    "catalog-capture-feedback",
    "Detectando catálogos..."
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
      "QCC_CATALOG_BROWSER_CAPTURE_INVALID"
    );
  }

  const catalogs =
    mainCatalogsFromCapture(
      capture
    );

  if (!catalogs.length) {
    throw new Error(
      "QCC_CATALOG_BROWSER_EMPTY"
    );
  }

  qccCatalogBrowserCapture =
    capture;

  populateCatalogBrowserSelect(
    "catalog-real-source-selector",
    catalogs
  );

  populateCatalogBrowserSelect(
    "catalog-real-target-selector",
    catalogs
  );

  applyCatalogDependencySuggestion();

  setText(
    "catalog-capture-feedback",
    (
      `${catalogs.length} catálogos detectados`
      + " · OK"
    )
  );

  return capture;
}


async function handlePassiveCatalogCapture() {
  try {
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

    const selector =
      realCatalogSelector(
        "catalog-real-source-selector"
      );

    const catalog =
      mainCatalogFromCapture(
        capture,
        selector
      );

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
        new URL(mainUrl);

      origin =
        parsed.origin;

      pathname =
        parsed.pathname;
    } catch (_) {
      // El artefacto sigue siendo válido.
    }

    const artifact = {
      schema_version:
        1,

      artifact_type:
        "QCC_SITE_CATALOG",

      origin:
        origin,

      pathname:
        pathname,

      captured_at:
        new Date().toISOString(),

      catalog: {
        selector:
          selector,

        label:
          catalogBrowserLabel(
            catalog
          ),

        options:
          sanitizedOptionsForHarvest(
            catalog
          )
      }
    };

    downloadSiteCatalogHarvest(
      artifact,
      "qcc_site_catalog"
    );

    setText(
      "catalog-capture-feedback",
      (
        "Catálogo capturado · "
        + `${artifact.catalog.options.length}`
        + " opciones · JSON descargado · OK"
      )
    );

  } catch (error) {
    setText(
      "catalog-capture-feedback",
      (
        "Captura detenida · "
        + String(
            error?.message
            || error
          )
      )
    );
  }
}


function sourceCatalogOption(
  catalog,
  value
) {
  return (
    (
      catalog?.options
      || []
    ).find(
      (option) =>
        String(
          option?.value
          || ""
        ) === String(
          value
          || ""
        )
    )
    || null
  );
}


function sequentialCatalogValues(
  options,
  currentValue
) {
  const usable =
    (
      Array.isArray(options)
      ? options
      : []
    ).filter(
      (option) => (
        String(
          option?.value
          || ""
        )
        && option?.disabled !== true
      )
    );

  const currentIndex =
    usable.findIndex(
      (option) =>
        String(
          option?.value
          || ""
        ) === currentValue
    );

  if (currentIndex < 0) {
    return usable;
  }

  /*
   * Comenzamos justo después del valor
   * actual y hacemos una sola vuelta.
   *
   * Ejemplo:
   * 24 → 25 → 26 → ... → 78
   *    → 1 → 2 → ... → 23
   *
   * Nunca:
   * 24 → X → 24 → Y → 24.
   */
  return [
    ...usable.slice(
      currentIndex + 1
    ),
    ...usable.slice(
      0,
      currentIndex
    )
  ];
}


function catalogSourceSystemFromOrigin(
  origin
) {
  const value =
    String(
      origin
      || ""
    ).trim();

  if (!value) {
    return null;
  }

  try {
    const hostname =
      String(
        new URL(
          value
        ).hostname
        || ""
      )
      .trim()
      .toLowerCase();

    if (!hostname) {
      return null;
    }

    const parts =
      hostname
      .split(".")
      .filter(Boolean);

    if (
      parts.length > 1
      && parts[0] === "www"
    ) {
      parts.shift();
    }

    const source =
      String(
        parts[0]
        || ""
      )
      .trim()
      .toUpperCase();

    return source || null;

  } catch (_) {
    return null;
  }
}


async function handleCatalogExperiment() {
  const button =
    element(
      "tool-catalog-experiment"
    );

  const selectorInput =
    element(
      "catalog-experiment-selector"
    );


  if (
    !button
    || !selectorInput
  ) {
    return;
  }


  const selector =
    String(
      selectorInput.value
      || ""
    ).trim();


  if (!selector) {
    setText(
      "catalog-experiment-feedback",
      "Indica el selector del catálogo."
    );

    return;
  }


  button.disabled =
    true;


  setText(
    "catalog-experiment-feedback",
    "Experimento Twin en curso..."
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
          "QCC_CATALOG_EXPERIMENT",

        selector:
          selector
      });


    if (
      !result
      || result.ok !== true
    ) {
      throw new Error(
        result?.error
        || "QCC_CATALOG_EXPERIMENT_INVALID"
      );
    }


    const mutation =
      result.mutation
      || {};

    const restoration =
      result.restoration
      || {};

    const verification =
      result.restoration_verification
      || {};

    const comparedCatalogs =
      Number(
        verification.compared_catalogs
        || 0
      );


    let backendAnalysis = null;

    try {
      backendAnalysis =
        await submitCatalogExperiment(
          result
        );

      if (
        !backendAnalysis
        || backendAnalysis.ok !== true
      ) {
        throw new Error(
          "QCC_CATALOG_EXPERIMENT_ANALYSIS_INVALID"
        );
      }

    } catch (error) {
      console.warn(
        "[QCC] Catalog experiment backend:",
        error
      );
    }


    const causalRelations =
      Number(
        backendAnalysis
        ?.causal_relation_count
        || 0
      );

    const evidenceCount =
      Number(
        backendAnalysis
        ?.evidence_count
        || 0
      );


    setText(
      "catalog-experiment-feedback",
      (
        `${mutation.original_value || "∅"}`
        + " → "
        + `${mutation.test_value || "∅"}`
        + " → restaurado "
        + `${restoration.restored_value || "∅"}`
        + " · estado integral "
        + `${comparedCatalogs}/${comparedCatalogs}`
        + (
            backendAnalysis
            ? (
                " · evidencia "
                + `${evidenceCount}`
                + " · relaciones causales "
                + `${causalRelations}`
              )
            : " · análisis backend no disponible"
          )
        + " · OK"
      )
    );

  } catch (error) {
    const detail =
      String(
        error?.message
        || error
        || "QCC_CATALOG_EXPERIMENT_FAILED"
      );


    setText(
      "catalog-experiment-feedback",
      (
        "Experimento rechazado/fallido · "
        + detail
      )
    );

  } finally {
    button.disabled =
      false;
  }
}


document.addEventListener(
  "DOMContentLoaded",
  initializeQccShell
);


function sanitizeDownloadToken(
  value
) {
  return (
    String(
      value
      || "pagina"
    )
      .trim()
      .replace(
        /[^A-Za-z0-9._-]+/g,
        "_"
      )
      .replace(
        /^[_\-.]+|[_\-.]+$/g,
        ""
      )
    || "pagina"
  );
}


function buildDomCaptureFilename(
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

  const hostname =
    sanitizeDownloadToken(
      mainFrame
        ?.result
        ?.hostname
        || "pagina"
    );

  const timestamp =
    String(
      capture?.captured_at
      || new Date()
        .toISOString()
    )
      .replace(
        /[:.]/g,
        "-"
      );

  return (
    "qcc_dom_capture_"
    + hostname
    + "_"
    + timestamp
    + ".json"
  );
}


function downloadDomCapture(
  capture
) {
  const serialized =
    JSON.stringify(
      capture,
      null,
      2
    );

  const blob =
    new Blob(
      [
        serialized
      ],
      {
        type:
          "application/json;charset=utf-8"
      }
    );

  const objectUrl =
    URL.createObjectURL(
      blob
    );

  const anchor =
    document.createElement(
      "a"
    );

  anchor.href =
    objectUrl;

  anchor.download =
    buildDomCaptureFilename(
      capture
    );

  anchor.style.display =
    "none";

  document.body.appendChild(
    anchor
  );

  anchor.click();
  anchor.remove();

  window.setTimeout(
    () => {
      URL.revokeObjectURL(
        objectUrl
      );
    },
    1500
  );

  return {
    filename:
      anchor.download,

    bytes:
      new TextEncoder()
        .encode(
          serialized
        )
        .length
  };
}


/* QCC_PROTOCOL_VERSION_V1 */
const QCC_PROTOCOL_VERSION = 1;


const QCC_SITE_ARCHITECTURE_PAGE_ARTIFACT_URL =
  QCC_SITE_ARCHITECTURE_CAPTURE_URL.replace(
    "/capture",
    "/page-artifact"
  );


/*
 * QCC_VISUAL_CAPTURE_PERMISSION_V1
 *
 * captureVisibleTab() requiere activeTab concedido
 * por una invocación compatible o <all_urls>.
 *
 * El Side Panel no proporciona por sí mismo el grant
 * temporal activeTab necesario para esta operación.
 *
 * <all_urls> permanece OPTIONAL:
 * QCC lo solicita explícitamente al usuario desde
 * Herramientas de navegador y, una vez concedido,
 * permitirá también la futura captura automática.
 */
const QCC_DOM_OPTIONAL_ORIGINS = [
  "<all_urls>"
];


async function requestDomInspectionPermission() {
  /*
   * Debe ejecutarse directamente como consecuencia
   * del click del usuario.
   *
   * El permiso es opcional: QCC no obtiene acceso
   * permanente a sitios web simplemente por instalarse.
   */
  const granted =
    await chrome.permissions.request({
      permissions: [
        "pageCapture"
      ],
      origins:
        QCC_DOM_OPTIONAL_ORIGINS
    });

  return Boolean(
    granted
  );
}



/*
 * QCC_PAGE_MHTML_CAPTURE_V1
 *
 * Captura autocontenida realizada por Chrome.
 *
 * NO:
 * - scroll
 * - chrome.debugger
 * - mutación DOM
 */
async function captureActivePageMhtml(
  domCapture
) {
  const tabs =
    await chrome.tabs.query({
      active: true,
      lastFocusedWindow: true
    });


  const tab =
    (
      tabs
      && tabs.length
    )
      ? tabs[0]
      : null;


  if (
    !tab
    || !Number.isInteger(
        tab.id
      )
  ) {
    throw new Error(
      "QCC_MHTML_ACTIVE_TAB_NOT_FOUND"
    );
  }


  const capturedTabId =
    Number(
      domCapture?.tab_id
    );


  if (
    Number.isFinite(
      capturedTabId
    )
    && capturedTabId !== tab.id
  ) {
    throw new Error(
      "QCC_MHTML_TAB_CHANGED"
    );
  }


  if (
    !chrome.pageCapture
    || typeof (
        chrome
        .pageCapture
        .saveAsMHTML
      ) !== "function"
  ) {
    throw new Error(
      "QCC_MHTML_API_UNAVAILABLE"
    );
  }


  const blob =
    await chrome
      .pageCapture
      .saveAsMHTML({
        tabId:
          tab.id
      });


  if (
    !(blob instanceof Blob)
    || blob.size <= 0
  ) {
    throw new Error(
      "QCC_MHTML_CAPTURE_EMPTY"
    );
  }


  return {
    kind:
      "mhtml",

    captured_at:
      new Date()
        .toISOString(),

    tab_id:
      tab.id,

    content_type:
      "multipart/related",

    blob,
  };
}


/*
 * QCC_PAGE_MHTML_UPLOAD_V1
 */
async function submitPageArchiveArtifact(
  captureId,
  pageArchive
) {
  const normalizedCaptureId =
    String(
      captureId
      || ""
    ).trim();


  if (!normalizedCaptureId) {
    throw new Error(
      "QCC_MHTML_CAPTURE_ID_REQUIRED"
    );
  }


  if (
    !pageArchive
    || pageArchive.kind !== "mhtml"
    || !(pageArchive.blob instanceof Blob)
    || pageArchive.blob.size <= 0
  ) {
    throw new Error(
      "QCC_MHTML_ARTIFACT_INVALID"
    );
  }


  const controller =
    new AbortController();


  const timeout =
    setTimeout(
      () => controller.abort(),
      20000
    );


  try {
    const response =
      await fetch(
        QCC_SITE_ARCHITECTURE_PAGE_ARTIFACT_URL,
        {
          method:
            "POST",

          headers: {
            "Content-Type":
              "multipart/related",

            "X-QCC-Protocol-Version":
              String(
                QCC_PROTOCOL_VERSION
              ),

            "X-QCC-Capture-Id":
              normalizedCaptureId,

            "X-QCC-Page-Kind":
              "mhtml",
          },

          body:
            pageArchive.blob,

          signal:
            controller.signal,
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
          "QCC_MHTML_UPLOAD_HTTP_"
          + String(
              response.status
            )
        )
      );
    }


    return payload;

  } finally {
    clearTimeout(
      timeout
    );
  }
}


/*
 * QCC_PAGE_MHTML_LOCAL_FALLBACK_V1
 */
function downloadPageArchive(
  pageArchive,
  domDownload
) {
  if (
    !pageArchive
    || pageArchive.kind !== "mhtml"
    || !(pageArchive.blob instanceof Blob)
  ) {
    throw new Error(
      "QCC_MHTML_LOCAL_ARTIFACT_INVALID"
    );
  }


  const domFilename =
    String(
      domDownload?.filename
      || ""
    );


  let filename =
    (
      "qcc_site_architecture_"
      + new Date()
          .toISOString()
          .replace(
            /[:.]/g,
            "-"
          )
      + ".mhtml"
    );


  if (
    domFilename
    && domFilename.endsWith(
      ".json"
    )
  ) {
    filename =
      (
        domFilename.slice(
          0,
          -5
        )
        + ".mhtml"
      );
  }


  const objectUrl =
    URL.createObjectURL(
      pageArchive.blob
    );


  const anchor =
    document.createElement(
      "a"
    );

  anchor.href =
    objectUrl;

  anchor.download =
    filename;

  anchor.style.display =
    "none";


  document.body.appendChild(
    anchor
  );

  anchor.click();
  anchor.remove();


  setTimeout(
    () => {
      URL.revokeObjectURL(
        objectUrl
      );
    },
    1500
  );


  return {
    ok:
      true,

    filename,

    bytes:
      pageArchive.blob.size,
  };
}



/*
 * QCC_GENERIC_DOM_HARVEST_UI_V1
 *
 * La UI nunca es autoridad de seguridad.
 * El Service Worker vuelve a resolver la política
 * antes de producir el dataset.
 */


async function qccGenericHarvestMessage(
  type,
  timeoutMs = 30000
) {
  let timer =
    null;

  try {
    const timeout =
      Math.max(
        1000,
        Number(
          timeoutMs
          || 30000
        )
      );

    const result =
      await Promise.race([
        chrome.runtime.sendMessage({
          type:
            type
        }),

        new Promise(
          (
            _resolve,
            reject
          ) => {
            timer =
              window.setTimeout(
                () => {
                  reject(
                    new Error(
                      "QCC_GENERIC_HARVEST_TIMEOUT"
                    )
                  );
                },
                timeout
              );
          }
        )
      ]);

    if (
      !result
      || result.ok === false
    ) {
      throw new Error(
        result?.error
        || result?.reason
        || "QCC_GENERIC_HARVEST_RESPONSE_INVALID"
      );
    }

    return result;

  } finally {
    if (timer !== null) {
      window.clearTimeout(
        timer
      );
    }
  }
}


async function handleGenericHarvestEnable() {
  const button =
    element(
      "tool-generic-harvest-enable"
    );

  if (button) {
    button.disabled =
      true;
  }

  try {
    const result =
      await qccGenericHarvestMessage(
        "QCC_GENERIC_HARVEST_ENABLE",
        10000
      );

    if (
      !result
      || result.ok !== true
      || result.enabled !== true
    ) {
      throw new Error(
        result?.reason
        || result?.error
        || "QCC_GENERIC_HARVEST_ENABLE_DENIED"
      );
    }

    setText(
      "generic-harvest-feedback",
      (
        "Harvest activo · "
        + String(
            result?.policy?.origin
            || ""
          )
        + " · "
        + String(
            result?.policy?.mode
            || ""
          )
      )
    );

  } catch (error) {
    setText(
      "generic-harvest-feedback",
      (
        "Harvest no autorizado · "
        + String(
            error?.message
            || error
          )
      )
    );

  } finally {
    if (button) {
      button.disabled =
        false;
    }
  }
}



async function handleGenericDynamicHarvest() {
  const button =
    element(
      "tool-generic-dynamic-harvest"
    );

  if (!button) {
    return;
  }

  button.disabled =
    true;

  setText(
    "generic-harvest-feedback",
    "Harvest dinámico · recorriendo página..."
  );

  try {
    /*
     * Gesto explícito antes de iniciar
     * cualquier adquisición dinámica.
     */
    const permissionGranted =
      await requestDomInspectionPermission();

    if (!permissionGranted) {
      throw new Error(
        "QCC_DOM_HOST_PERMISSION_DENIED"
      );
    }


    const result =
      await qccGenericHarvestMessage(
        "QCC_GENERIC_DYNAMIC_HARVEST",
        60000
      );

    const dataset =
      result?.dataset;

    if (
      !dataset
      || dataset.artifact_type
        !== "QCC_GENERIC_DYNAMIC_HARVEST"
    ) {
      throw new Error(
        "QCC_GENERIC_DYNAMIC_HARVEST_DATASET_INVALID"
      );
    }


    downloadSiteCatalogHarvest(
      dataset,
      "qcc_generic_dynamic_harvest"
    );


    setText(
      "generic-harvest-feedback",
      (
        "Harvest dinámico · "
        + String(
            dataset.deduplicated_count
            || 0
          )
        + " únicos · "
        + String(
            dataset.scroll_steps_completed
            || 0
          )
        + " paso(s) · "
        + String(
            dataset.stop_reason
            || ""
          )
        + " · JSON descargado"
      )
    );

  } catch (error) {
    setText(
      "generic-harvest-feedback",
      (
        "Harvest dinámico detenido · "
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


async function handleGenericHarvestDisable() {
  const button =
    element(
      "tool-generic-harvest-disable"
    );

  if (button) {
    button.disabled =
      true;
  }

  try {
    const result =
      await qccGenericHarvestMessage(
        "QCC_GENERIC_HARVEST_DISABLE",
        10000
      );

    if (
      !result
      || result.ok !== true
    ) {
      throw new Error(
        result?.reason
        || result?.error
        || "QCC_GENERIC_HARVEST_DISABLE_FAILED"
      );
    }

    setText(
      "generic-harvest-feedback",
      "Harvest desactivado · SNAPSHOT_ONLY"
    );

  } catch (error) {
    setText(
      "generic-harvest-feedback",
      (
        "No se pudo desactivar Harvest · "
        + String(
            error?.message
            || error
          )
      )
    );

  } finally {
    if (button) {
      button.disabled =
        false;
    }
  }
}


async function handleGenericDomHarvest() {
  const button =
    element(
      "tool-generic-dom-harvest"
    );

  if (!button) {
    return;
  }

  button.disabled =
    true;

  setText(
    "generic-harvest-feedback",
    "Extrayendo dataset del DOM cargado..."
  );

  try {
    /*
     * Gesto explícito del usuario:
     * permite solicitar host permission si aún falta.
     */
    const permissionGranted =
      await requestDomInspectionPermission();

    if (!permissionGranted) {
      throw new Error(
        "QCC_DOM_HOST_PERMISSION_DENIED"
      );
    }


    const result =
      await qccGenericHarvestMessage(
        "QCC_GENERIC_DOM_HARVEST",
        30000
      );

    const dataset =
      result?.dataset;

    if (
      !dataset
      || dataset.artifact_type
        !== "QCC_GENERIC_DOM_HARVEST"
    ) {
      throw new Error(
        "QCC_GENERIC_DOM_HARVEST_DATASET_INVALID"
      );
    }


    downloadSiteCatalogHarvest(
      dataset,
      "qcc_generic_dom_harvest"
    );


    setText(
      "generic-harvest-feedback",
      (
        "Dataset capturado · "
        + String(
            dataset.deduplicated_count
            || 0
          )
        + " elementos · "
        + String(
            dataset.captured_frames
            || 0
          )
        + " frame(s) · JSON descargado"
      )
    );

  } catch (error) {
    setText(
      "generic-harvest-feedback",
      (
        "Dataset no capturado · "
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
    const enable =
      element(
        "tool-generic-harvest-enable"
      );

    const capture =
      element(
        "tool-generic-dom-harvest"
      );

    const dynamic =
      element(
        "tool-generic-dynamic-harvest"
      );

    const disable =
      element(
        "tool-generic-harvest-disable"
      );


    if (enable) {
      enable.addEventListener(
        "click",
        handleGenericHarvestEnable
      );
    }

    if (capture) {
      capture.addEventListener(
        "click",
        handleGenericDomHarvest
      );
    }

    if (dynamic) {
      dynamic.addEventListener(
        "click",
        handleGenericDynamicHarvest
      );
    }

    if (disable) {
      disable.addEventListener(
        "click",
        handleGenericHarvestDisable
      );
    }
  }
);


async function handleDomInspect() {
  const button =
    element(
      "tool-dom-inspect"
    );

  if (!button) {
    return;
  }

  button.disabled =
    true;

  setText(
    "dom-inspect-feedback",
    "Forzando captura de la pestaña activa..."
  );


  try {
    /*
     * Primera operación privilegiada:
     * conservar el gesto explícito del usuario
     * para chrome.permissions.request().
     */
    const permissionGranted =
      await requestDomInspectionPermission();

    if (!permissionGranted) {
      throw new Error(
        "QCC_DOM_HOST_PERMISSION_DENIED"
      );
    }

    setText(
      "dom-inspect-feedback",
      "Permiso concedido · forzando captura..."
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
        capture?.error
        || "QCC_DOM_CAPTURE_INVALID"
      );
    }


    let backendResult = null;
    let saved = null;
    let humanListenerStatus =
      "listener humano: no solicitado";

    /*
     * QCC_VISUAL_VIEWPORT_PREPARED
     *
     * Capturamos aquí, inmediatamente después del
     * DOM/Geometry y ANTES del procesamiento backend.
     *
     * Si falla, Site Architecture continúa fail-open.
     */
    let viewportEvidence = null;
    let viewportStatus =
      "viewport: no disponible";


    // QCC_PAGE_MHTML_PREPARED_V1
    let pageArchiveEvidence = null;

    let pageArchiveStatus =
      "mhtml: no disponible";

    try {
      viewportEvidence =
        await captureActiveViewportScreenshot(
          capture
        );

      viewportStatus =
        "viewport: capturado";

    } catch (visualCaptureError) {
      viewportStatus =
        (
          "viewport: ERROR · "
          + String(
              visualCaptureError?.message
              || visualCaptureError
            )
        );

      console.warn(
        "[QCC] Viewport capture:",
        visualCaptureError
      );
    }

    /*
     * QCC_PAGE_MHTML_CAPTURE_PRE_BACKEND_V1
     */
    try {
      pageArchiveEvidence =
        await captureActivePageMhtml(
          capture
        );

      pageArchiveStatus =
        (
          "mhtml: capturado · "
          + String(
              pageArchiveEvidence
                ?.blob
                ?.size
              || 0
            )
          + " bytes"
        );

    } catch (mhtmlCaptureError) {
      pageArchiveStatus =
        (
          "mhtml: ERROR · "
          + String(
              mhtmlCaptureError?.message
              || mhtmlCaptureError
            )
        );

      console.warn(
        "[QCC] MHTML capture:",
        mhtmlCaptureError
      );
    }


    try {
      backendResult =
        await submitSiteArchitectureCapture(
          capture
        );

      if (
        !backendResult
        || backendResult.ok !== true
      ) {
        throw new Error(
          "QCC_SITE_ARCHITECTURE_RESPONSE_INVALID"
        );
      }


      /*
       * QCC_VISUAL_VIEWPORT_ATTACHED
       *
       * El backend es autoridad del capture_id.
       * Solo después de recibirlo adjuntamos el PNG.
       *
       * Fallar aquí NO invalida la captura DOM.
       */
      if (
        viewportEvidence
        && backendResult.capture_id
      ) {
        try {
          const visualResult =
            await submitVisualArtifact(
              backendResult.capture_id,
              viewportEvidence
            );

          viewportStatus =
            (
              "viewport: GUARDADO · "
              + String(
                  visualResult?.bytes
                  || 0
                )
              + " bytes"
            );

          console.log(
            "[QCC] Visual Evidence viewport:",
            visualResult
          );

        } catch (visualUploadError) {
          viewportStatus =
            (
              "viewport: ERROR · "
              + String(
                  visualUploadError?.message
                  || visualUploadError
                )
            );

          console.warn(
            "[QCC] Visual Evidence upload:",
            visualUploadError
          );
        }
      }


      /*
       * QCC_PAGE_MHTML_ATTACHED_V1
       */
      if (
        pageArchiveEvidence
        && backendResult.capture_id
      ) {
        try {
          const pageArchiveResult =
            await submitPageArchiveArtifact(
              backendResult.capture_id,
              pageArchiveEvidence
            );

          pageArchiveStatus =
            (
              "mhtml: GUARDADO · "
              + String(
                  pageArchiveResult?.bytes
                  || 0
                )
              + " bytes"
            );

          console.log(
            "[QCC] Page MHTML:",
            pageArchiveResult
          );

        } catch (mhtmlUploadError) {
          pageArchiveStatus =
            (
              "mhtml: ERROR · "
              + String(
                  mhtmlUploadError?.message
                  || mhtmlUploadError
                )
            );

          console.warn(
            "[QCC] MHTML upload:",
            mhtmlUploadError
          );
        }
      }


      /*
       * Si la captura quedó ligada a una sesión
       * runtime y el backend devolvió targets
       * canónicos, armamos el listener pasivo
       * en el MISMO tab/document capturado.
       *
       * Fallar aquí NO rompe la inspección DOM:
       * simplemente no habrá aprendizaje causal.
       */
      try {
        const armResult =
          await armHumanListenerFromCapture(
            capture,
            backendResult
          );

        if (
          armResult
          && armResult.ok === true
          && armResult.armed === true
        ) {
          humanListenerStatus =
            "listener humano: ARMADO";

          console.log(
            "[QCC] Human listener ARMED:",
            armResult
          );

        } else {
          const armError =
            String(
              armResult?.error
              || "QCC_HUMAN_LISTENER_NOT_ARMED"
            );

          humanListenerStatus =
            (
              "listener humano: ERROR · "
              + armError
            );

          console.warn(
            "[QCC] Human listener:",
            armError,
            armResult
          );
        }

      } catch (listenerError) {
        const listenerErrorText =
          String(
            listenerError?.message
            || listenerError
          );

        humanListenerStatus =
          (
            "listener humano: ERROR · "
            + listenerErrorText
          );

        console.warn(
          "[QCC] Human listener:",
          listenerError
        );
      }

    } catch (error) {
      /*
       * Fail-open:
       * QCC debe seguir siendo útil incluso si
       * CRM/Bridge no está abierto o rechaza
       * la captura.
       */
      console.warn(
        "[QCC] Site Architecture backend:",
        error
      );

      saved =
        downloadDomCapture(
          capture
        );


      /*
       * El DOM ya dispone de fallback local.
       * Conservamos también el viewport si llegó
       * a capturarse antes de detectar que Bridge
       * no está disponible.
       */
      if (viewportEvidence) {
        try {
          const localVisual =
            downloadVisualEvidence(
              viewportEvidence,
              saved
            );

          viewportStatus =
            (
              "viewport: DESCARGADO · "
              + localVisual.filename
              + " · "
              + String(
                  localVisual.bytes
                  || 0
                )
              + " bytes"
            );

          console.log(
            "[QCC] Visual Evidence local fallback:",
            localVisual
          );

        } catch (visualFallbackError) {
          viewportStatus =
            (
              "viewport: ERROR · "
              + String(
                  visualFallbackError?.message
                  || visualFallbackError
                )
            );

          console.warn(
            "[QCC] Visual Evidence local fallback:",
            visualFallbackError
          );
        }
      }

      // QCC_PAGE_MHTML_LOCAL_DOWNLOAD_WIRED_V1
      if (pageArchiveEvidence) {
        try {
          const localMhtml =
            downloadPageArchive(
              pageArchiveEvidence,
              saved
            );

          pageArchiveStatus =
            (
              "mhtml: DESCARGADO · "
              + localMhtml.filename
              + " · "
              + String(
                  localMhtml.bytes
                  || 0
                )
              + " bytes"
            );

          console.log(
            "[QCC] MHTML local fallback:",
            localMhtml
          );

        } catch (mhtmlFallbackError) {
          pageArchiveStatus =
            (
              "mhtml: ERROR · "
              + String(
                  mhtmlFallbackError?.message
                  || mhtmlFallbackError
                )
            );

          console.warn(
            "[QCC] MHTML local fallback:",
            mhtmlFallbackError
          );
        }
      }

    }


    const mainFrame =
      (
        capture.frames
        || []
      ).find(
        (frame) =>
          frame?.frame_id === 0
      );


    const mainCounts =
      (
        mainFrame
        ?.result
        ?.counts
        || {}
      );


    if (backendResult) {
      const mode =
        backendResult.context_mode
        || "MANUAL";

      setText(
        "dom-inspect-feedback",
        (
          "Site Architecture integrada · "
          + `${capture.captured_frames} frame(s) · `
          + `${mainCounts.elements || 0} elementos · `
          + `${mode} · `
          + backendResult.capture_id
          + " · "
          + viewportStatus
          + " · "
          + pageArchiveStatus
          + " · "
          + humanListenerStatus
        )
      );

    } else {
      setText(
        "dom-inspect-feedback",
        (
          "Bridge no disponible · "
          + "captura guardada localmente · "
          + `${capture.captured_frames} frame(s) · `
          + `${mainCounts.elements || 0} elementos · `
          + viewportStatus
          + " · "
          + pageArchiveStatus
          + " · "
          + saved.filename
        )
      );
    }

  } catch (error) {
    console.error(
      "[QCC] DOM inspect:",
      error
    );

    const errorDetail =
      String(
        error?.message
        || error
        || "QCC_DOM_INSPECT_FAILED"
      );

    setText(
      "dom-inspect-feedback",
      (
        "No se pudo forzar la captura · "
        + errorDetail
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
    const domInspect =
      element(
        "tool-dom-inspect"
      );

    if (domInspect) {
      domInspect.addEventListener(
        "click",
        handleDomInspect
      );
    }


    const catalogExperiment =
      element(
        "tool-catalog-experiment"
      );


    if (catalogExperiment) {
      catalogExperiment.addEventListener(
        "click",
        handleCatalogExperiment
      );
    }


    const catalogRefresh =
      element(
        "tool-catalog-refresh"
      );

    if (catalogRefresh) {
      catalogRefresh.addEventListener(
        "click",
        () => {
          refreshCatalogBrowser()
            .catch(
              (error) => {
                setText(
                  "catalog-capture-feedback",
                  (
                    "Detección fallida · "
                    + String(
                        error?.message
                        || error
                      )
                  )
                );
              }
            );
        }
      );
    }


    const catalogCapture =
      element(
        "tool-catalog-capture"
      );

    if (catalogCapture) {
      catalogCapture.addEventListener(
        "click",
        handlePassiveCatalogCapture
      );
    }


    const catalogSourceSelect =
      element(
        "catalog-real-source-selector"
      );

    if (catalogSourceSelect) {
      catalogSourceSelect.addEventListener(
        "change",
        applyCatalogDependencySuggestion
      );
    }


    const catalogTargetSelect =
      element(
        "catalog-real-target-selector"
      );

    if (catalogTargetSelect) {
      catalogTargetSelect.addEventListener(
        "change",
        () => {
          updateCatalogRelationButtonState(
            true
          );
        }
      );
    }


    const catalogHarvest =
      element(
        "tool-catalog-harvest"
      );


    if (catalogHarvest) {
      catalogHarvest.addEventListener(
        "click",
        handleCatalogHarvest
      );
    }
  }
);


/*
 * ============================================================
 * QCC_ARCHITECTURE_MANAGER_RUNTIME_V1
 * ============================================================
 *
 * El gestor pertenece SIEMPRE al Chrome físico actual.
 *
 * Autoridad:
 * - qccOwnBrowserProfileKey;
 * - pestaña activa de currentWindow;
 * - QccArchitectureCapturePolicy.
 *
 * Nunca:
 * - usa qccViewedBrowserProfileKey como autoridad;
 * - concede permisos Chrome;
 * - depende del Bridge;
 * - inicia captura automática.
 */

async function qccArchitectureActiveTab() {
  const tabs =
    await chrome.tabs.query({
      active:
        true,

      currentWindow:
        true
    });

  return (
    tabs?.[0]
    || null
  );
}


function qccArchitecturePolicyApi() {
  return (
    globalThis
      ?.QccArchitectureCapturePolicy
    || null
  );
}


function qccArchitectureSetControlsEnabled(
  enabled
) {
  const normalized =
    enabled === true;

  for (
    const id
    of [
      "architecture-profile-default",
      "architecture-origin-allow",
      "architecture-origin-deny",
      "architecture-origin-inherit"
    ]
  ) {
    const control =
      element(
        id
      );

    if (control) {
      control.disabled =
        !normalized;
    }
  }
}


function renderArchitectureOriginList(
  origins
) {
  const container =
    element(
      "architecture-origin-list"
    );

  if (!container) {
    return;
  }

  container.replaceChildren();

  const entries =
    Array.isArray(
      origins
    )
      ? origins
      : [];

  if (entries.length === 0) {
    const empty =
      document.createElement(
        "div"
      );

    empty.className =
      "qcc-info-text";

    empty.textContent =
      "Sin webs configuradas para este perfil.";

    container.appendChild(
      empty
    );

    return;
  }

  for (const entry of entries) {
    const row =
      document.createElement(
        "div"
      );

    row.className =
      "qcc-architecture-origin-item";

    const origin =
      document.createElement(
        "span"
      );

    origin.className =
      "qcc-architecture-origin-value";

    origin.textContent =
      String(
        entry?.origin
        || "—"
      );

    const mode =
      document.createElement(
        "span"
      );

    mode.className =
      "qcc-architecture-origin-mode";

    mode.textContent =
      String(
        entry?.mode
        || "—"
      );

    row.append(
      origin,
      mode
    );

    container.appendChild(
      row
    );
  }
}


async function qccArchitectureOwnContext() {
  const policy =
    qccArchitecturePolicyApi();

  if (!policy) {
    throw new Error(
      "QCC_ARCH_POLICY_UNAVAILABLE"
    );
  }

  const profileKey =
    String(
      qccOwnBrowserProfileKey
      || ""
    ).trim();

  if (!profileKey) {
    return {
      profile_key:
        null,

      tab:
        null,

      url:
        null,

      origin:
        null,

      policy:
        policy
    };
  }

  const tab =
    await qccArchitectureActiveTab();

  const url =
    String(
      tab?.url
      || ""
    );

  const origin =
    policy.normalizeOrigin(
      url
    );

  return {
    profile_key:
      profileKey,

    tab:
      tab,

    url:
      url,

    origin:
      origin,

    policy:
      policy
  };
}


async function refreshArchitectureManager() {
  qccArchitectureSetControlsEnabled(
    false
  );

  setText(
    "architecture-current-profile",
    qccOwnBrowserProfileKey
      || "SIN VINCULAR"
  );

  setText(
    "architecture-current-origin",
    "—"
  );

  setText(
    "architecture-current-policy",
    "DESACTIVADA"
  );

  setText(
    "architecture-current-source",
    "—"
  );

  const context =
    await qccArchitectureOwnContext();

  const profileDefault =
    element(
      "architecture-profile-default"
    );

  if (!context.profile_key) {
    if (profileDefault) {
      profileDefault.checked =
        false;
    }

    renderArchitectureOriginList(
      []
    );

    setText(
      "architecture-policy-feedback",
      "Vincula este Chrome a un profile_key."
    );

    return;
  }

  /*
   * El gestor visual debe reflejar el modo real del OWN
   * profile si el Browser Registry ya lo conoce.
   */
  await qccSeedOwnArchitectureProfileDefault();

  const snapshot =
    await context.policy
      .snapshotForProfile(
        context.profile_key
      );

  if (profileDefault) {
    profileDefault.checked =
      snapshot
        ?.automatic_default
        === true;

    /*
     * El default del perfil puede gobernarse aunque
     * la pestaña actual no sea http/https.
     */
    profileDefault.disabled =
      false;
  }

  renderArchitectureOriginList(
    snapshot?.origins
    || []
  );

  setText(
    "architecture-current-profile",
    context.profile_key
  );

  if (!context.origin) {
    setText(
      "architecture-policy-feedback",
      "La pestaña actual no admite política por origin."
    );

    return;
  }

  const resolution =
    await context.policy.resolve(
      context.profile_key,
      context.url
    );

  setText(
    "architecture-current-origin",
    context.origin
  );

  setText(
    "architecture-current-policy",
    resolution
      ?.automatic_allowed
      === true
        ? "ACTIVADA"
        : "DESACTIVADA"
  );

  setText(
    "architecture-current-source",
    resolution?.source
    || "—"
  );

  for (
    const id
    of [
      "architecture-origin-allow",
      "architecture-origin-deny",
      "architecture-origin-inherit"
    ]
  ) {
    const control =
      element(
        id
      );

    if (control) {
      control.disabled =
        false;
    }
  }

  setText(
    "architecture-policy-feedback",
    (
      resolution
        ?.automatic_allowed
        === true
          ? "Captura automática autorizada."
          : "Captura automática no autorizada."
    )
  );
}


async function mutateArchitectureOriginPolicy(
  mutation
) {
  const context =
    await qccArchitectureOwnContext();

  if (
    !context.profile_key
    || !context.origin
  ) {
    throw new Error(
      "QCC_ARCH_POLICY_CONTEXT_INVALID"
    );
  }

  if (mutation === "ALLOW") {
    await context.policy.allowOrigin(
      context.profile_key,
      context.url
    );

  } else if (mutation === "DENY") {
    await context.policy.denyOrigin(
      context.profile_key,
      context.url
    );

  } else if (mutation === "INHERIT") {
    await context.policy.clearOriginOverride(
      context.profile_key,
      context.url
    );

  } else {
    throw new Error(
      "QCC_ARCH_POLICY_MUTATION_INVALID"
    );
  }

  await refreshArchitectureManager();
}


async function mutateArchitectureProfileDefault(
  enabled
) {
  const context =
    await qccArchitectureOwnContext();

  if (!context.profile_key) {
    throw new Error(
      "QCC_ARCH_POLICY_PROFILE_UNBOUND"
    );
  }

  await context.policy.setProfileDefault(
    context.profile_key,
    enabled === true
  );

  await refreshArchitectureManager();
}


function qccArchitectureReportError(
  error
) {
  setText(
    "architecture-policy-feedback",
    (
      "Gestión de Architecture detenida · "
      + String(
          error?.message
          || error
          || "QCC_ARCH_POLICY_FAILED"
        )
    )
  );
}


function initializeBrowserToolsDialog() {
  const dialog =
    element(
      "browser-tools-dialog"
    );

  const openButton =
    element(
      "tool-browser-tools-open"
    );

  const closeButton =
    element(
      "tool-browser-tools-close"
    );

  if (
    !dialog
    || !openButton
  ) {
    return;
  }

  openButton.addEventListener(
    "click",
    () => {
      if (
        typeof dialog.showModal
          === "function"
      ) {
        dialog.showModal();
      } else {
        dialog.setAttribute(
          "open",
          ""
        );
      }

      refreshArchitectureManager()
        .catch(
          qccArchitectureReportError
        );

      refreshCatalogBrowser()
        .catch(
          (error) => {
            setText(
              "catalog-capture-feedback",
              (
                "Detección fallida · "
                + String(
                    error?.message
                    || error
                  )
              )
            );
          }
        );
    }
  );

  const architectureDefault =
    element(
      "architecture-profile-default"
    );

  const architectureAllow =
    element(
      "architecture-origin-allow"
    );

  const architectureDeny =
    element(
      "architecture-origin-deny"
    );

  const architectureInherit =
    element(
      "architecture-origin-inherit"
    );


  if (architectureDefault) {
    architectureDefault.addEventListener(
      "change",
      () => {
        mutateArchitectureProfileDefault(
          architectureDefault.checked
        ).catch(
          qccArchitectureReportError
        );
      }
    );
  }


  if (architectureAllow) {
    architectureAllow.addEventListener(
      "click",
      () => {
        mutateArchitectureOriginPolicy(
          "ALLOW"
        ).catch(
          qccArchitectureReportError
        );
      }
    );
  }


  if (architectureDeny) {
    architectureDeny.addEventListener(
      "click",
      () => {
        mutateArchitectureOriginPolicy(
          "DENY"
        ).catch(
          qccArchitectureReportError
        );
      }
    );
  }


  if (architectureInherit) {
    architectureInherit.addEventListener(
      "click",
      () => {
        mutateArchitectureOriginPolicy(
          "INHERIT"
        ).catch(
          qccArchitectureReportError
        );
      }
    );
  }


  if (closeButton) {
    closeButton.addEventListener(
      "click",
      () => {
        if (
          typeof dialog.close
            === "function"
        ) {
          dialog.close();
        } else {
          dialog.removeAttribute(
            "open"
          );
        }
      }
    );
  }

  dialog.addEventListener(
    "click",
    (event) => {
      if (event.target === dialog) {
        dialog.close();
      }
    }
  );
}


document.addEventListener(
  "DOMContentLoaded",
  initializeBrowserToolsDialog
);
