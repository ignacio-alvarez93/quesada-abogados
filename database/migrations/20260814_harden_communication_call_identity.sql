-- ============================================================
-- COMUNICACIONES · IDENTIDAD EXTERNA DE LLAMADAS
-- 2026-08-14
-- ============================================================
--
-- Una misma llamada observada por realtime y posteriormente
-- por reconciliación/historial debe converger en una única
-- fila del CRM.
--
-- Identidad canónica:
--
--     (provider, external_call_key)
--
-- provider_call_id conserva el identificador bruto del
-- proveedor cuando exista, pero no constituye por sí solo
-- la identidad canónica del CRM.
--
-- NULL / vacío sigue permitido para llamadas manuales,
-- callbacks todavía no iniciados por proveedor o llamadas
-- cuyo proveedor aún no haya entregado identidad estable.
-- ============================================================

CREATE UNIQUE INDEX IF NOT EXISTS
    uq_communication_calls_provider_external
ON communication_calls(
    provider,
    external_call_key
)
WHERE
    provider IS NOT NULL
    AND TRIM(provider) <> ''
    AND external_call_key IS NOT NULL
    AND TRIM(external_call_key) <> '';
