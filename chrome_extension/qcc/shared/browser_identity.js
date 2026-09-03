/*
 * QCC_BROWSER_IDENTITY_V1
 *
 * Identidad lógica persistente del Chrome/profile
 * que ejecuta esta instancia de QCC.
 *
 * Autoridad:
 * - browser_profile_key;
 * - persistido en chrome.storage.local;
 * - compartido Side Panel / Service Worker.
 *
 * IMPORTANTE:
 * - no genera UUID;
 * - no inventa profile_key;
 * - no usa tabId/windowId como identidad;
 * - no deriva identidad de URL/provider;
 * - un perfil no vinculado devuelve null;
 * - read() es fail-open para no romper capturas existentes.
 */

(() => {
  if (globalThis.QccBrowserIdentity) {
    return;
  }


  const STORAGE_KEY =
    "qcc:browser-profile-key:v1";


  function normalize(
    value
  ) {
    const normalized =
      String(
        value
        || ""
      ).trim();

    if (!normalized) {
      return null;
    }

    if (
      normalized.length > 128
      || /[\u0000-\u001f\u007f]/.test(
          normalized
        )
    ) {
      return null;
    }

    return normalized;
  }


  function localStorageArea() {
    const storage =
      globalThis
        ?.chrome
        ?.storage
        ?.local;

    if (!storage) {
      throw new Error(
        "QCC_BROWSER_IDENTITY_LOCAL_STORAGE_UNAVAILABLE"
      );
    }

    return storage;
  }


  async function read() {
    try {
      const stored =
        await localStorageArea().get(
          STORAGE_KEY
        );

      return normalize(
        stored?.[
          STORAGE_KEY
        ]
      );

    } catch (_) {
      /*
       * Identidad auxiliar:
       * si storage no está disponible, no debe
       * romper Force Capture ni captura automática.
       *
       * Backend mantendrá temporalmente el
       * comportamiento legacy.
       */
      return null;
    }
  }


  async function bind(
    profileKey
  ) {
    const normalized =
      normalize(
        profileKey
      );

    if (!normalized) {
      throw new Error(
        "QCC_BROWSER_PROFILE_KEY_INVALID"
      );
    }

    const storage =
      localStorageArea();

    await storage.set({
      [STORAGE_KEY]:
        normalized
    });

    return normalized;
  }


  async function clear() {
    const storage =
      localStorageArea();

    await storage.remove(
      STORAGE_KEY
    );

    return true;
  }


  globalThis.QccBrowserIdentity = {
    schema_version:
      1,

    storage_key:
      STORAGE_KEY,

    normalize,
    read,
    bind,
    clear
  };
})();
