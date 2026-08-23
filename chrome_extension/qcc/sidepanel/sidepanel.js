const QCC_BRIDGE_BASE_URL =
  "http://127.0.0.1:8766";

const QCC_BRIDGE_HEALTH_URL =
  `${QCC_BRIDGE_BASE_URL}/qcc/health`;

const QCC_CONTEXT_URL =
  `${QCC_BRIDGE_BASE_URL}/qcc/context`;

const QCC_SITE_ARCHITECTURE_CAPTURE_URL =
  `${QCC_BRIDGE_BASE_URL}/qcc/site-architecture/capture`;

const QCC_HEALTH_INTERVAL_MS = 2000;
const QCC_REQUEST_TIMEOUT_MS = 1200;

const QCC_SITE_ARCHITECTURE_REQUEST_TIMEOUT_MS =
  30000;

let qccActiveSessionId = null;

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


async function submitSiteArchitectureCapture(
  capture
) {
  return await postJson(
    QCC_SITE_ARCHITECTURE_CAPTURE_URL,
    {
      protocol_version: 1,
      capture
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
    qccActiveSessionId;

  if (!sessionId) {
    throw new Error(
      "QCC_SESSION_NOT_AVAILABLE"
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


function showEmptyContext(
  title = "Sin actividad en curso",
  description = (
    "Cuando una presentación o automatización "
    + "se conecte a QCC, aparecerá aquí su contexto."
  )
) {
  qccActiveSessionId = null;

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
  qccActiveSessionId =
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

  const canStartDocuments =
    (
      requiresUserAction
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
      requiresUserAction
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
        + "elige cómo debe continuar Mercurio."
      )
    );

  } else if (canStartDocuments) {
    setText(
      "user-action-text",
      (
        "Mercurio está preparado para "
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
}


async function checkContext() {
  try {
    const context =
      await fetchJson(
        QCC_CONTEXT_URL
      );

    renderContext(context);
  } catch (_) {
    showEmptyContext(
      "Contexto no disponible",
      "No se pudo leer el estado de la presentación."
    );
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
    setBridgeState(
      false,
      "QCC Bridge todavía no está disponible."
    );

    showEmptyContext();
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



function initializeQccShell() {
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

  checkBridgeHealth();

  window.setInterval(
    checkBridgeHealth,
    QCC_HEALTH_INTERVAL_MS
  );
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


const QCC_DOM_OPTIONAL_ORIGINS = [
  "http://*/*",
  "https://*/*"
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
      origins:
        QCC_DOM_OPTIONAL_ORIGINS
    });

  return Boolean(
    granted
  );
}


function downloadVisualStyleProbe(
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
      [serialized],
      {
        type:
          "application/json"
      }
    );

  const url =
    URL.createObjectURL(
      blob
    );

  const anchor =
    document.createElement(
      "a"
    );

  const stamp =
    new Date()
      .toISOString()
      .replaceAll(
        ":",
        "-"
      );

  const filename =
    (
      "qcc_visual_probe_"
      + stamp
      + ".json"
    );

  anchor.href =
    url;

  anchor.download =
    filename;

  anchor.click();

  URL.revokeObjectURL(
    url
  );

  return {
    filename
  };
}


async function handleVisualStyleProbe() {
  const button =
    element(
      "tool-visual-style-probe"
    );

  const input =
    element(
      "tool-visual-selectors"
    );

  if (
    !button
    || !input
  ) {
    return;
  }

  button.disabled =
    true;

  setText(
    "visual-style-feedback",
    "Preparando sonda visual..."
  );

  try {
    /*
     * Primera operación privilegiada:
     * mantenemos el mismo modelo de permisos
     * que Arquitectura DOM.
     */
    const permissionGranted =
      await requestDomInspectionPermission();

    if (!permissionGranted) {
      throw new Error(
        "QCC_DOM_HOST_PERMISSION_DENIED"
      );
    }

    const selectors =
      String(
        input.value
        || ""
      )
        .split(
          /\r?\n/
        )
        .map(
          (selector) =>
            selector.trim()
        )
        .filter(
          Boolean
        )
        .slice(
          0,
          50
        );

    if (
      selectors.length === 0
    ) {
      throw new Error(
        "QCC_VISUAL_SELECTORS_EMPTY"
      );
    }

    setText(
      "visual-style-feedback",
      (
        "Leyendo estilos de "
        + `${selectors.length} selector(es)...`
      )
    );

    const capture =
      await chrome.runtime.sendMessage({
        type:
          "QCC_VISUAL_STYLE_PROBE",

        selectors
      });

    if (
      !capture
      || capture.ok !== true
      || !capture.result
    ) {
      throw new Error(
        capture?.error
        || "QCC_VISUAL_STYLE_PROBE_INVALID"
      );
    }

    const elements =
      capture.result.elements
      || [];

    const found =
      elements.filter(
        (item) =>
          item?.found === true
      ).length;

    const saved =
      downloadVisualStyleProbe(
        capture
      );

    setText(
      "visual-style-feedback",
      (
        "Sonda visual completada · "
        + `${found}/${selectors.length} encontrados · `
        + saved.filename
      )
    );

  } catch (error) {
    console.error(
      "[QCC] Visual style probe:",
      error
    );

    setText(
      "visual-style-feedback",
      (
        "No se pudo leer estilos · "
        + String(
            error?.message
            || error
            || "QCC_VISUAL_STYLE_PROBE_FAILED"
          )
      )
    );

  } finally {
    button.disabled =
      false;
  }
}


function buildAutomaticVisualSelectors(
  capture
) {
  const mainFrame =
    (
      capture.frames
      || []
    ).find(
      (frame) =>
        frame?.frame_id === 0
    );

  const elements =
    (
      mainFrame
      ?.result
      ?.elements
      || []
    );

  const candidates = [];
  const seen = new Set();


  function addCandidate(
    selector,
    score,
    index
  ) {
    if (
      !selector
      || seen.has(selector)
    ) {
      return;
    }

    seen.add(
      selector
    );

    candidates.push({
      selector,
      score,
      index
    });
  }


  elements.forEach(
    (
      item,
      index
    ) => {
      if (
        item?.visible !== true
      ) {
        return;
      }

      const tag =
        String(
          item.tag
          || ""
        ).toLowerCase();

      const id =
        String(
          item.id
          || ""
        ).trim();

      const attributes =
        item.attributes
        || {};

      const rect =
        item.rect
        || {};

      let score = 0;

      if (
        [
          "input",
          "select",
          "textarea"
        ].includes(tag)
      ) {
        score = 100;

      } else if (
        [
          "button",
          "a"
        ].includes(tag)
      ) {
        score = 95;

      } else if (
        [
          "h1",
          "h2",
          "h3",
          "h4",
          "h5",
          "h6"
        ].includes(tag)
      ) {
        score = 90;

      } else if (
        [
          "form",
          "fieldset",
          "section",
          "main",
          "nav",
          "header",
          "footer"
        ].includes(tag)
      ) {
        score = 80;

      } else {
        score = 50;
      }


      if (
        Number(rect.width || 0) >= 300
        || Number(rect.height || 0) >= 80
      ) {
        score += 10;
      }


      /*
       * IDs CSS simples cubren la enorme mayoría
       * de sedes administrativas y evitan tener
       * que generar selectores frágiles.
       */
      if (
        id
        && /^[A-Za-z_][A-Za-z0-9_-]*$/.test(
          id
        )
      ) {
        addCandidate(
          `#${id}`,
          score,
          index
        );
      }


      /*
       * Los labels suelen carecer de ID.
       * Cuando tienen for="" podemos capturar
       * su tipografía/estilo de forma estable.
       */
      if (
        tag === "label"
      ) {
        const target =
          String(
            attributes.for
            || ""
          ).trim();

        if (
          target
          && /^[A-Za-z_][A-Za-z0-9_-]*$/.test(
            target
          )
        ) {
          addCandidate(
            `label[for="${target}"]`,
            98,
            index
          );
        }
      }
    }
  );


  /*
   * Elementos tipográficos estructurales
   * aunque no posean ID.
   */
  for (
    const tag
    of [
      "h1",
      "h2",
      "h3",
      "h4"
    ]
  ) {
    if (
      elements.some(
        (item) =>
          item?.visible === true
          && String(
            item.tag
            || ""
          ).toLowerCase() === tag
      )
    ) {
      addCandidate(
        tag,
        85,
        -1
      );
    }
  }


  return candidates
    .sort(
      (left, right) =>
        (
          right.score
          - left.score
        )
        || (
          left.index
          - right.index
        )
    )
    .slice(
      0,
      50
    )
    .map(
      (item) =>
        item.selector
    );
}


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
    "Leyendo DOM de la pestaña activa..."
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
      "Permiso concedido · leyendo DOM..."
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


    /*
     * Segunda capa de la captura:
     * estilos visuales únicamente sobre una
     * muestra automática y acotada.
     *
     * Fail-open: un fallo visual nunca debe
     * impedir Site Architecture.
     */
    try {
      const visualSelectors =
        buildAutomaticVisualSelectors(
          capture
        );

      if (
        visualSelectors.length > 0
      ) {
        setText(
          "dom-inspect-feedback",
          (
            "DOM leído · analizando "
            + `${visualSelectors.length} `
            + "elementos visuales..."
          )
        );

        const visualProbe =
          await chrome.runtime.sendMessage({
            type:
              "QCC_VISUAL_STYLE_PROBE",

            selectors:
              visualSelectors
          });

        if (
          visualProbe
          && visualProbe.ok === true
          && visualProbe.result
        ) {
          capture.visual_probe =
            visualProbe.result;
        }
      }

    } catch (error) {
      console.warn(
        "[QCC] Automatic visual probe:",
        error
      );
    }


    let backendResult = null;
    let saved = null;

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


    const visualFound =
      (
        capture.visual_probe
        ?.elements
        || []
      ).filter(
        (item) =>
          item?.found === true
      ).length;


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
          + `${visualFound} estilos · `
          + `${mode} · `
          + backendResult.capture_id
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
          + `${visualFound} estilos · `
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
        "No se pudo inspeccionar esta pestaña · "
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

    const visualStyleProbe =
      element(
        "tool-visual-style-probe"
      );

    if (visualStyleProbe) {
      visualStyleProbe.addEventListener(
        "click",
        handleVisualStyleProbe
      );
    }
  }
);
