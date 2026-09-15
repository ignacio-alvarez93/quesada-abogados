/*
 * QCC_MERCURIO_ACQUISITION_POLICY_V1
 *
 * Provider policy compartida por:
 * - Side Panel;
 * - Service Worker.
 *
 * Mercurio REAL permanece bloqueado en SNAPSHOT_ONLY.
 */

(() => {
  const policy =
    globalThis.QccAcquisitionPolicy;

  if (
    !policy
    || typeof policy.register
      !== "function"
  ) {
    throw new Error(
      "QCC_ACQUISITION_POLICY_NOT_AVAILABLE"
    );
  }

  policy.register({
    origin:
      "https://mercurio.delegaciondelgobierno.gob.es",

    mode:
      policy.SNAPSHOT_ONLY,

    locked:
      true,

    source:
      "MERCURIO_PROVIDER"
  });
})();
