-- ============================================================
-- COMUNICACIONES · IDENTIDAD EXTERNA DE MENSAJES
-- 2026-08-12
-- ============================================================
--
-- Un mensaje recibido/importado desde un proveedor no puede
-- persistirse dos veces dentro de la misma conversación.
--
-- NULL sigue permitido para mensajes internos/salientes que
-- todavía no dispongan de identificador del proveedor.
-- ============================================================

CREATE UNIQUE INDEX IF NOT EXISTS
    uq_communication_messages_thread_provider
ON communication_messages(
    thread_id,
    provider_message_id
)
WHERE
    provider_message_id IS NOT NULL
    AND TRIM(provider_message_id) <> '';
