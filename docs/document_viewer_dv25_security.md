# DV25-P3B3 · Seguridad e idempotencia antes de Box REAL

**Base:** `feature/document-viewer-dv25-seleccion-nomenclatura` @ `5317fe2`.
**Auditoría de referencia:** `fdb-20261110t201240273538-916f9d23` (H1–H8).
**Estado de la vía real:** `EXECUTION_ENABLED = False` (sin cambios). Ninguna escritura en Box real ni en
`database/quesada.db`. Sin flags activados, sin integración de rama.

> **Evidencia de ejecución: PENDIENTE.** Este trabajo se hizo en un entorno sin terminal: no se ha
> ejecutado pytest, `git diff --check` ni `py_compile`. El código y los tests se escribieron revisando el
> código real y los contratos certificados, pero **no hay RUNNER_ACCEPTANCE de P3B3** hasta que el runner
> ejecute la batería (comandos al final). Nada de este informe es aprobación funcional humana.

## Resumen por hallazgo

| Hallazgo | Estado | Dónde |
|---|---|---|
| H1 permiso | **Preparado, no integrado** (DENY por defecto; integrarlo requiere ampliar contrato P3B2) | `document_viewer_archive_permission_service.py` |
| H2 idempotencia / exclusión | **Preparado, no integrado**; garantía solo con UNA base compartida; **multi-equipo NO resuelto** | `document_viewer_archive_repository.py`, migración `20261110_dv25_archive_claims.sql` |
| H3 TOCTOU / reparse | **Pendiente (riesgo residual documentado)**; detección posterior probada | P3B1 sin cambios de mecanismo |
| H4 carpeta desaparecida | **Mitigado** en el flujo del visor (`STALE_DESTINATION`) | `document_inbox_service._box_destination_folder` |
| H5 `reused_identical` | **Mitigación parcial**: procedencia verificable, sin atribución; la reutilización se mantiene (contrato P3B1) | `_box_copy_provenance`, mensaje en P3B2 |
| H6 DDL al abrir diálogo | **Mitigado** en los lectores del diálogo de vinculación | `document_inbox_service` (lectores) |
| H7 aislamiento de tests | **Mitigado en la suite nueva** (guarda fail-closed de `sqlite3.connect`) | `test_document_viewer_dv25_security.py` |
| H8 convergencia P3A/P3B1 | **Mitigado**: una sola política de reparse, rutas de red y nombres | `document_viewer_filing_plan_service.py` |

## Contratos certificados que impiden integrar H1/H2 (escalado, no sorteado)

`test_document_viewer_dv25_box_from_viewer.py` (P3B2, certificado) abre `EXECUTION_ENABLED` en sandbox y
espera que `execute_archive` copie con solo usuario activo + bloqueos en RAM:

- `GateTests.test_real_path_is_closed_in_the_code` exige `execution_blocker() == ""` con la compuerta abierta;
- `ExecutionTests` / `ViewerDialogTests` esperan `ARCHIVED` para el usuario `ana` sin permiso alguno;
- `ScopeTests.test_service_reuses_the_certified_copy_and_otherwise_reads` fija exactamente los atributos de
  `document_inbox_service` y los 3 kwargs de la llamada a la copia.

Exigir permiso (H1) o claim persistente (H2) dentro de `execute_archive` hace fallar esos tests sin
cambiar una sola aserción: el ArchiveBase no concede permiso ni tiene la tabla de solicitudes. Modificar
su `setUp` no está autorizado (solo tests nuevos en ese archivo). **Propuesta mínima para Dirección:**

1. autorizar dos líneas en `ArchiveBase.setUp`: `repo.apply_schema(self.db)` y
   `patch.object(permission, "APPROVED_CONTRACT", <contrato de sandbox que concede a ana>)`;
2. autorizar que `execute_archive` llame a `permission.authorize_archive` y envuelva cada copia con
   `repo.run_intent(..., repo.governed_box_copy(...))`, conservando `IN_FLIGHT` como mensaje del
   `IN_PROGRESS` persistente.

Hasta entonces la compuerta sigue cerrada y las piezas viven probadas por separado.

## H1 · Permiso

Estado real: `users(id, username, password_hash, is_active, created_at)`; no hay roles ni RBAC en el CRM.
`authorize_archive(actor, db_path=)`:

- reutiliza `link_service.verified_user` (existe, activo, mismo `username`): ausente/falsificado/inactivo ⇒ `DENIED`;
- **sin contrato aprobado (`APPROVED_CONTRACT = None`) ⇒ `DENIED` para todos** (`permission_contract_missing`);
- claves declaradas por el cliente (`role`, `permissions`, `is_admin`) se ignoran; no se infiere nada del nombre;
- un contrato instalado en código decide con `grants(user) is True`; otro valor ⇒ `DENIED`; excepción ⇒ `DENIED`;
  nunca se consulta para un actor no autenticado.

**Decisión pendiente de Dirección:** qué permiso habilita archivar en Box y dónde se persiste (tabla de
permisos versionada). No se ha creado ningún rol.

## H2 · Solicitud canónica persistente

Migración aditiva y versionada `database/migrations/20261110_dv25_archive_claims.sql`
(`document_viewer_archive_intents`):

- `idempotency_key` UNIQUE = SHA-256(ítem, cliente, expediente, subcarpeta, nomenclatura, SHA-256 origen);
  el actor no entra: dos personas, una sola copia;
- índice único parcial por `inbox_item_id` en estados `claimed`/`needs_review`: un ítem no puede tener dos
  solicitudes activas aunque lleguen con otra clave;
- `fence` + `owner_token`: cada adquisición/conciliación incrementa `fence`; solo el titular vigente cierra
  (`UPDATE ... WHERE owner_token AND fence AND state='claimed'`).

Se aplica **solo** con `apply_schema(db_path)` explícito; rechaza `None` y la base habitual. Nunca desde UI,
arranque ni pytest sobre la base habitual. El almacén (`SqliteArchiveIntentStore`) solo abre bases
existentes (`mode=rw`) y no migra: sin tabla ⇒ `UNAVAILABLE` sin copiar.

Dominio (`run_intent`) sin SQL: adquisición atómica (`BEGIN IMMEDIATE`), una sola ejecución de la operación,
cierre con fencing, y estados:

| Situación | Resultado | Escritura en Box |
|---|---|---|
| primera petición | `done` | la de P3B1 (única vía física) |
| misma petición ya registrada | `already_done` (devuelve destino) | ninguna |
| petición del mismo ítem en curso (cualquier clave) | `in_progress` | ninguna |
| rechazo P3B1 sin escritura | `refused` (reintentable, `fence+1`) | ninguna |
| `BoxCopyIncomplete` / error desconocido | `review_required` (no se reintenta) | la que hubiera; nunca se borra |
| claim caducado + copia registrada e íntegra en Bandeja | `recovered` | ninguna |
| claim caducado sin registro | `review_required` | ninguna |
| titular desplazado durante la copia | `fenced` (a revisión) | la suya, registrada por P3B1 |

Portabilidad: el contrato (UNIQUE, índice parcial, UPDATE condicionado, excepciones DB-API de la conexión)
es el mismo en PostgreSQL; solo cambia la DDL de `id`.

### Garantías reales de concurrencia

- **Probado (sandbox):** dos procesos independientes sobre **la misma** base temporal ⇒ una copia, un registro,
  sin `_2`; hilos con conexiones propias ⇒ una ejecución; crash tras REGISTER ⇒ conciliación sin nuevo archivo;
  crash entre VERIFY y REGISTER ⇒ revisión humana, archivo conservado.
- **No garantizado:** coordinación entre equipos. Hoy `connection.DB_PATH` es un archivo SQLite dentro de cada
  copia del repositorio: cada PC tiene su propia autoridad. El test con dos bases independientes muestra que
  ambos procesos "ganan" (`MULTI_HOST_GUARANTEE = False`). SQLite en carpeta de red tampoco es una autoridad
  fiable. **La concurrencia multi-equipo NO está resuelta; la puerta debe seguir cerrada** hasta disponer de una
  base central compartida (DATA-008).
- El `fence` protege el registro de la solicitud, no el sistema de archivos: P3B1 no recibe el fence. La
  protección física sigue siendo la creación exclusiva `xb` y el CAS de `_register_box_copy`.
- No hay heartbeat durante la copia: una copia más larga que `LEASE` (15 min) puede ser conciliada por otro
  proceso a revisión humana (conservador: nunca duplica).

## H3 · Ruta / TOCTOU

Existente y conservado: raíz y cada componente comprobados con `lstat` (enlace, unión o reparse no-nube ⇒
rechazo), creación exclusiva `xb`, verificación posterior de que `realpath(dest).parent` es la carpeta.
**No resuelto:** entre validar la carpeta y `open("xb")` un componente puede sustituirse por una unión; Python
en Windows no permite crear relativo a un handle de directorio ni bloquear el renombrado sin Win32 directo.
Test `test_toctou_swap_after_validation_is_detected_but_not_prevented`: la escritura **sale** por la unión,
P3B1 lo detecta en VERIFY, no registra y no borra. Mitigación posible (no implementada, requiere decisión):
abrir cada componente con `CreateFileW(FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS)` sin
`FILE_SHARE_DELETE` durante la copia, y validar su comportamiento con Box Drive. **Bloqueante para Box REAL.**

## H4 · Carpeta desaparecida

`_box_destination_folder(..., create_missing=False)` lanza `BoxCopyStaleDestination` (`code =
"STALE_DESTINATION"`, subclase de `BoxCopyRejected`). Se activa cuando la copia es por `nomenclature_key`,
que hoy solo usa el visor (carpeta elegida entre las existentes revisadas por P3A). La copia de Bandeja sin
nomenclatura conserva su contrato certificado (`test_missing_subfolders_are_created_one_by_one_inside_root`).
Decisión a ratificar: acoplar "por nomenclatura ⇒ solo carpetas existentes" (el contrato P3B2 fija los kwargs
de la llamada y no permite añadir uno explícito).

## H5 · `reused_identical`

La traza de P3B1 incluye `provenance` y `created_by_this_operation`:

- `created`: este flujo creó el archivo;
- `own_unregistered_copy`: un fallo de REGISTER **de este ítem** trazó ese destino, ese SHA-256 y que lo había
  creado él; la reutilización es la recuperación de su propia copia;
- `preexisting_unverified`: cualquier otro caso (incluidas trazas sin procedencia anteriores a P3B3). El evento
  dice "no lo creó esta operación" y el visor lo muestra. Un fallo de REGISTER sobre un archivo preexistente
  no "blanquea" su procedencia en el reintento.

No se bloquea la reutilización: P3B1/P3B2 certificados la exigen. Si Dirección prefiere bloquearla, es un
cambio de contrato a aprobar. El registro sigue escribiendo `copied_to_box` y `linked_document_path`.

## H6 · Sin DDL ni carpetas al abrir el diálogo

`get_inbox_item`, `list_clients_for_inbox`, `client_autocomplete_options`, `list_expedients_for_client`,
`expedient_autocomplete_options_for_client` y la anotación de duplicados (`_query_inbox_items`) ya no llaman
a `ensure_document_inbox_schema()`/`_ensure_dirs()`. Sin tabla, `get_inbox_item` responde "no existe"
(`ValueError`, igual que antes para un ítem ausente). Los escritores y `list_inbox_items` siguen inicializando
como antes; la vista de Bandeja hace su bootstrap al cargarse (`document_inbox_view`, sin cambios).
Residual: `get_inbox_events` (panel de actividad del visor, no el diálogo) mantiene la inicialización
existente.

## H7 · Aislamiento

`SandboxMixin` sustituye `sqlite3.connect` por una versión que rechaza (AssertionError y registro) cualquier
base fuera del directorio temporal, también en URI `file:` y `bytes`; apunta `connection.DB_PATH` y
`expedient_service.DB_PATH` al sandbox. A nivel de módulo se compara la base habitual (y `-journal`, `-wal`,
`-shm`) por tamaño, `mtime` **y SHA-256**. Los procesos hijos instalan la misma guarda antes de importar el CRM
(salida 90 si se viola). Las suites certificadas no se tocan; cuando se ejecutan dentro de esta suite heredan
la guarda.

## H8 · Convergencia preview / copia

`reparse_redirects` vive en P3A y P3B1 lo delega (una sola política). P3A ya no ofrece: raíces de red
(`\\`, `//`), raíces o carpetas unión/reparse (antes `is_symlink()` no detectaba uniones), ni nombres que
`check_subfolder` rechaza (`CON`, `aux.txt`, punto final...). Test: toda carpeta ofrecida pasa
`check_subfolder` y `_box_destination_folder(create_missing=False)` sin crear nada.

## Pruebas por escenario (`scripts/tests/test_document_viewer_dv25_security.py`)

| Escenario | Test |
|---|---|
| permiso ausente, rol insuficiente, inactivo, falsificado ⇒ DENIED; puerta cerrada | `PermissionTests.*` |
| dos procesos, misma BD ⇒ una copia y un registro | `MultiProcessTests.test_two_processes_on_one_shared_database_copy_and_register_once` |
| dos procesos, BD independientes ⇒ NO es coordinación | `MultiProcessTests.test_independent_databases_are_not_coordination_between_machines` |
| crash tras REGISTER / entre VERIFY y REGISTER | `MultiProcessTests.test_crash_*` |
| claim, clave, fencing, rechazo, revisión, hilos | `IntentStoreTests.*` |
| inexistente, borrada tras revisión | `DestinationSafetyTests.test_missing_folder_*`, `test_folder_deleted_*`, `ViewerSafetyTests.test_reviewed_folder_removed_*` |
| symlink/unión, `..`, UNC, absolutas, `CON` | `DestinationSafetyTests.test_hostile_destinations_*`, `ConvergenceTests.*` |
| colisión, original cambiado, idéntico previo | `DestinationSafetyTests.test_collision_changed_original_and_identical_previous_file` |
| fallo de REGISTER y reintento | `DestinationSafetyTests.test_register_failure_*` |
| TOCTOU (residual) | `DestinationSafetyTests.test_toctou_*` |
| navegación/cancelación sin cambios de esquema, datos ni carpetas | `ViewerSafetyTests.test_opening_navigating_*`, `ReaderSideEffectTests.*` |
| aislamiento fail-closed | `IsolationTests.*` |
| alcance: compuerta, primitivas, UI | `ScopeTests.*` |

Todos los escenarios con archivos usan las guardas certificadas (sin `unlink`/`rename`/`replace`/`rmtree`, solo `xb`).

## Archivos tocados

- `backend/services/document_inbox_service.py` (H4, H5, H6, H8)
- `backend/services/document_viewer_filing_plan_service.py` (H8)
- `backend/services/document_viewer_box_archive_service.py` (mensaje H5 y docstring; sin cambios de flujo)
- `backend/services/document_viewer_archive_permission_service.py` (nuevo, H1)
- `backend/services/document_viewer_archive_repository.py` (nuevo, H2)
- `database/migrations/20261110_dv25_archive_claims.sql` (nuevo, no aplicado a ninguna base real)
- `scripts/tests/test_document_viewer_dv25_security.py` (nuevo)
- `docs/document_viewer_dv25_security.md` (este informe)

No se modificaron tests certificados ni diálogos Flet.

## Comandos de verificación (pendientes de ejecutar por el runner)

```
python -m pytest scripts/tests/test_document_viewer_dv25_security.py -v
python -m pytest scripts/tests/test_document_viewer_dv23_*.py scripts/tests/test_document_viewer_dv24_*.py scripts/tests/test_document_viewer_dv25_*.py
python -m py_compile backend/services/document_inbox_service.py backend/services/document_viewer_filing_plan_service.py backend/services/document_viewer_box_archive_service.py backend/services/document_viewer_archive_permission_service.py backend/services/document_viewer_archive_repository.py scripts/tests/test_document_viewer_dv25_security.py
git diff --check
git status --porcelain
```

## Riesgos residuales

1. H1/H2 no aplicados en `execute_archive` (contrato P3B2; ver propuesta).
2. Sin autoridad transaccional compartida entre equipos: multi-equipo no resuelto.
3. H3 TOCTOU abierto en Windows/Box Drive; solo detección posterior.
4. H4 depende de que el visor copie siempre por nomenclatura (hoy cierto; fijado por el test P3B2).
5. H5: la reutilización de un idéntico preexistente sigue registrándose (trazada como no creada).
6. Sin heartbeat: copias de más de 15 min pasan a revisión humana.
7. Smoke Flet aislado no realizado.

## Recomendaciones

**(a) Integración de la rama con flag OFF:** viable **tras** el RUNNER_ACCEPTANCE de esta batería y de la
regresión DV23/DV24/DV25. Los cambios con la compuerta cerrada son de endurecimiento (lectores sin DDL,
preview más estricto, trazas de procedencia) y no habilitan escrituras nuevas.

**(b) Habilitación de Box REAL:** **NO apta.** Requiere: contrato de permiso aprobado e integrado (H1),
claim integrado en `execute_archive` sobre una base central compartida por todos los puestos (H2),
decisión y mitigación de H3 en Windows/Box Drive, y smoke Flet aislado. RUNNER_ACCEPTANCE no sustituye la
aprobación funcional humana de Dirección.
