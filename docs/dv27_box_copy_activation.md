# WO-DV27-P3B4 · «Archivar copia en Box» desde el visor, gobernado

**Base:** `feature/dv27-visor-box-copia` @ `c8146ac` (checkpoint DV26-UI1). Worktree nuevo; sin tocar CRM canónico,
`develop` ni `main`.
**Estado de la vía real:** `EXECUTION_ENABLED = False` en el código. **Box REAL NO habilitado.**

> **Evidencia de ejecución: PENDIENTE.** Este trabajo se hizo en una sesión sin terminal: no se ha ejecutado
> pytest, `compileall`, `git diff --check` ni se ha creado el checkpoint Git. El código y los tests se escribieron
> leyendo el código real y los contratos certificados. No hay RUNNER_ACCEPTANCE de DV27 hasta que el Runner ejecute
> la batería (comandos al final).

## Implementación validada vs. habilitada en producción

| | Estado |
|---|---|
| Circuito `ArchiveForm` → `execute_archive` → H1 → H2 → P3B1 | Implementado; validación **pendiente del Runner** |
| Habilitado en producción | **NO**. Bloqueado por `PERMISSION_CONTRACT_PENDING`, `MULTI_HOST_AUTHORITY_PENDING`, `TOCTOU_PREVENTION_PENDING` |

## Diagnóstico (código real antes de tocar)

- `execute_archive` copiaba con solo usuario activo + bloqueo en RAM (`_inflight`). Ni H1 ni H2 se aplicaban
  (lo dice `document_viewer_dv25_security.md`: «Preparado, no integrado»).
- `authorize_archive` (H1) y `run_intent`/`governed_box_copy` (H2) existen, probados aparte, sin cambios necesarios.
- P3B1 (`copy_inbox_item_to_expedient_box`): creación exclusiva `xb`, VERIFY por tamaño/SHA-256 y carpeta real, CAS
  en REGISTER, `create_missing=False` cuando se copia por nomenclatura (H4). H3 sigue abierto: entre
  `_box_destination_folder` y `open("xb")` un componente puede sustituirse por una unión; solo se detecta después.
- Contrato P3B2 (`ScopeTests`) fija exactamente una llamada a la copia con 3 kwargs y los atributos de
  `document_inbox_service` usados; se respeta.
- Planificador P3A acotado (`MAX_DEPTH = 4`, `MAX_FOLDERS = 500`, `iterdir` por nivel, sin `rglob`/`os.walk`).
- `ArchiveForm` ya deshabilita confirmación y botón cuando `execution_blocker()` no está vacío y muestra el motivo;
  no ha hecho falta tocarlo. «Vincular y archivar copia» (DV26) sigue deshabilitado y sin handler.

## Cambios (diff localizado)

### `backend/services/document_viewer_box_archive_service.py`

- Importa `document_viewer_archive_permission_service as permission` y
  `document_viewer_archive_repository as intents`.
- Constantes nuevas, todas cerradas en el código: `SINGLE_HOST_APPROVED = False` (decisión formal de operar en un
  solo puesto), `H3_WRITE_CONTAINMENT_VERIFIED = False`, `REVIEW_MAX_AGE = 15 min`; códigos
  `PERMISSION_CONTRACT_PENDING`, `MULTI_HOST_AUTHORITY_PENDING`, `TOCTOU_PREVENTION_PENDING`.
- `EXECUTION_DISABLED` ahora enumera los tres códigos (motivo concreto en el diálogo).
- `activation_blockers()`: códigos pendientes para la vía real (hoy los tres).
- `execution_blocker()`: compuerta cerrada ⇒ `EXECUTION_DISABLED`; abierta (solo sandbox) ⇒ además exige contrato
  (`PERMISSION_PENDING`) y autoridad (`MULTI_HOST_PENDING`).
- `execute_archive`, antes de revisar de nuevo y de copiar nada:
  1. revisión caducada ⇒ `EXPIRED`;
  2. H1 `_authorize`: `permission.authorize_archive`; sin contrato ⇒ `PERMISSION_PENDING`, rechazo/error ⇒ su
     mensaje; la decisión debe ser sobre el mismo usuario verificado;
  3. H2 `_intent_store`: `SqliteArchiveIntentStore` sobre la BD revisada + sonda de lectura; sin migración, base
     habitual o error ⇒ `INTENTS_UNAVAILABLE`; sin autoridad compartida ni `SINGLE_HOST_APPROVED` ⇒ `MULTI_HOST_PENDING`.
- `_governed_copy`: cada documento es un `ArchiveIntent` ejecutado con `intents.run_intent(...,
  intents.governed_box_copy(intent, copy=certified_copy), evidence=registered_copy_evidence)`. `certified_copy` es la
  **única** llamada a `copy_inbox_item_to_expedient_box` (mismos 3 kwargs). Resultados:

| `run_intent` | Resultado en el visor | Lote |
|---|---|---|
| `done` | comprobación `_confirmed` (como P3B2) ⇒ `archived` / `failed` | sigue / se detiene |
| `refused` (P3B1 rechazó sin escribir) | `rejected` con el motivo; reintentable con nueva revisión (`fence+1`) | sigue |
| `review_required` por `BoxCopyIncomplete` | `incomplete` + archivo a revisar; nunca se borra ni reintenta | se detiene |
| `review_required` por error desconocido | `failed` «pendiente de revisión humana» | se detiene |
| copia hecha pero solicitud no cerrada / `fenced` | `failed` + ruta escrita | se detiene |
| `in_progress` (otro titular, cualquier clave del ítem) | `rejected` `IN_FLIGHT` | sigue |
| claim caducado / en revisión / ya cerrado | `rejected` con el motivo; no se copia | sigue |

- El bloqueo en RAM (`_inflight`) se conserva como primera barrera dentro del proceso.

### `scripts/tests/test_document_viewer_dv25_box_from_viewer.py` (solo fixture H1/H2)

Contrato superior explícito (H1/H2 obligatorios en `execute_archive`): `ArchiveBase.setUp` añade exactamente lo que
proponía `document_viewer_dv25_security.md` («Propuesta mínima para Dirección»):

- `intents.apply_schema(self.db)` sobre la BD temporal, y se vuelve a tomar `schema_before` (FilingBase compara el
  esquema en `tearDown`);
- `APPROVED_CONTRACT` = `SandboxContract` (concede solo a `ana`, id 1);
- `SINGLE_HOST_APPROVED = True` solo en el sandbox.

Ninguna aserción se ha relajado ni eliminado. `ViewerSafetyTests` (suite de seguridad) hereda este fixture.

### Nuevos

- `scripts/tests/test_dv27_box_copy_activation.py`
- `docs/dv27_box_copy_activation.md` (este documento)

### Sin cambios

`document_inbox_service.py` (P3B1 y Bandeja intactos: no se altera `copied_to_box`), permiso, repositorio,
migraciones, `document_viewer_archive_dialog.py`, `document_viewer_link_dialog.py`, `test_document_viewer_dv25_security.py`.

## H1 / H2 / H3

**H1 · Permiso — integrado, DENIED por defecto.** `APPROVED_CONTRACT = None` ⇒ ningún usuario archiva, aunque esté
activo o declare `role`/`permissions`. El contrato se consulta una vez, solo con el usuario verificado. Rechazo,
valor no `True` o excepción ⇒ DENIED. **Bloqueo:** `PERMISSION_CONTRACT_PENDING` (Dirección debe decidir qué
permiso habilita archivar y dónde se persiste; no se ha inventado ningún rol).

**H2 · Solicitud persistente — integrada; multi-equipo NO resuelto.** Claim atómico, clave canónica sin actor,
índice parcial por ítem, fencing, sin reintento automático, conciliación por evidencia de Bandeja. Garantía real solo
entre procesos sobre **la misma** base. Dos bases locales conceden ambas el mismo claim (probado). El almacén rechaza
por diseño `database/quesada.db` hasta que exista el proceso de migración aprobado. **Bloqueo:**
`MULTI_HOST_AUTHORITY_PENDING` (base central compartida — DATA-008 — o decisión formal de un solo puesto).

**H3 · TOCTOU de carpeta — NO mitigado.** No se ha implementado la mitigación por handle de directorio
(`CreateFileW` con `FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS` sin `FILE_SHARE_DELETE` en cada
componente durante la copia). Motivo: es código Win32 (ctypes) en la ruta física compartida con Bandeja y en esta
sesión no se podía ejecutar ni validar, tampoco con Box Drive (filtro de nube). Implementarlo sin pruebas sería
improvisar en la ruta certificada. El test DV27 `test_h3_folder_swap_is_only_detected_after_the_write` lo deja
explícito: por el visor, la escritura **sale** por la unión, P3B1 la detecta en VERIFY, el visor informa
`incomplete`, la solicitud queda `needs_review`, no se registra ni se borra. **Detección, no prevención.**
**Bloqueo:** `TOCTOU_PREVENTION_PENDING`.

`H3_WRITE_CONTAINMENT_VERIFIED` no se comprueba en tiempo de ejecución (el fixture P3B2 solo está autorizado para
H1/H2): la única barrera H3 es la compuerta `EXECUTION_ENABLED = False`, protegida por los tests AST de DV27. Además,
en producción H1 y H2 fallan cerrados por sí solos (sin contrato; almacén que rechaza la base habitual).

## Pruebas nuevas (`test_dv27_box_copy_activation.py`)

| Clase | Qué prueba |
|---|---|
| `GateTests` | AST: `EXECUTION_ENABLED`, `SINGLE_HOST_APPROVED`, `H3_WRITE_CONTAINMENT_VERIFIED` = False, `APPROVED_CONTRACT` = None, `MULTI_HOST_GUARANTEE` = False; tres códigos pendientes; resolver uno no libera los otros; valores «truthy» no cuentan; compuerta abierta sigue exigiendo H1/H2 |
| `ScopeTests` | Una sola copia física, dentro de `certified_copy`, pasada como `copy=` a `governed_box_copy`; `_authorize`/`_intent_store` antes de `_execute_one`; sin `rglob`/`glob`/`walk`/`scandir`/`listdir`/`iterdir` en el servicio |
| `PermissionTests` | Sin contrato (también con roles declarados por el cliente) ⇒ DENIED; contrato que rechaza, devuelve 1/"yes", o lanza ⇒ DENIED; sin actor, falsificado, desconocido, inactivo ⇒ DENIED; decisión sobre otro usuario ⇒ DENIED; contrato que concede ⇒ una copia, vínculo intacto, evento `copied_to_box`, solicitud `registered` |
| `IntentTests` | Doble clic ⇒ una copia y una solicitud; sin migración o sobre la base habitual ⇒ nada; sin autoridad ⇒ `MULTI_HOST_PENDING`; dos bases independientes ⇒ ambas conceden (no hay coordinación); claim de otro proceso en la BD compartida (otra clave) ⇒ `IN_FLIGHT`; dos ejecuciones paralelas sin memoria compartida ⇒ una copia |
| `CrashTests` | Crash antes de COPY, durante COPY (archivo parcial), entre VERIFY y REGISTER, después de REGISTER: en curso mientras dura el lease, después revisión humana; nunca se reintenta ni se borra; tras REGISTER se concilia por evidencia sin nueva copia |
| `SafetyTests` | Colisión: homónimo intacto, una sola creación exclusiva; revisión caducada; H3 (arriba); ejecución acotada: sin `rglob`/`glob`/`os.walk`, `iterdir` ≤ 2·(MAX_FOLDERS+1) y siempre dentro de la raíz del expediente |
| `ViewerTests` | Con cada bloqueo, el diálogo muestra el motivo concreto, mantiene la revisión (destino y nombre), no toma el consentimiento ni copia; disponible ⇒ destino, nombre y resultado real; doble clic sin duplicar |

Todas sobre `ArchiveBase`: TemporaryDirectory, SQLite sintética, Box sintético comparado byte a byte, guardas sin
`mkdir`/`rename`/`remove`/`unlink`/`shutil`, original de Bandeja con mismo contenido y mtime, `quesada.db` sin cambios.

**Carrera entre procesos reales:** la de procesos independientes sobre la misma base vive en
`test_document_viewer_dv25_security.MultiProcessTests` (usa `run_intent` + `governed_box_copy`, la misma ruta que
ahora usa el visor). En DV27 la carrera se reproduce con hilos sin memoria compartida y con un claim de «otro
proceso» insertado en la BD compartida; no hay un subproceso que lance `execute_archive` completo.

## Comandos para el Runner

```
python -m pytest -q scripts/tests/test_dv27_box_copy_activation.py
python -m pytest -q scripts/tests/test_document_viewer_dv25_box_from_viewer.py scripts/tests/test_document_viewer_dv25_security.py scripts/tests/test_document_viewer_dv25_box_hardening.py scripts/tests/test_dv25_bandeja_compat.py
python -m pytest -q scripts/tests/test_document_viewer_dv23_close.py scripts/tests/test_document_viewer_dv23_pdf_tools.py scripts/tests/test_document_viewer_dv23_visual.py scripts/tests/test_document_viewer_dv24_linking.py scripts/tests/test_document_viewer_dv24_multidoc.py scripts/tests/test_document_viewer_dv24_notes.py scripts/tests/test_document_viewer_dv25_filing_plan.py scripts/tests/test_document_viewer_dv25_selection.py scripts/tests/test_document_viewer_dv25_toolbar.py scripts/tests/test_dv25_documental_smoke.py scripts/tests/test_dv26_link_visual.py
python -m compileall -q backend/services/document_viewer_box_archive_service.py backend/services/document_viewer_archive_permission_service.py backend/services/document_viewer_archive_repository.py frontend/components/document_viewer_archive_dialog.py
git diff --check
git status --porcelain
```

Riesgos para el Runner: `test_execution_is_bounded_and_stays_inside_the_expediente_root` parchea `Path.iterdir`,
`Path.glob` y `os.walk` a nivel de clase; si alguna dependencia los usa internamente fallará y habrá que revisar
(no relajar). El test H3 crea una unión NTFS en el sandbox (`_winapi.CreateJunction`) y la retira antes del `tearDown`.

## Blockers explícitos

1. `PERMISSION_CONTRACT_PENDING` — contrato de permiso aprobado por Dirección.
2. `MULTI_HOST_AUTHORITY_PENDING` — base central compartida (DATA-008) o decisión formal de un solo puesto con
   garantías acotadas; más el proceso aprobado para aplicar `20261110_dv25_archive_claims.sql` a la base operativa.
3. `TOCTOU_PREVENTION_PENDING` — prevención H3 en Windows/Box Drive.
4. Evidencia: ejecución del Runner y smoke Flet aislado.

## Plan de activación final (cuando Dirección lo autorice)

1. Contrato de permiso: tabla de permisos versionada + implementación `grants(user, db_path=)`; instalarlo en
   `APPROVED_CONTRACT` (código, nunca desde la UI) con tests.
2. Autoridad: base central compartida o decisión mono-equipo (`SINGLE_HOST_APPROVED = True`) firmada; migración
   aplicada por el proceso aprobado (hoy `apply_schema` rechaza la base habitual).
3. H3: handles de directorio sin `FILE_SHARE_DELETE` durante COPY/VERIFY en P3B1, test de intercambio de ruta que
   demuestre que la escritura **no sale**, validación con Box Drive; entonces `H3_WRITE_CONTAINMENT_VERIFIED = True`.
4. Solo con `activation_blockers() == ()`: `EXECUTION_ENABLED = True`, actualizar `EXECUTION_DISABLED`, los tests AST
   de DV27/P3B2/seguridad/smoke, Runner completo, smoke Flet aislado y aprobación humana. Box REAL solo con
   autorización humana específica.
