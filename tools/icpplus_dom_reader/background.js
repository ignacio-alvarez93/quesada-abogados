const ENDPOINT =
  "http://127.0.0.1:8765/icpplus";


function isIcpUrl(url) {
  return (
    String(url || "").startsWith(
      "https://sede.administracionespublicas.gob.es/"
    ) ||
    String(url || "").startsWith(
      "https://icp.administracionelectronica.gob.es/"
    )
  );
}


function extensionDebug() {
  const manifest =
    chrome.runtime.getManifest();

  return {
    extensionId:
      chrome.runtime.id,

    extensionName:
      manifest.name,

    extensionVersion:
      manifest.version,

    backgroundBuild:
      "ICP_OBSERVER_BG_V6_PRIVACY_PROOF"
  };
}


function sourceFromSender(sender) {
  const tab =
    sender && sender.tab
      ? sender.tab
      : null;

  return {
    tabId:
      tab && Number.isInteger(tab.id)
        ? tab.id
        : null,

    windowId:
      tab && Number.isInteger(tab.windowId)
        ? tab.windowId
        : null,

    frameId:
      sender && Number.isInteger(sender.frameId)
        ? sender.frameId
        : null
  };
}



// ======================================================
// PRIVACY CONTRACT
// ======================================================
//
// Los campos personales NO salen hacia localhost en claro.
//
// El content/semantic script puede observar element.value
// dentro de la propia extensión, pero background.js lo
// sustituye ANTES del fetch HTTP por una prueba HMAC.
//
// El secreto es el token efímero qa_observer de la ejecución.
// ======================================================

const PRIVACY_CONTRACT_VERSION = 1;

const SENSITIVE_CONTROL_KEYS = new Set([
  "identityNie",
  "identityName",
  "phone",
  "email",
  "emailRepeat"
]);


function runTokenStorageKey(tabId) {
  return (
    "icpplus_run_token_tab_"
    + String(tabId)
  );
}


function extractRunToken(url) {
  try {
    const parsed =
      new URL(String(url || ""));

    const hash =
      String(parsed.hash || "")
        .replace(/^#/, "");

    const params =
      new URLSearchParams(hash);

    return (
      params.get("qa_observer")
      || null
    );
  } catch (_) {
    return null;
  }
}


async function rememberOrLoadRunToken(
  payload,
  observerSource
) {
  const tabId =
    observerSource &&
    Number.isInteger(
      observerSource.tabId
    )
      ? observerSource.tabId
      : null;

  if (tabId === null) {
    return null;
  }

  const key =
    runTokenStorageKey(tabId);

  const fromUrl =
    extractRunToken(
      payload && payload.url
    );

  if (fromUrl) {
    await chrome.storage.session.set({
      [key]: fromUrl
    });

    return fromUrl;
  }

  const stored =
    await chrome.storage.session.get(
      key
    );

  return (
    stored[key]
    || null
  );
}


async function hmacSha256Hex(
  secret,
  value
) {
  const encoder =
    new TextEncoder();

  const key =
    await crypto.subtle.importKey(
      "raw",
      encoder.encode(secret),
      {
        name: "HMAC",
        hash: "SHA-256"
      },
      false,
      ["sign"]
    );

  const signature =
    await crypto.subtle.sign(
      "HMAC",
      key,
      encoder.encode(
        String(value ?? "")
      )
    );

  return Array.from(
    new Uint8Array(signature)
  )
    .map(
      byte =>
        byte
          .toString(16)
          .padStart(2, "0")
    )
    .join("");
}


async function privacySafePayload(
  payload,
  observerSource
) {
  const safePayload = {
    ...payload
  };

  const controls =
    payload &&
    payload.navigationControls &&
    typeof payload.navigationControls === "object"
      ? payload.navigationControls
      : null;

  if (!controls) {
    return safePayload;
  }

  const runToken =
    await rememberOrLoadRunToken(
      payload,
      observerSource
    );

  const safeControls = {
    ...controls
  };


  for (
    const controlKey
    of SENSITIVE_CONTROL_KEYS
  ) {
    const original =
      controls[controlKey];

    if (
      !original ||
      typeof original !== "object"
    ) {
      continue;
    }

    const safeControl = {
      ...original
    };

    if (
      Object.prototype.hasOwnProperty.call(
        original,
        "value"
      )
    ) {
      const rawValue =
        String(
          original.value ?? ""
        );

      safeControl.hasValue =
        rawValue.length > 0;

      safeControl.valueLength =
        rawValue.length;

      safeControl.valueProof =
        runToken
          ? await hmacSha256Hex(
              runToken,
              rawValue
            )
          : null;

      delete safeControl.value;
    }

    safeControls[controlKey] =
      safeControl;
  }


  safePayload.navigationControls =
    safeControls;

  return safePayload;
}


async function postEvent(
  payload,
  observerSource
) {
  const safePayload =
    await privacySafePayload(
      payload,
      observerSource
    );

  const body = {
    ...safePayload,

    privacyContractVersion:
      PRIVACY_CONTRACT_VERSION,

    observerSource:
      observerSource || {
        tabId: null,
        windowId: null,
        frameId: null
      },

    extensionDebug:
      extensionDebug()
  };

  try {
    await fetch(
      ENDPOINT,
      {
        method: "POST",

        headers: {
          "Content-Type":
            "application/json"
        },

        body:
          JSON.stringify(body)
      }
    );
  } catch (_) {
    // Listener Python puede estar cerrado.
  }
}


chrome.runtime.onMessage.addListener(
  (
    message,
    sender
  ) => {

    if (
      !message ||
      message.type !== "ICP_OBSERVER_EVENT"
    ) {
      return;
    }

    postEvent(
      message.payload,
      sourceFromSender(sender)
    );
  }
);


// ======================================================
// ERRORES DE NAVEGACIÓN SIN DOM
// ======================================================

const DOWN_ERRORS = new Set([
  "net::ERR_CONNECTION_TIMED_OUT",
  "net::ERR_CONNECTION_REFUSED",
  "net::ERR_CONNECTION_RESET",
  "net::ERR_NAME_NOT_RESOLVED",
  "net::ERR_INTERNET_DISCONNECTED",
  "net::ERR_NETWORK_CHANGED"
]);


chrome.webNavigation.onErrorOccurred.addListener(
  (details) => {

    if (
      details.frameId !== 0 ||
      !isIcpUrl(details.url)
    ) {
      return;
    }

    // Muy frecuente durante navegación normal.
    // No representa caída del portal.
    if (
      details.error === "net::ERR_ABORTED"
    ) {
      return;
    }

    const portalStatus =
      DOWN_ERRORS.has(details.error)
        ? "DOWN"
        : "UNKNOWN";

    postEvent(
      {
        schemaVersion: 4,

        eventType:
          "NAVIGATION_ERROR",

        capturedAt:
          new Date().toISOString(),

        url:
          details.url,

        portalStatus,

        availabilityStatus:
          "UNKNOWN",

        navigationError:
          details.error
      },
      {
        tabId:
          Number.isInteger(details.tabId)
            ? details.tabId
            : null,

        // webNavigation no aporta windowId directamente.
        // tabId ya identifica inequívocamente la pestaña
        // que hemos vinculado durante LANDING.
        windowId: null,

        frameId:
          details.frameId
      }
    );
  }
);
