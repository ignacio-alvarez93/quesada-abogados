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


      state.profiles[
        profileKey
      ] = {
        automatic_default:
          rawProfile
            .automatic_default
            === true,

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

    await writeState(
      state
    );

    return profile
      .automatic_default;
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
      resolve,
      setProfileDefault,
      setOriginMode,
      allowOrigin,
      denyOrigin,
      clearOriginOverride,
      snapshotForProfile
    };
})();
