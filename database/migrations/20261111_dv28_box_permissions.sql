-- DV28-P1 (H1): concesión explícita y auditada del permiso de archivar copias en Box.
--
-- Aditiva e idempotente: solo crea user_permission_grants, su índice y dos
-- triggers de auditoría. No modifica users ni ninguna otra tabla y NO inserta
-- concesiones: sin una concesión explícita nadie archiva (DENIED por defecto).
-- NO se aplica al abrir pantallas ni al arrancar: solo por el procedimiento de
-- migración aprobado por Dirección, con copia de seguridad validada y rollback
-- (DV28-P2). En DV28-P1 solo se aplica a bases temporales de test.
--
-- Permiso canónico: 'document.box_copy'. Una concesión es de UN usuario
-- (user_id + username en el momento de concederla: si el usuario cambia de
-- nombre, deja de aplicar), la concede OTRA persona (granted_by_user_id) con
-- motivo, puede caducar (expires_at) y se revoca una sola vez con quién y por
-- qué. Las filas nunca se borran ni se reescriben: la tabla es la evidencia.
-- Fechas en UTC con el formato de datetime('now'): 'YYYY-MM-DD HH:MM:SS'.
--
-- Dialecto: SQLite. En PostgreSQL el contrato es el mismo (CHECK, índice
-- parcial, trigger que impide DELETE y UPDATE salvo la revocación).

CREATE TABLE IF NOT EXISTS user_permission_grants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id)
        CHECK (user_id > 0),
    username TEXT NOT NULL
        CHECK (length(trim(username)) > 0),
    permission TEXT NOT NULL
        CHECK (permission = 'document.box_copy'),
    granted_by_user_id INTEGER NOT NULL REFERENCES users(id)
        CHECK (granted_by_user_id > 0 AND granted_by_user_id <> user_id),
    granted_at TEXT NOT NULL
        CHECK (granted_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'),
    reason TEXT NOT NULL
        CHECK (length(trim(reason)) > 0),
    expires_at TEXT
        CHECK (expires_at IS NULL OR (
            expires_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
            AND expires_at > granted_at)),
    revoked_at TEXT
        CHECK (revoked_at IS NULL OR (
            revoked_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
            AND revoked_at >= granted_at)),
    revoked_by_user_id INTEGER REFERENCES users(id),
    revoke_reason TEXT,
    CHECK ((revoked_at IS NULL AND revoked_by_user_id IS NULL AND revoke_reason IS NULL)
        OR (revoked_at IS NOT NULL AND revoked_by_user_id IS NOT NULL AND revoked_by_user_id > 0
            AND revoke_reason IS NOT NULL AND length(trim(revoke_reason)) > 0))
);

-- Como mucho una concesión vigente (no revocada) por usuario y permiso.
CREATE UNIQUE INDEX IF NOT EXISTS uq_user_permission_grants_active
    ON user_permission_grants(user_id, permission)
    WHERE revoked_at IS NULL;

-- Evidencia inmutable: nunca se borra una concesión.
CREATE TRIGGER IF NOT EXISTS trg_user_permission_grants_no_delete
BEFORE DELETE ON user_permission_grants
BEGIN
    SELECT RAISE(ABORT, 'user_permission_grants: las concesiones no se borran; se revocan');
END;

-- Solo se admite UNA actualización: la revocación de una concesión vigente.
CREATE TRIGGER IF NOT EXISTS trg_user_permission_grants_revoke_only
BEFORE UPDATE ON user_permission_grants
WHEN OLD.revoked_at IS NOT NULL
    OR NEW.revoked_at IS NULL
    OR NEW.id IS NOT OLD.id
    OR NEW.user_id IS NOT OLD.user_id
    OR NEW.username IS NOT OLD.username
    OR NEW.permission IS NOT OLD.permission
    OR NEW.granted_by_user_id IS NOT OLD.granted_by_user_id
    OR NEW.granted_at IS NOT OLD.granted_at
    OR NEW.reason IS NOT OLD.reason
    OR NEW.expires_at IS NOT OLD.expires_at
BEGIN
    SELECT RAISE(ABORT, 'user_permission_grants: solo se admite revocar una concesión vigente');
END;
