/*
 * QCC_ARCHITECTURE_CAPTURE_POLICY_V1
 *
 * Gobierno persistente de captura automática
 * de QCC Site Architecture.
 *
 * Identidad:
 *   browser_profile_key + origin
 *
 * Separado deliberadamente de:
 * - AcquisitionPolicy / Harvest;
 * - SiteInteractionPolicy;
 * - permisos Chrome;
 * - Bridge;
 * - fingerprint funcional.
 *
 * Precedencia:
 *   DENY > ALLOW > profile automatic_default
 *
 * Seguridad:
 * - perfil desconocido => OFF;
 * - profile_key inválido => OFF;
 * - URL inválida => OFF;
 * - error de storage => OFF;
 * - ninguna heurística por nombre de perfil.
 */

(() => {
  if (
    globalThis
      .QccArchitectureCapturePolicy
  ) {
    return;
  }


  const SCHEMA_VERSION = 1;

  const STORAGE_KEY =
    "qcc:architecture:capture-policy:v1";

  const ORIGIN_ALLOW =
    "ALLOW";

  const ORIGIN_DENY =
    "DENY";


  function normalizeProfileKey(
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


  function normalizeBrowserSessionMode(
    value
  ) {
    const normalized =
      String(
        value
        || ""
      )
        .trim()
        .toUpperCase();

    if (
      normalized !== "ASSISTED"
      && normalized !== "PERSISTENT"
      && normalized !== "EPHEMERAL"
    ) {
      return null;
    }

    return normalized;
  }


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


  function storageArea() {
    const storage =
      globalThis
        ?.chrome
        ?.storage
        ?.local;

    if (!storage) {
      throw new Error(
        "QCC_ARCH_CAPTURE_STORAGE_UNAVAILABLE"
      );
    }

    return storage;
  }


  function emptyState() {
    return {
      schema_version:
        SCHEMA_VERSION,

      profiles:
        {}
    };
  }


  function sanitizeState(
    raw
  ) {
    const state =
      emptyState();

    const profiles =
      raw?.profiles;

    if (
      !profiles
      || typeof profiles !== "object"
      || Array.isArray(profiles)
    ) {
      return state;
    }


    for (
      const [
        rawProfileKey,
        rawProfile
      ]
      of Object.entries(profiles)
    ) {
      const profileKey =
        normalizeProfileKey(
          rawProfileKey
        );

      if (
        !profileKey
        || !rawProfile
        || typeof rawProfile
          !== "object"
        || Array.isArray(rawProfile)
      ) {
        continue;
      }

      const origins = {};

      const rawOrigins =
        rawProfile.origins;

      if (
        rawOrigins
        && typeof rawOrigins
          === "object"
        && !Array.isArray(
            rawOrigins
          )
      ) {
        for (
          const [
            rawOrigin,
            rawMode
          ]
          of Object.entries(
            rawOrigins
          )
        ) {
          const origin =
            normalizeOrigin(
              rawOrigin
            );

          const mode =
            String(
              rawMode
              || ""
            )
              .trim()
              .toUpperCase();

          if (
            origin
            && (
              mode === ORIGIN_ALLOW
              || mode === ORIGIN_DENY
            )
          ) {
            origins[
              origin
            ] = mode;
          }
        }
      }


      const hasInitializationMarker =
        Object.prototype
          .hasOwnProperty
          .call(
            rawProfile,
            "default_initialized"
          );

      const defaultInitialized =
        hasInitializationMarker
          ? rawProfile
              .default_initialized
              === true
          : true;

      let defaultSource =
        String(
          rawProfile
            .default_source
          || ""
        )
          .trim()
          .toUpperCase();

      if (!hasInitializationMarker) {
        defaultSource =
          "LEGACY";

      } else if (
        !defaultInitialized
      ) {
        defaultSource =
          "UNINITIALIZED";

      } else if (
        ![
          "MANUAL",
          "MODE_ASSISTED",
          "MODE_PERSISTENT",
          "MODE_EPHEMERAL",
          "LEGACY"
        ].includes(
          defaultSource
        )
      ) {
        defaultSource =
          "LEGACY";
      }


      state.profiles[
        profileKey
      ] = {
        automatic_default:
          rawProfile
            .automatic_default
            === true,

        default_initialized:
          defaultInitialized,

        default_source:
          defaultSource,

        origins:
          origins
      };
    }

    return state;
  }


  async function readState() {
    const result =
      await storageArea().get(
        STORAGE_KEY
      );

    return sanitizeState(
      result?.[
        STORAGE_KEY
      ]
    );
  }


  async function writeState(
    state
  ) {
    const sanitized =
      sanitizeState(
        state
      );

    await storageArea().set({
      [STORAGE_KEY]:
        sanitized
    });

    return sanitized;
  }


  function ensureProfile(
    state,
    profileKey
  ) {
    if (
      !state.profiles[
        profileKey
      ]
    ) {
      state.profiles[
        profileKey
      ] = {
        automatic_default:
          false,

        default_initialized:
          false,

        default_source:
          "UNINITIALIZED",

        origins:
          {}
      };
    }

    return state.profiles[
      profileKey
    ];
  }


  function deniedResolution(
    profileKey,
    origin,
    source
  ) {
    return {
      schema_version:
        SCHEMA_VERSION,

      browser_profile_key:
        profileKey,

      origin:
        origin,

      automatic_allowed:
        false,

      source:
        source
    };
  }


  async function resolve(
    profileKey,
    url
  ) {
    const normalizedProfile =
      normalizeProfileKey(
        profileKey
      );

    const origin =
      normalizeOrigin(
        url
      );

    if (
      !normalizedProfile
      || !origin
    ) {
      return deniedResolution(
        normalizedProfile,
        origin,
        "INVALID_IDENTITY"
      );
    }


    let state;

    try {
      state =
        await readState();

    } catch (_) {
      return deniedResolution(
        normalizedProfile,
        origin,
        "STORAGE_ERROR"
      );
    }


    const profile =
      state.profiles[
        normalizedProfile
      ];

    if (!profile) {
      return deniedResolution(
        normalizedProfile,
        origin,
        "PROFILE_DEFAULT_OFF"
      );
    }


    const explicit =
      profile.origins[
        origin
      ];

    if (
      explicit === ORIGIN_DENY
    ) {
      return deniedResolution(
        normalizedProfile,
        origin,
        "ORIGIN_DENY"
      );
    }


    if (
      explicit === ORIGIN_ALLOW
    ) {
      return {
        schema_version:
          SCHEMA_VERSION,

        browser_profile_key:
          normalizedProfile,

        origin:
          origin,

        automatic_allowed:
          true,

        source:
          "ORIGIN_ALLOW"
      };
    }


    return {
      schema_version:
        SCHEMA_VERSION,

      browser_profile_key:
        normalizedProfile,

      origin:
        origin,

      automatic_allowed:
        (
          profile
            .automatic_default
          === true
        ),

      source:
        (
          profile
            .automatic_default
          === true
            ? "PROFILE_DEFAULT_ON"
            : "PROFILE_DEFAULT_OFF"
        )
    };
  }


  async function setProfileDefault(
    profileKey,
    enabled
  ) {
    const normalized =
      normalizeProfileKey(
        profileKey
      );

    if (!normalized) {
      throw new Error(
        "QCC_ARCH_CAPTURE_PROFILE_INVALID"
      );
    }

    const state =
      await readState();

    const profile =
      ensureProfile(
        state,
        normalized
      );

    profile.automatic_default =
      enabled === true;

    profile.default_initialized =
      true;

    profile.default_source =
      "MANUAL";

    await writeState(
      state
    );

    return profile
      .automatic_default;
  }


  /*
   * QCC_ARCHITECTURE_PROFILE_MODE_SEED_V1
   *
   * Inicialización única del default del perfil:
   *
   * ASSISTED   -> ON
   * PERSISTENT -> ON
   * EPHEMERAL  -> OFF
   *
   * Si el perfil ya está inicializado, no modifica nada.
   * Esto protege tanto configuración MANUAL como LEGACY.
   */
  async function seedProfileDefaultFromMode(
    profileKey,
    browserSessionMode
  ) {
    const normalizedProfile =
      normalizeProfileKey(
        profileKey
      );

    const normalizedMode =
      normalizeBrowserSessionMode(
        browserSessionMode
      );

    if (!normalizedProfile) {
      throw new Error(
        "QCC_ARCH_CAPTURE_PROFILE_INVALID"
      );
    }

    if (!normalizedMode) {
      throw new Error(
        "QCC_ARCH_CAPTURE_SESSION_MODE_INVALID"
      );
    }


    const state =
      await readState();

    const existing =
      state.profiles[
        normalizedProfile
      ];

    if (
      existing
      ?.default_initialized
      === true
    ) {
      return {
        seeded:
          false,

        browser_profile_key:
          normalizedProfile,

        browser_session_mode:
          normalizedMode,

        automatic_default:
          existing
            .automatic_default
            === true,

        default_initialized:
          true,

        default_source:
          existing
            .default_source
          || "LEGACY"
      };
    }


    const profile =
      ensureProfile(
        state,
        normalizedProfile
      );

    profile.automatic_default =
      (
        normalizedMode === "ASSISTED"
        || normalizedMode === "PERSISTENT"
      );

    profile.default_initialized =
      true;

    profile.default_source =
      (
        "MODE_"
        + normalizedMode
      );


    await writeState(
      state
    );


    return {
      seeded:
        true,

      browser_profile_key:
        normalizedProfile,

      browser_session_mode:
        normalizedMode,

      automatic_default:
        profile
          .automatic_default
          === true,

      default_initialized:
        true,

      default_source:
        profile
          .default_source
    };
  }


  async function setOriginMode(
    profileKey,
    url,
    mode
  ) {
    const normalizedProfile =
      normalizeProfileKey(
        profileKey
      );

    const origin =
      normalizeOrigin(
        url
      );

    const normalizedMode =
      (
        mode === null
        || mode === undefined
        || String(mode).trim() === ""
      )
        ? null
        : String(
            mode
          )
            .trim()
            .toUpperCase();


    if (!normalizedProfile) {
      throw new Error(
        "QCC_ARCH_CAPTURE_PROFILE_INVALID"
      );
    }

    if (!origin) {
      throw new Error(
        "QCC_ARCH_CAPTURE_ORIGIN_INVALID"
      );
    }

    if (
      normalizedMode !== null
      && normalizedMode
        !== ORIGIN_ALLOW
      && normalizedMode
        !== ORIGIN_DENY
    ) {
      throw new Error(
        "QCC_ARCH_CAPTURE_MODE_INVALID"
      );
    }


    const state =
      await readState();

    const profile =
      ensureProfile(
        state,
        normalizedProfile
      );

    if (
      normalizedMode === null
    ) {
      delete profile.origins[
        origin
      ];

    } else {
      profile.origins[
        origin
      ] = normalizedMode;
    }

    await writeState(
      state
    );

    return (
      normalizedMode
    );
  }


  async function allowOrigin(
    profileKey,
    url
  ) {
    return await setOriginMode(
      profileKey,
      url,
      ORIGIN_ALLOW
    );
  }


  async function denyOrigin(
    profileKey,
    url
  ) {
    return await setOriginMode(
      profileKey,
      url,
      ORIGIN_DENY
    );
  }


  async function clearOriginOverride(
    profileKey,
    url
  ) {
    return await setOriginMode(
      profileKey,
      url,
      null
    );
  }


  async function snapshotForProfile(
    profileKey
  ) {
    const normalized =
      normalizeProfileKey(
        profileKey
      );

    if (!normalized) {
      return {
        schema_version:
          SCHEMA_VERSION,

        browser_profile_key:
          null,

        automatic_default:
          false,

        default_initialized:
          false,

        default_source:
          "UNINITIALIZED",

        origins:
          []
      };
    }


    let state;

    try {
      state =
        await readState();

    } catch (_) {
      return {
        schema_version:
          SCHEMA_VERSION,

        browser_profile_key:
          normalized,

        automatic_default:
          false,

        default_initialized:
          false,

        default_source:
          "STORAGE_ERROR",

        origins:
          [],

        storage_error:
          true
      };
    }


    const profile =
      state.profiles[
        normalized
      ] || {
        automatic_default:
          false,

        default_initialized:
          false,

        default_source:
          "UNINITIALIZED",

        origins:
          {}
      };


    const origins =
      Object.entries(
        profile.origins
      )
        .map(
          ([origin, mode]) => ({
            origin:
              origin,

            mode:
              mode
          })
        )
        .sort(
          (left, right) =>
            left.origin.localeCompare(
              right.origin
            )
        );


    return {
      schema_version:
        SCHEMA_VERSION,

      browser_profile_key:
        normalized,

      automatic_default:
        profile
          .automatic_default
          === true,

      default_initialized:
        profile
          .default_initialized
          === true,

      default_source:
        profile
          .default_source
        || "UNINITIALIZED",

      origins:
        origins
    };
  }


  globalThis
    .QccArchitectureCapturePolicy = {
      schema_version:
        SCHEMA_VERSION,

      storage_key:
        STORAGE_KEY,

      modes: {
        ALLOW:
          ORIGIN_ALLOW,

        DENY:
          ORIGIN_DENY
      },

      normalizeProfileKey,
      normalizeOrigin,
      normalizeBrowserSessionMode,
      resolve,
      setProfileDefault,
      seedProfileDefaultFromMode,
      setOriginMode,
      allowOrigin,
      denyOrigin,
      clearOriginOverride,
      snapshotForProfile
    };
})();
