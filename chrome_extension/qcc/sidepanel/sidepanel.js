const QCC_BRIDGE_HEALTH_URL =
  "http://127.0.0.1:8766/qcc/health";

const QCC_HEALTH_INTERVAL_MS = 2000;
const QCC_HEALTH_TIMEOUT_MS = 1200;


function setBridgeState(
  connected,
  description
) {
  const dot =
    document.getElementById(
      "bridge-dot"
    );

  const status =
    document.getElementById(
      "bridge-status"
    );

  const detail =
    document.getElementById(
      "bridge-description"
    );

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

  if (status) {
    status.textContent =
      connected
        ? "CRM conectado"
        : "CRM desconectado";
  }

  if (detail) {
    detail.textContent =
      description;
  }
}


async function checkBridgeHealth() {
  const controller =
    new AbortController();

  const timeoutId =
    setTimeout(
      () => controller.abort(),
      QCC_HEALTH_TIMEOUT_MS
    );

  try {
    const response =
      await fetch(
        QCC_BRIDGE_HEALTH_URL,
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

    const payload =
      await response.json();

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
  } catch (_) {
    setBridgeState(
      false,
      "QCC Bridge todavía no está disponible."
    );
  } finally {
    clearTimeout(
      timeoutId
    );
  }
}


function initializeQccShell() {
  const manifest =
    chrome.runtime.getManifest();

  const versionElement =
    document.getElementById(
      "qcc-version"
    );

  if (versionElement) {
    versionElement.textContent =
      `QCC ${manifest.version}`;
  }

  const buildElement =
    document.getElementById(
      "qcc-build"
    );

  if (buildElement) {
    buildElement.textContent =
      "Bridge Health";
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
