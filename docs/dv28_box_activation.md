# WO-DV28-P1 · Activación gobernada de «Archivar copia en Box» desde el visor

**Rama:** `feature/dv28-activacion-box` (worktree `quesada-dv28-activacion-box`), sobre `5c87594` (merge DV26+DV27;
`ae7170f` es ancestro). Sin tocar `main`, `develop`, CRM canónico, `database/quesada.db`, Box Drive ni `.env`.
**Estado de la vía real:** `EXECUTION_ENABLED = False`, `APPROVED_CONTRACT = None`, `SINGLE_HOST_APPROVED = False`,
`H3_WRITE_CONTAINMENT_VERIFIED = False`, sin cambios. **Box REAL NO activado.**

> **Evidencia de ejecución: PENDIENTE.** Esta sesión no tenía terminal: no se ha ejecutado pytest, `compileall`
> ni `git diff --check`, y no se ha hecho commit. Código y tests se escribieron leyendo el código real y los
> contratos certificados. No hay `RUNNER_ACCEPTANCE` de DV28 hasta que el Runner ejecute la batería (al final).
> En especial, la prevención H3 en Windows **no está confirmada** hasta que pasen los tests de ataque
> (`ContainmentTests`) en el Runner Windows.

## 1. Diagnóstico

### Traza botón → copia física

`document_viewer_link_dialog` («Archivar en Box» / «Archivar seleccionados», import diferido) →
`ArchiveForm` (`document_viewer_archive_dialog`): `inspect_archive` → `prepare_archive` (solo lectura) →
consentimiento sobre la huella → `execute_archive` → `_authorize` (H1) → `_intent_store` (H2) → nueva revisión
completa → por documento `_execute_one` → `_governed_copy` → `intents.run_intent(store, intent,
intents.governed_box_copy(intent, copy=certified_copy))` → `certified_copy` → **única** llamada a
`document_inbox_service.copy_inbox_item_to_expedient_box` (P3B1: COPY → VERIFY → REGISTER). No hay segundo motor:
el repositorio solo envuelve esa función (comprobado por `ScopeTests` de P3B2/P3B3/DV27).

### Hechos H1 / H2 / H3

| | Cobertura antes de DV28 | Agujero concreto | Prueba reproducible | Corrección mínima (DV28) |
|---|---|---|---|---|
| **H1** permiso | `authorize_archive` DENY por defecto; consultado una vez en `execute_archive` | (a) no existía ningún contrato concreto (no hay RBAC: `users` = id, username, is_active); (b) solo se comprobaba al confirmar: una revocación después no se veía antes de copiar; (c) la revisión no reflejaba el permiso | `ViewerGrantTests.test_revocation_right_before_the_copy_writes_nothing_and_can_be_retried` | Migración aditiva `20261111_dv28_box_permissions.sql` + `PersistedGrantContract` (no instalado); H1 en `prepare`, al confirmar y dentro de la solicitud justo antes de COPY |
| **H2** exclusión | `run_intent` + `SqliteArchiveIntentStore` (claim atómico, índice parcial, fencing, conciliación) integrados en DV27 | No hay autoridad compartida entre puestos: cada `quesada.db` es otra autoridad | `test_independent_databases_are_not_coordination_between_machines` (P3B3) | Ninguna en código de copia (no se duplica idempotencia). Contrato `ArchiveIntentStore` (Protocol) para el adaptador central futuro; más pruebas de carrera (4 hilos por el visor, 4 procesos reales) |
| **H3** TOCTOU | P3B1 valida la carpeta por ruta y crea `open("xb")` por ruta; VERIFY detecta después | Entre `_box_destination_folder` y `open("xb")` un componente se podía sustituir por una unión: la escritura **salía** (demostrado en DV27/P3B3) | `test_toctou_swap_after_validation_is_detected_but_not_prevented` (P3B3, ahora invertido) | Cadena de handles de carpeta sin `FILE_SHARE_DELETE` de la raíz al destino durante COPY → VERIFY → REGISTER; carpetas que faltan se crean bajo un padre retenido |

### Flags confirmados en el código real (sin cambiar)

`EXECUTION_ENABLED = False`, `SINGLE_HOST_APPROVED = False`, `H3_WRITE_CONTAINMENT_VERIFIED = False`
(`document_viewer_box_archive_service.py`), `APPROVED_CONTRACT = None` (`document_viewer_archive_permission_service.py`),
`MULTI_HOST_GUARANTEE = False` (`document_viewer_archive_repository.py`). `GateTests` de DV28 lo comprueba por AST.

### Infraestructura reutilizable

- **RBAC / permisos:** no existe (solo `document_viewer_archive_permission_service`, que es la puerta, sin datos).
  Se implementa un contrato mínimo aislado: una tabla, un permiso, solo lectura desde el CRM.
- **Autoridad transaccional central:** no existe base central operativa. Se reutiliza el dominio de DV25-P3B3
  (que ya habla con un almacén abstracto) y se formaliza su contrato; no se crea un segundo almacén.
- **Adaptador de filesystem seguro:** no existía. La corrección se hace dentro de P3B1 (la primitiva única),
  no en un módulo nuevo.

## 2. H1 · Autorización explícita y auditada

**Migración** `database/migrations/20261111_dv28_box_permissions.sql` (solo DDL, idempotente, no aplicada a la BD
real): tabla `user_permission_grants`, índice parcial `uq_user_permission_grants_active` (una concesión vigente por
usuario y permiso) y dos triggers. Sin concesiones por defecto.

- Permiso canónico único: `CHECK (permission = 'document.box_copy')`.
- Concesión para `user_id` **y** `username` de ese momento (renombrar al usuario la deja sin efecto).
- Concede otra persona (`granted_by_user_id <> user_id`), con motivo obligatorio; `expires_at` opcional.
- Revocación: una sola vez, con `revoked_by_user_id` y `revoke_reason`; después no se admite ningún cambio.
- Auditoría: `DELETE` prohibido por trigger; `UPDATE` solo para revocar. La tabla es la evidencia.

**Contrato** `PersistedGrantContract.grants(user, db_path=)` (conexión de solo lectura): concede solo si existe una
fila vigente (no revocada, en vigor, no caducada) del permiso para ese id, con el mismo nombre que el usuario actual
y el usuario activo. Cualquier error (p. ej. tabla ausente) lanza y `authorize_archive` deniega
(`permission_contract_error`). Los campos `role`, `permissions`, `is_admin` del actor siguen ignorados.
**No está instalado**: `APPROVED_CONTRACT = None`.

**Servicio del visor** (`_permission` es el único punto que llama a `authorize_archive`):

1. `prepare_archive`: la revisión registra `authorized` y `permission_message`; la revisión sigue disponible.
2. `execute_archive` (confirmación): `_authorize` con el usuario verificado; además, una revisión hecha sin permiso
   no se ejecuta aunque después se conceda (`PERMISSION_CHANGED`).
3. Justo antes de COPY, dentro de `certified_copy` y con la solicitud ya tomada: si se retiró o el contrato falla,
   `PERMISSION_REVOKED`, la solicitud queda `rejected` (nada escrito, reintentable con revisión nueva, `fence + 1`).

**Diálogo** (único cambio Flet, sin rediseño): si la revisión no está autorizada para ese usuario muestra el motivo
y no deja marcar el consentimiento. No llama a nada nuevo del servicio (el contrato de `ScopeTests` P3B2 se mantiene).

## 3. H2 · Exclusión interproceso y multi-equipo

- Sin cambios en `run_intent`, `governed_box_copy` ni en el adaptador SQLite: la idempotencia no se duplica.
- `ArchiveIntentStore` (Protocol, `runtime_checkable`): `get`, `claim`, `finish`, `reconcile` y
  `multi_host_guarantee`. Es lo que debe implementar el adaptador PostgreSQL/Supabase (misma tabla; `claim` con
  UNIQUE + índice parcial; `finish`/`reconcile` condicionados por fence).
- El servicio exige `multi_host_guarantee is True` **exacto** o `SINGLE_HOST_APPROVED is True`; un valor «verdadero»
  que no sea `True` no cuenta (probado).
- **Decisión vigente respetada:** no se asume mono-equipo; `SINGLE_HOST_APPROVED` sigue False y no se propone
  activarlo. Bloqueo: `MULTI_HOST_AUTHORITY_PENDING`.
- Qué falta para resolverlo: base central operativa (DATA-008), adaptador que cumpla `ArchiveIntentStore` contra
  ella, migración de `document_viewer_archive_intents` en esa base y que todos los puestos usen esa autoridad.
- Huérfanos y `needs_review`: sin cambios; nunca se reintentan ni se borra nada (DV27 `CrashTests`).

## 4. H3 · TOCTOU Windows + Box Drive

**Corrección en P3B1** (`document_inbox_service.py`, reutilizada por el visor y por el botón de Bandeja):

- `_HeldBoxFolders` / `_held_box_folder`: un handle por carpeta, de la raíz Box del expediente hasta el destino,
  abierto con `CreateFileW(FILE_LIST_DIRECTORY | FILE_TRAVERSE | FILE_READ_ATTRIBUTES | SYNCHRONIZE,
  FILE_SHARE_READ | FILE_SHARE_WRITE` — **sin** `FILE_SHARE_DELETE` —, `OPEN_EXISTING,
  FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)`.
- Cada handle se valida: es carpeta; si es reparse point, solo se acepta la etiqueta de la Cloud Files API
  (`0x9000x01A`, misma política única `reparse_redirects` de P3A/P3B1); su ruta final
  (`GetFinalPathNameByHandleW`) es exactamente la revisada. Si no: `BoxCopyContainmentError`
  (`BoxCopyRejected`, código `CONTAINMENT`) **antes de crear nada**.
- `_copy_inbox_item_to_box` mantiene la cadena desde antes de `_create_box_copy` hasta después de
  `_register_box_copy`; los handles se liberan siempre (también ante fallo o «crash» simulado).
- `_box_destination_folder` retiene cada padre antes de crear la carpeta que falta (ruta de Bandeja):
  una carpeta nueva nunca se crea a través de una unión.
- Mientras la cadena está retenida, ninguna de sus carpetas se puede borrar ni renombrar (violación de uso
  compartido), por lo que `open("xb")` por ruta resuelve dentro de las carpetas retenidas. Se mantiene `open("xb")`
  por ruta: es el contrato certificado de P3B1 (modo `xb`, guardas de escritura de los sandboxes).
- Traza: `box_copy.containment = "win32_handles_without_share_delete"`.
- POSIX (no es destino de producción): revalidación con `O_NOFOLLOW` + `dir_fd`; **no** es prevención.

**Supuesto a confirmar en el Runner:** que NTFS rechaza renombrar un **antecesor** de la raíz mientras hay un handle
abierto sin `FILE_SHARE_DELETE` en su interior. `test_swaps_while_the_chain_is_held_fail_and_the_copy_stays_inside`
lo intenta (renombrar `box/`, padre de la raíz) y **falla** si el sistema lo permite. Si falla, H3 queda NO resuelto
para antecesores y hay que decidir (p. ej. retener también los antecesores de la raíz) antes de activar.

**Box Drive:** no probado (prohibido en esta WO). Riesgos a validar en la prueba supervisada: que Box Drive
devuelva en `GetFinalPathNameByHandleW` la misma ruta que `Path.resolve`; que abrir una carpeta marcador con
`FILE_FLAG_OPEN_REPARSE_POINT` no interfiera con el filtro de nube; que retener carpetas sin `FILE_SHARE_DELETE`
unos segundos no rompa la sincronización. Si algo no cuadra, el diseño **falla cerrado** (no copia); no se relaja
la validación. Rutas cortas 8.3 o de más de 260 caracteres: fallan cerradas.

## 5. Contrato de interfaz y formatos

DV26/DV27 sin cambios de diseño: previsualización, carpeta existente, nomenclatura, confirmación, resumen por
documento y lote. PDF/JPG/PNG conservan su extensión y reciben el nombre del catálogo, sin conversión
(`FormatTests`). Solo se archivan ítems ya vinculados al mismo cliente/expediente. Originales de Bandeja y archivos
existentes en Box se comparan byte a byte (y mtime) en todos los sandboxes. La UI no ejecuta SQL, rutas ni escritura.

## 6. Archivos

| Archivo | Cambio |
|---|---|
| `backend/services/document_inbox_service.py` | H3: `BoxCopyContainmentError`, `_HeldBoxFolders`, `_held_box_folder`, `_open_box_dir`; `_box_destination_folder` y `_copy_inbox_item_to_box` retienen la cadena |
| `backend/services/document_viewer_box_archive_service.py` | H1 en revisión/confirmación/antes de COPY (`_permission`, `PERMISSION_CHANGED`, `PERMISSION_REVOKED`, `ArchivePlan.authorized/permission_message`) |
| `backend/services/document_viewer_archive_permission_service.py` | `BOX_COPY_PERMISSION`, `PersistedGrantContract` (no instalado) |
| `backend/services/document_viewer_archive_repository.py` | `ArchiveIntentStore` (Protocol) y documentación de la autoridad central |
| `frontend/components/document_viewer_archive_dialog.py` | Motivo del rechazo de permiso y consentimiento bloqueado |
| `database/migrations/20261111_dv28_box_permissions.sql` | Nueva (DDL aditiva) |
| `scripts/tests/test_dv28_box_activation.py` | Nueva |
| `scripts/tests/test_dv27_box_copy_activation.py` | Ver «Cambios de contrato de test» |
| `scripts/tests/test_document_viewer_dv25_security.py` | Ver «Cambios de contrato de test» |
| `docs/dv28_box_activation.md` | Este documento |

No se ha creado `scripts/dev/dv28_box_drive_probe.py` (no era necesario).

### Cambios de contrato de test (endurecen, no relajan)

1. `test_document_viewer_dv25_security.DestinationSafetyTests.test_toctou_swap_after_validation_is_detected_but_not_prevented`
   → `..._is_prevented_before_any_write`. Antes exigía que la escritura **saliera** por la unión (residual
   documentado). Ahora exige `BoxCopyContainmentError`, nada escrito fuera, ítem y eventos intactos.
2. `test_dv27_box_copy_activation.SafetyTests.test_h3_folder_swap_is_only_detected_after_the_write`
   → `test_h3_folder_swap_after_validation_is_prevented`: `rejected` con `BOX_CONTAINMENT_FAILED`, carpeta de
   escape vacía, solicitud `rejected` (nada escrito); `TOCTOU_PREVENTION_PENDING` sigue en `activation_blockers()`.
3. `test_dv27_box_copy_activation.PermissionTests`: el contrato se consulta en revisión y confirmación (`[1, 1]`) y,
   si concede, también antes de copiar (`[1, 1, 1]`); antes era una sola vez. Siempre solo sobre el usuario verificado.

## 7. Pruebas nuevas (`test_dv28_box_activation.py`)

| Clase | Qué prueba |
|---|---|
| `GateTests` | Flags cerrados por AST; `activation_blockers()` = 3 códigos; contrato candidato no instalado ni referenciado por la UI; migración solo DDL sin concesiones; la cadena se retiene alrededor de `_create_box_copy` y `_register_box_copy` (y de los `mkdir`); sin `connect` ni `sqlite3` en dominio/UI |
| `GrantContractTests` | Migración aditiva e idempotente; sin concesión ⇒ DENIED (también con `role`/`is_admin` declarados); concedido ⇒ ALLOWED solo a ese usuario; falso, desconocido, inactivo ⇒ NOT_AUTHENTICATED; revocado, renombrado, caducado, aún no vigente ⇒ DENIED; autoconcesión, otro permiso, sin motivo, doble concesión vigente, DELETE, reescritura, revocación sin quién/por qué, doble revocación, «des-revocar» ⇒ rechazados por la BD; sin tabla ⇒ error ⇒ DENIED |
| `ViewerGrantTests` | Concedido ⇒ una copia, vínculo y original intactos; revocado entre revisión y confirmación ⇒ nada; revocado justo antes de COPY ⇒ `rejected`, P3B1 ni llamado, Box intacto, reintento con nueva concesión ⇒ una copia (`fence 2`); fallo del contrato antes de COPY ⇒ nada; revisión sin permiso nunca se ejecuta aunque luego se conceda; caducado ⇒ nada; diálogo muestra el motivo y no toma consentimiento |
| `ViewerAuthorityTests` | 4 revisiones concurrentes sin memoria compartida ⇒ 1 copia, 3 `IN_FLIGHT`; `multi_host_guarantee` = 1/"True"/None no es autoridad; el adaptador SQLite cumple `ArchiveIntentStore` |
| `ProcessAuthorityTests` | 4 procesos reales sobre la misma BD ⇒ un `done`, un archivo, un evento, una solicitud `registered` |
| `ContainmentTests` | Raíz sustituida por unión tras validarla ⇒ rechazo sin escribir (ambas plataformas). Windows: con la cadena retenida fallan `rmdir` de la carpeta y `rename` de carpeta, padre, raíz y antecesor (antes de crear y durante la escritura) y la copia queda dentro; fallos `write`/`verify`/`register` ⇒ archivo conservado dentro y cadena liberada; handle imposible ⇒ rechazo; marcador de nube aceptado; unión, symlink, otro reparse, reparse sin etiqueta, no carpeta u otra ruta ⇒ rechazo; colisión, `reused_identical`, hashes y no sobrescritura bajo la cadena |
| `FormatTests` | PDF/JPG/PNG: misma extensión, nombre del catálogo, mismos bytes, original intacto |

Ataque que consigue escribir fuera de la raíz ⇒ el test **falla** y el flag H3 sigue cerrado en el código.

## 8. Blockers

1. `PERMISSION_CONTRACT_PENDING` — Dirección: quién puede archivar (concesiones explícitas) y aprobación de
   instalar `PersistedGrantContract`; migración aplicada con el procedimiento aprobado.
2. `MULTI_HOST_AUTHORITY_PENDING` — base central compartida + adaptador `ArchiveIntentStore`, o decisión formal
   mono-equipo (no propuesta aquí).
3. `TOCTOU_PREVENTION_PENDING` — evidencia del Runner Windows (`ContainmentTests` en verde, incluido el antecesor)
   y prueba supervisada con Box Drive.
4. Evidencia: ejecución completa del Runner (esta sesión no pudo ejecutar nada).

## 9. Plan de activación final (DV28-P2, fuera de esta WO)

1. Decisiones de Dirección: lista de personas con `document.box_copy` y quién concede; autoridad entre puestos o
   decisión formal mono-equipo; autorización de la prueba supervisada con Box Drive y carpeta de ensayo.
2. Copia de seguridad validada de la BD operativa; aplicar `20261110_dv25_archive_claims.sql` y
   `20261111_dv28_box_permissions.sql` con el procedimiento aprobado y rollback probado (hoy `apply_schema` rechaza
   la BD habitual por diseño).
3. Insertar las concesiones aprobadas (con quién y por qué); instalar `APPROVED_CONTRACT = PersistedGrantContract()`
   en código, con tests.
4. Prueba supervisada Box Drive: una copia inocua en la carpeta de ensayo; comprobar ruta final, hash origen/destino,
   traza `containment` y que el original y lo existente siguen intactos. Si cuadra, `H3_WRITE_CONTAINMENT_VERIFIED = True`.
5. Solo con `activation_blockers() == ()`: `EXECUTION_ENABLED = True`, actualizar los tests AST de compuerta
   (DV27/P3B2/seguridad/DV28/smoke), Runner completo, smoke Flet aislado, aprobación humana y evidencia
   post-activación.

## 10. Informes

### Avance fase DV28-P1

- Hecho en código: H1 (contrato persistido candidato + comprobación en tres puntos + UI), H3 (cadena de handles en
  P3B1, también para carpetas nuevas de Bandeja), H2 (contrato de autoridad formalizado, más pruebas de carrera),
  migración DDL, tests nuevos y tests históricos endurecidos.
- No hecho: ejecución de pruebas, `compileall`, `git diff --check`, commit y `RUNNER_ACCEPTANCE` (sin terminal en
  esta sesión).
- No confirmado: la prevención H3 en Windows real (incluido el antecesor de la raíz) hasta que pase `ContainmentTests`.

### Capacidad global de archivado desde el visor

- Revisión (carpeta, nomenclatura, nombre, colisiones, permiso): disponible.
- Copia real a Box: **desactivada**. Faltan los cuatro blockers del apartado 8; ninguno se resuelve solo con código.
- Bandeja clásica: sigue copiando por P3B1, ahora con la carpeta destino retenida durante la copia.

## Comandos para el Runner

```
python -m pytest -q scripts/tests/test_dv28_box_activation.py
python -m pytest -q scripts/tests/test_dv27_box_copy_activation.py scripts/tests/test_document_viewer_dv25_box_from_viewer.py scripts/tests/test_document_viewer_dv25_security.py scripts/tests/test_document_viewer_dv25_box_hardening.py
python -m pytest -q scripts/tests/test_dv25_bandeja_compat.py scripts/tests/test_dv26_link_visual.py
python -m pytest -q scripts/tests/test_document_viewer_dv24_linking.py scripts/tests/test_document_viewer_dv24_multidoc.py scripts/tests/test_document_viewer_dv24_notes.py scripts/tests/test_document_viewer_dv25_filing_plan.py scripts/tests/test_document_viewer_dv25_selection.py scripts/tests/test_document_viewer_foundation.py scripts/tests/test_document_viewer_integrations.py scripts/tests/test_document_viewer_dv25_toolbar.py scripts/tests/test_document_viewer_dv23_visual.py scripts/tests/test_document_viewer_dv23_close.py scripts/tests/test_document_viewer_dv23_pdf_tools.py scripts/tests/test_dv25_documental_smoke.py
python -m compileall -q backend/services/document_inbox_service.py backend/services/document_viewer_box_archive_service.py backend/services/document_viewer_archive_permission_service.py backend/services/document_viewer_archive_repository.py frontend/components/document_viewer_archive_dialog.py scripts/tests/test_dv28_box_activation.py
git diff --check
```

Si un test falla: conservar la salida, no reintentar a ciegas y no relajar la aserción. En particular, un fallo de
`ContainmentTests` en Windows es evidencia de que H3 **no** está contenido y debe reportarse como tal.

## Estado tras WO-DV28-P2 (piloto mono-equipo)

Detalle completo en `docs/dv28_p2_single_host.md`.

- Nueva puerta de **estación** (`document_viewer_archive_host_policy`): prueba criptográfica de posesión (ECDSA P-256
  contra un ancla pública en código; proveedor Windows CNG/TPM implementado, no instalado). Se exige en la revisión, al
  confirmar y justo antes de cada copia; fail-closed. `ENROLLED_STATION = None`, `PROOF_PROVIDER = None`.
- Flags de producción **sin cambios**: `EXECUTION_ENABLED = False`, `SINGLE_HOST_APPROVED = False`,
  `H3_WRITE_CONTAINMENT_VERIFIED = False`, `APPROVED_CONTRACT = None`, `MULTI_HOST_GUARANTEE = False`.
- H3: `document_inbox_service.py` sin cambios; `ContainmentTests` siguen **sin ejecutar** (P2 tampoco tuvo terminal).
  Nuevo control `H3EvidenceTests` en P2: exige 0 skips en Windows.
- Evidencia de ejecución P2: **PENDIENTE**. El primer run (`fdb-20261112t045215948552-1c3b2f10`) terminó en
  `ACCEPTANCE_FAILED`. FIX1 aplica la corrección de fixture autorizada: `ArchiveBase` enrola una estación sintética
  solo durante cada test (§6 del documento P2). Box Drive real sigue sin probar y la copia real sigue **OFF**.
