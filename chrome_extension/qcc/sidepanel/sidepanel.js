const QCC_BRIDGE_BASE_URL =
  "http://127.0.0.1:8766";

const QCC_BRIDGE_HEALTH_URL =
  `${QCC_BRIDGE_BASE_URL}/qcc/health`;

const QCC_CONTEXT_URL =
  `${QCC_BRIDGE_BASE_URL}/qcc/context`;

const QCC_SITE_ARCHITECTURE_CAPTURE_URL =
  `${QCC_BRIDGE_BASE_URL}/qcc/site-architecture/capture`;

const QCC_CATALOG_EXPERIMENT_URL =
  `${QCC_BRIDGE_BASE_URL}`
  + "/qcc/site-architecture/catalog-experiment";

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
      "tool-mercurio-real-harvest"
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
      "mercurio-real-harvest-feedback",
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
      "tool-mercurio-real-harvest"
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
      "mercurio-real-harvest-feedback",
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
      "mercurio-real-harvest-feedback",
      (
        `${candidates.length} dependencias detectadas`
        + " · selecciona destino"
      )
    );

    return;
  }

  setText(
    "mercurio-real-harvest-feedback",
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


async function handleMercurioRealCatalogHarvest() {
  const button =
    element(
      "tool-mercurio-real-harvest"
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
      "mercurio-real-harvest-feedback",
      "Faltan selectores de catálogo."
    );

    return;
  }

  if (
    sourceSelector
      === targetSelector
  ) {
    setText(
      "mercurio-real-harvest-feedback",
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
      "mercurio-real-harvest-feedback",
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
        "mercurio-real-harvest-feedback",
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
        "mercurio-real-harvest-feedback",
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
      "mercurio-real-harvest-feedback",
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
      "mercurio-real-harvest-feedback",
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


    const mercurioRealHarvest =
      element(
        "tool-mercurio-real-harvest"
      );


    if (mercurioRealHarvest) {
      mercurioRealHarvest.addEventListener(
        "click",
        handleMercurioRealCatalogHarvest
      );
    }


    const mercurioRealCatalog =
      element(
        "tool-mercurio-real-catalog"
      );


    if (mercurioRealCatalog) {
      mercurioRealCatalog.addEventListener(
        "click",
        handleMercurioRealCatalogProbe
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
