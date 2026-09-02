/*
 * QCC_ACQUISITION_POLICY_V1
 *
 * Autoridad compartida Side Panel / Service Worker.
 *
 * Independiente de:
 * - CRM;
 * - Bridge;
 * - SiteInteractionPolicy.
 *
 * Seguridad:
 * - DEFAULT = SNAPSHOT_ONLY;
 * - una web desconocida nunca obtiene harvest automáticamente;
 * - un provider puede bloquear un origin;
 * - el opt-in de harvest vive solo en chrome.storage.session;
 * - un bloqueo provider no puede elevarse mediante opt-in.
 */

(() => {
  if (globalThis.QccAcquisitionPolicy) {
    return;
  }


  const SNAPSHOT_ONLY =
    "SNAPSHOT_ONLY";

  const HARVEST_ALLOWED =
    "HARVEST_ALLOWED";

  const SESSION_STORAGE_KEY =
    "qcc:acquisition:harvest-origins:v1";


  const providerPolicies =
    new Map();


  function normalizeOrigin(
    value
  ) {
    try {
      const parsed =
        new URL(
          String(
            value
            || ""
          )
        );

      if (
        parsed.protocol !== "http:"
        && parsed.protocol !== "https:"
      ) {
        return null;
      }

      return parsed.origin;

    } catch (_) {
      return null;
    }
  }


  function register(
    registration
  ) {
    const origin =
      normalizeOrigin(
        registration?.origin
      );

    const mode =
      String(
        registration?.mode
        || ""
      )
        .trim()
        .toUpperCase();

    if (!origin) {
      throw new Error(
        "QCC_ACQUISITION_ORIGIN_INVALID"
      );
    }

    if (
      mode !== SNAPSHOT_ONLY
      && mode !== HARVEST_ALLOWED
    ) {
      throw new Error(
        "QCC_ACQUISITION_MODE_INVALID"
      );
    }

    providerPolicies.set(
      origin,
      {
        origin:
          origin,

        mode:
          mode,

        locked:
          registration?.locked === true,

        source:
          String(
            registration?.source
            || "PROVIDER"
          )
      }
    );

    return true;
  }


  function invalidPolicy() {
    return {
      mode:
        SNAPSHOT_ONLY,

      allowed:
        false,

      locked:
        true,

      origin:
        null,

      source:
        "INVALID_URL"
    };
  }


  function providerPolicyForOrigin(
    origin
  ) {
    return (
      providerPolicies.get(
        origin
      )
      || null
    );
  }


  function resolvedProviderPolicy(
    policy
  ) {
    return {
      ...policy,

      allowed:
        (
          policy.mode
          === HARVEST_ALLOWED
        )
    };
  }


  function sessionStorage() {
    const storage =
      globalThis
        ?.chrome
        ?.storage
        ?.session;

    if (!storage) {
      throw new Error(
        "QCC_ACQUISITION_SESSION_STORAGE_UNAVAILABLE"
      );
    }

    return storage;
  }


  async function readSessionOrigins() {
    const result =
      await sessionStorage().get(
        SESSION_STORAGE_KEY
      );

    const raw =
      result?.[
        SESSION_STORAGE_KEY
      ];

    return new Set(
      (
        Array.isArray(raw)
        ? raw
        : []
      )
        .map(
          normalizeOrigin
        )
        .filter(Boolean)
    );
  }


  async function writeSessionOrigins(
    origins
  ) {
    await sessionStorage().set({
      [SESSION_STORAGE_KEY]:
        Array.from(
          origins
        ).sort()
    });
  }


  async function resolve(
    url
  ) {
    const origin =
      normalizeOrigin(
        url
      );

    if (!origin) {
      return invalidPolicy();
    }

    const providerPolicy =
      providerPolicyForOrigin(
        origin
      );

    /*
     * El bloqueo provider es autoridad absoluta.
     */
    if (
      providerPolicy
      && providerPolicy.locked === true
    ) {
      return resolvedProviderPolicy(
        providerPolicy
      );
    }


    let sessionOrigins;

    try {
      sessionOrigins =
        await readSessionOrigins();

    } catch (_) {
      /*
       * Fail-closed:
       * si no podemos conocer el opt-in,
       * nunca concedemos HARVEST.
       */
      if (providerPolicy) {
        return resolvedProviderPolicy(
          providerPolicy
        );
      }

      return {
        mode:
          SNAPSHOT_ONLY,

        allowed:
          false,

        locked:
          false,

        origin:
          origin,

        source:
          "DEFAULT"
      };
    }


    if (
      sessionOrigins.has(
        origin
      )
    ) {
      return {
        mode:
          HARVEST_ALLOWED,

        allowed:
          true,

        locked:
          false,

        origin:
          origin,

        source:
          "SESSION_OPT_IN"
      };
    }


    if (providerPolicy) {
      return resolvedProviderPolicy(
        providerPolicy
      );
    }


    return {
      mode:
        SNAPSHOT_ONLY,

      allowed:
        false,

      locked:
        false,

      origin:
        origin,

      source:
        "DEFAULT"
    };
  }


  async function enableHarvestForUrl(
    url
  ) {
    const origin =
      normalizeOrigin(
        url
      );

    if (!origin) {
      return {
        ok:
          false,

        enabled:
          false,

        reason:
          "QCC_ACQUISITION_ORIGIN_INVALID",

        policy:
          invalidPolicy()
      };
    }


    const providerPolicy =
      providerPolicyForOrigin(
        origin
      );

    if (
      providerPolicy
      && providerPolicy.locked === true
      && providerPolicy.mode
        === SNAPSHOT_ONLY
    ) {
      return {
        ok:
          false,

        enabled:
          false,

        reason:
          "QCC_ACQUISITION_LOCKED_SNAPSHOT_ONLY",

        policy:
          resolvedProviderPolicy(
            providerPolicy
          )
      };
    }


    try {
      const origins =
        await readSessionOrigins();

      origins.add(
        origin
      );

      await writeSessionOrigins(
        origins
      );

    } catch (_) {
      return {
        ok:
          false,

        enabled:
          false,

        reason:
          "QCC_ACQUISITION_SESSION_STORAGE_UNAVAILABLE",

        policy:
          await resolve(
            url
          )
      };
    }


    return {
      ok:
        true,

      enabled:
        true,

      policy:
        await resolve(
          url
        )
    };
  }


  async function disableHarvestForUrl(
    url
  ) {
    const origin =
      normalizeOrigin(
        url
      );

    if (!origin) {
      return {
        ok:
          false,

        enabled:
          false,

        reason:
          "QCC_ACQUISITION_ORIGIN_INVALID",

        policy:
          invalidPolicy()
      };
    }


    try {
      const origins =
        await readSessionOrigins();

      origins.delete(
        origin
      );

      await writeSessionOrigins(
        origins
      );

    } catch (_) {
      return {
        ok:
          false,

        enabled:
          false,

        reason:
          "QCC_ACQUISITION_SESSION_STORAGE_UNAVAILABLE",

        policy:
          await resolve(
            url
          )
      };
    }


    return {
      ok:
        true,

      enabled:
        false,

      policy:
        await resolve(
          url
        )
    };
  }


  globalThis.QccAcquisitionPolicy =
    Object.freeze({
      SNAPSHOT_ONLY:
        SNAPSHOT_ONLY,

      HARVEST_ALLOWED:
        HARVEST_ALLOWED,

      register:
        register,

      resolve:
        resolve,

      enableHarvestForUrl:
        enableHarvestForUrl,

      disableHarvestForUrl:
        disableHarvestForUrl
    });
})();
