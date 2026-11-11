# DV25 · C2/C3 — Compatibilidad sintética de Bandeja y smoke visual Flet aislado

**Orden de trabajo:** WO-DV25-C2-C3 · **Rama:** `feature/document-viewer-dv25-seleccion-nomenclatura`
(base `8baa93c5718ac199bc79acefc5a87007047e23b4`) · **Puerta del archivo desde el visor:**
`EXECUTION_ENABLED = False` (sin cambios) · `APPROVED_CONTRACT = None` (sin cambios).

> Un resultado sintético no prueba compatibilidad con unidades Box Drive reales. La puerta OFF del
> visor **no** es una aptitud para Box real y no debe presentarse como tal.

## 1. Estado

| Bloque | Estado | Nota |
|---|---|---|
| C1 | PASS (informado por el Runner) | 323 tests + 456 subtests, 14 suites, `git diff --check` = 0. |
| C2 OFFLINE | **PENDIENTE DE EJECUCIÓN** | Primera ejecución: 1 FAIL (expectativa falsa del test, sección 8). Corregido en FIX1; no reejecutado en la sesión de corrección. |
| C2 REAL | **PENDIENTE** | Requiere autorización humana separada (sección 4). Prohibido sin ella. |
| C3 `--check` + tests | **PENDIENTE DE EJECUCIÓN** | Primera ejecución: 7 FAIL + `CHECK=BLOCKED` (sección 8). Corregido en FIX1; no reejecutado en la sesión de corrección. |
| C3 visual (`--launch`) | **PENDIENTE** | Solo por acción humana; no hay PASS sin capturas (sección 5.3). |

Archivos de esta orden (los cuatro son nuevos; ningún archivo productivo ni test existente cambia):

1. `scripts/dev/dv25_documental_smoke.py`
2. `scripts/tests/test_dv25_documental_smoke.py`
3. `scripts/tests/test_dv25_bandeja_compat.py`
4. `docs/dv25_c2_c3_smoke_instructions.md`

## 2. Comandos de aceptación

```powershell
python -m pytest -q scripts/tests/test_dv25_documental_smoke.py scripts/tests/test_dv25_bandeja_compat.py
python scripts/dev/dv25_documental_smoke.py --check
python -m pytest -q scripts/tests/test_document_viewer_dv23_close.py scripts/tests/test_document_viewer_dv23_pdf_tools.py `
  scripts/tests/test_document_viewer_dv23_visual.py scripts/tests/test_document_viewer_dv24_linking.py `
  scripts/tests/test_document_viewer_dv24_multidoc.py scripts/tests/test_document_viewer_dv24_notes.py `
  scripts/tests/test_document_viewer_dv25_selection.py scripts/tests/test_document_viewer_dv25_toolbar.py `
  scripts/tests/test_document_viewer_dv25_filing_plan.py scripts/tests/test_document_viewer_dv25_box_hardening.py `
  scripts/tests/test_document_viewer_dv25_box_from_viewer.py scripts/tests/test_document_viewer_dv25_security.py
git diff --check
git status --porcelain --untracked-files=all
```

La lista anterior son las 12 suites `test_document_viewer_dv2*` del árbol. C1 contó 14 suites: las dos
restantes deben tomarse de la lista del Runner de C1 (no están identificadas en el repositorio).
`git status` debe mostrar solo las cuatro rutas de la sección 1 como no rastreadas.

## 3. C2 OFFLINE — botón «Copiar a Box expediente» de la Bandeja

### 3.1 Flujo real inspeccionado

- `frontend/views/document_inbox_view.py`: dos botones con la etiqueta «Copiar a Box expediente».
  - Panel de acciones → `copy_to_box()`: lee el ítem (`selected_item()` → `get_inbox_item`), toma el
    expediente seleccionado o el del ítem, la subcarpeta del campo «Subcarpeta Box destino» y llama a
    `document_inbox_service.copy_inbox_item_to_expedient_box(item_id, expedient_id=, subfolder=, target_filename=)`.
  - Ficha del documento → `detail_copy_to_box()`: fija cliente/expediente de la ficha, convierte el
    directorio elegido en relativo a la carpeta Box (`_normalize_box_subfolder_for_copy`), pasa el
    nombre de la nomenclatura como `target_filename` (sobrescrituras de un solo uso) y delega en
    `copy_to_box(open_expediente_after=False)`.
  - La vista **nunca** pasa `nomenclature_key`: usa la variante de P3B1 que **crea** subcarpetas que
    falten (la del visor no las recrea, H4). La vista no referencia `EXECUTION_ENABLED` ni el servicio
    de archivo del visor: la puerta OFF no afecta a este botón.
- `backend/services/document_inbox_service.py` (P3B1):
  - `ensure_document_inbox_schema()` en **cada** copia (DDL idempotente sobre la BD operativa).
  - Subcarpeta: `check_subfolder` (relativa, sin `..`, unidades, UNC, nombres reservados).
  - Origen: archivo bajo `INBOX_ROOT`, sin enlaces; SHA-256 igual al registrado.
  - Raíz Box (`box_folder_path`): rechaza por texto `\\`, `//`, `\\?\`, `\\.\` **antes** de tocar disco;
    exige ruta absoluta existente, sin enlace/unión (los marcadores de nube no cuentan como redirección).
  - Copia: creación exclusiva `xb`; nombre ocupado → `_2`, `_3`…; ocupante idéntico → reutilizado con
    procedencia `preexisting_unverified` u `own_unregistered_copy`.
  - COPY → VERIFY (tamaño + SHA-256 + carpeta real) → REGISTER (`copied_to_box` solo tras verificar).
  - Copia ya registrada e intacta → `already_copied`; registrada fuera de la raíz actual o distinta →
    «requiere revisión»; registrada y desaparecida → se permite una copia nueva.

### 3.2 Aislamiento de `test_dv25_bandeja_compat.py`

Reutiliza `BoxCopyBase` (P3B1) y `SandboxMixin` (P3B3) sin relajarlos: BD SQLite temporal con
`connection.DB_PATH`, `expedient_service.DB_PATH` y `get_connection` redirigidos y comprobados;
`sqlite3.connect` rechaza cualquier BD fuera del TEMP; Bandeja (`INBOX_*`) y Box sintéticos; prohibidos
borrar, mover, renombrar, enlazar y `shutil.copy*`; escrituras y `mkdir` fuera del sandbox fallan.
Añade: `os.open` de escritura fuera del sandbox, cualquier proceso hijo (`subprocess.Popen`), cualquier
`socket.connect`/`getaddrinfo` y cualquier llamada de sistema de archivos sobre rutas UNC/dispositivo
hacen fallar el test. Huella (tamaño, mtime, SHA-256) de `quesada.db` antes y después del módulo.
Los manejadores reales de la vista se ejecutan con `dv24.bind` (mismo mecanismo que DV24/DV25-P1).

### 3.3 Matriz C2 OFFLINE

| # | Caso | Test | Esperado | Resultado |
|---|---|---|---|---|
| 1 | Raíz local normal, panel de acciones | `LocalRootTests.test_button_copies_to_a_local_root_copy_verify_register` | Copia verificada y registrada; orden COPY→VERIFY→REGISTER; origen intacto; navega al expediente | PENDIENTE DE EJECUCIÓN |
| 2 | Ficha: directorio + nombre de nomenclatura | `test_detail_button_with_selected_directory_and_nomenclature_name` | Copia en `02 LABORAL/Contratos/CONTRATO DE TRABAJO.pdf`; sobrescrituras consumidas | PENDIENTE DE EJECUCIÓN |
| 3 | Subcarpeta inexistente (botón clásico) | `test_missing_subfolder_is_created_inside_the_root_by_the_classic_button` | Se crea dentro de la raíz (comportamiento existente) | PENDIENTE DE EJECUCIÓN |
| 4 | Directorio de ficha fuera de la raíz | `test_detail_directory_outside_the_root_is_refused` | Rechazo, sin archivo ni cambio de estado | PENDIENTE DE EJECUCIÓN |
| 5 | Subcarpetas hostiles (`..`, unidad, UNC, `CON`…) | `test_hostile_subfolders_from_the_panel_are_refused` | Rechazo sin escritura | PENDIENTE DE EJECUCIÓN |
| 6 | Raíz UNC / dispositivo (5 formas) | `NetworkAndLinkTests.test_unc_and_device_roots_are_refused_without_touching_the_network` | Rechazo por texto; ninguna llamada de E/S sobre la ruta; sin red | PENDIENTE DE EJECUCIÓN |
| 7 | Raíz que es enlace/unión | `test_root_that_is_a_link_or_junction_is_refused` | Rechazo (SKIP justificado si el equipo no permite crear uniones) | PENDIENTE DE EJECUCIÓN |
| 8 | Enlace/unión dentro de la raíz | `test_link_or_junction_inside_the_root_is_refused_and_never_followed` | Rechazo; nada escrito fuera | PENDIENTE DE EJECUCIÓN |
| 9 | Colisión con archivo distinto | `CollisionAndIntegrityTests.test_existing_name_is_never_overwritten` | `_2`, original intacto, solo modo `xb` | PENDIENTE DE EJECUCIÓN |
| 10 | Duplicado idéntico previo | `test_identical_previous_file_is_reused_with_its_provenance` | Reutilizado, `preexisting_unverified`, no atribuido | PENDIENTE DE EJECUCIÓN |
| 11 | Doble pulsación secuencial | `test_pressing_twice_copies_once` | `already_copied`, sin eventos nuevos, árbol Box idéntico byte a byte, ninguna escritura nueva | PENDIENTE DE EJECUCIÓN |
| 11b | Doble pulsación simultánea desde dos procesos | `test_double_press_protection_is_in_process_only` | Documenta el residual: el cerrojo es `threading.Lock` del proceso; sin protección entre procesos (sección 3.4.5) | PENDIENTE DE EJECUCIÓN |
| 12 | Origen cambiado / fuera de Bandeja | `test_changed_source_is_refused_and_never_copied`, `test_source_outside_bandeja_is_refused` | Rechazo | PENDIENTE DE EJECUCIÓN |
| 13 | Destino retirado | `DestinationChangeTests.test_removed_root_is_refused_and_not_recreated` | Error «no existe en este equipo»; no se recrea | PENDIENTE DE EJECUCIÓN |
| 14 | Destino cambiado tras copiar | `test_root_changed_after_the_copy_requires_review` | «requiere revisión»; nada en la raíz nueva | PENDIENTE DE EJECUCIÓN |
| 15 | Copia registrada borrada en Box | `test_registered_copy_removed_in_box_is_copied_again` | Copia nueva (recuperación) | PENDIENTE DE EJECUCIÓN |
| 16 | Expediente sin Box / de otro cliente | `test_expedient_without_box_folder_or_of_another_client` | Rechazo | PENDIENTE DE EJECUCIÓN |
| 17 | Cableado de botones y puerta | `WiringTests` | Dos botones → manejadores reales; una llamada al servicio; sin referencia a la puerta | PENDIENTE DE EJECUCIÓN |
| 18 | Unidad de red mapeada (`Z:`) | `test_mapped_network_drive_letter` | — | **NO PROBADO** (SKIP justificado) |
| 19 | Raíz real de Box Drive y marcadores de nube | `test_real_box_drive_root_and_cloud_placeholders` | — | **NO PROBADO** (SKIP; C2 REAL) |

Sustituir «PENDIENTE DE EJECUCIÓN» por PASS/FAIL solo con la salida de `pytest` adjunta.

### 3.4 Hallazgos de la inspección (relevantes para C2 REAL)

1. **Unidades asignadas a red:** `_authorized_box_root` solo reconoce rutas de red por el prefijo de texto.
   Una letra de unidad asignada a un recurso compartido (o un `subst`) se trataría como local.
2. **DDL en cada copia:** el botón ejecuta `ensure_document_inbox_schema()` sobre la BD operativa antes de
   copiar (comportamiento previo a DV25, no introducido aquí).
3. **Subcarpetas creadas por el botón clásico:** a diferencia del visor (H4), el botón crea las subcarpetas
   que falten dentro de la raíz; si una carpeta fue retirada en Box a propósito, el botón la recrea.
4. **Directorio absoluto en la ficha:** si no cuelga de la carpeta Box del expediente se pasa tal cual y lo
   rechaza el validador (seguro, mensaje genérico de subcarpeta no válida).
5. **Doble pulsación entre procesos (PENDIENTE):** la idempotencia del botón es el estado `copied_to_box` con
   la copia registrada intacta, comprobado bajo `_box_copy_lock` (`threading.Lock` por proceso). Dos procesos
   del CRM que pulsen a la vez no se coordinan: la creación exclusiva `xb` produce `Pasaporte_2.pdf` en vez de
   sobrescribir (caso 9). No es una sobrescritura ni pérdida de datos; la protección entre procesos sigue
   pendiente y no se resuelve en esta orden.

## 4. C2 REAL — PENDIENTE (requiere autorización humana separada)

No ejecutar sin una autorización escrita específica que nombre el equipo y el alcance. Este documento no
la concede. Cuando exista, el procedimiento propuesto es **solo de lectura** y no copia nada:

1. Sobre el equipo autorizado, en una consola sin el CRM abierto, listar los valores distintos de
   `expedientes.box_folder_path` mediante una copia de la BD (nunca la BD habitual en uso) abierta en modo
   `?mode=ro`.
2. Para una muestra acordada de esas rutas, registrar sin abrir archivos: tipo de unidad (local, asignada a
   red, `subst`), si la carpeta es punto de reanálisis y su etiqueta (`st_reparse_tag`), longitud de ruta,
   y si la raíz de Box Drive está bajo el perfil del usuario.
3. Contrastar con la sección 3.4: cualquier raíz en unidad asignada a red o con etiqueta distinta de los
   marcadores de nube es un bloqueo para C2 REAL.
4. Una copia real de prueba exige una segunda autorización, un expediente de prueba acordado y un archivo
   sintético; queda fuera de esta orden.

Resultado actual: **NO PROBADO / PENDIENTE**.

## 5. C3 — Smoke visual Flet aislado

### 5.1 `--check` (sin Flet, sin escrituras)

```powershell
python scripts/dev/dv25_documental_smoke.py --check            # opcional: --expect-head <sha>
```

Comprueba y muestra: `BRANCH`/`HEAD` (bloquea `main`/`master`, HEAD desacoplado u otra rama), la puerta en
el código (`EXECUTION_ENABLED=False`, `APPROVED_CONTRACT=None`, leídos por AST), que el destino previsto
sería un directorio nuevo bajo TEMP fuera de todo checkout (reutiliza `crm_it_sandbox_launcher`), el
entorno mínimo del proceso hijo (lista blanca, sin claves sensibles), los predicados de las guardas y la
clasificación de cada constante de ruta del cierre de importaciones del visor (`db-redirect`,
`write-redirect`, `read-only`; cualquier `UNREVIEWED` bloquea). Imprime `CHECK=PASS` (código 0) o
`CHECK=BLOCKED` con `BLOCKER=…` (código 2), y siempre `FLET_LAUNCHED=NO`, `WRITES=NONE`. No importa el CRM
ni Flet, no abre bases de datos y no usa `tempfile.gettempdir()` (que crea un archivo de prueba).

### 5.2 `--launch` (solo por acción humana)

```powershell
python scripts/dev/dv25_documental_smoke.py --launch
```

1. Repite `--check`; si bloquea, no crea nada.
2. Crea `%TEMP%\dv25_smoke_<aleatorio>` con un sello y arranca un proceso hijo (`python -E -B`, entorno de
   lista blanca, `cwd` en ese directorio).
3. El hijo instala las guardas **antes** de importar el CRM: `sqlite3.connect` fuera del sandbox, escrituras
   fuera de TEMP/`~/.flet`, `os.startfile`, procesos que no sean el cliente de Flet y conexiones no locales
   lanzan error y se registran.
4. Redirige toda `DB_PATH` cargada (incluidas `database.connection.DB_PATH` y `expedient_service.DB_PATH`),
   la Bandeja, la caché de previsualizaciones y la carpeta de herramientas PDF al sandbox.
5. Crea la BD sintética (fixtures DV24 + catálogo P3A), 10 PDF sintéticos en la Bandeja, la raíz Box
   simulada (`box/EXP-42`, `box/EXP-43`) y aplica la migración de notas. Verifica rutas efectivas; si algo
   no cuadra imprime `BLOCKED` y **Flet no se abre**.
6. Abre Flet: listado mínimo de la Bandeja sintética (casillas y «Ver seleccionados» con
   `marked_queue`/`bulk_action_bar` reales) que abre `open_document_viewer_modal` real con notas,
   vinculación y barra PDF reales (herramientas sin manejadores: deshabilitadas con su motivo).
7. Al cerrar la ventana imprime `DDL_AFTER_LAUNCH=<n> UNEXPECTED_DDL=<m> SCHEMA_CHANGED=<YES|NO>
   BLOCKED_ACCESSES=<k>` (y una línea `UNEXPECTED_DDL=` por cada DDL no tolerado). Resultado aceptable:
   `UNEXPECTED_DDL=0 SCHEMA_CHANGED=NO BLOCKED_ACCESSES=0`; `DDL_AFTER_LAUNCH` será mayor que 0 (ver
   nota V10). El script no borra el sandbox: eliminarlo a mano cuando se hayan guardado las evidencias.

Límites (no es aislamiento del sistema operativo): las guardas viven en el proceso Python; el cliente de
escritorio de Flet es otro proceso y puede usar su caché (`~/.flet`) y el TEMP; el proceso puede **leer**
lo que el usuario puede leer; rutas de BD ligadas como argumento por defecto no se redirigen (las cubre la
guarda de `sqlite3.connect`); conexiones solapadas de asyncio y procesos lanzados por asyncio no pasan por
las guardas.

### 5.3 Matriz C3 (capturas obligatorias para PASS)

| # | Comprobación | Evidencia automática | Visual (`--launch`) |
|---|---|---|---|
| V0 | `--check` = PASS sin escrituras, sin Flet ni CRM cargados | `CheckTests.test_check_reads_only_and_never_loads_flet_or_the_crm` — PENDIENTE DE EJECUCIÓN | Salida de consola — PENDIENTE |
| V1 | Cabecera con ruta TEMP y «EXECUTION_ENABLED = False» | — | Captura — PENDIENTE |
| V2 | Marcar 2 → «Ver seleccionados» abre el visor real con 2 documentos | `SandboxViewerTests.test_two_and_four_marked_documents_open_the_real_viewer` — PENDIENTE DE EJECUCIÓN | Captura — PENDIENTE |
| V3 | «Comparador 4» con 2 y con 4 documentos; «Documento único» | ídem | Captura — PENDIENTE |
| V4 | Plegar/desplegar «Herramientas PDF» | ídem | Captura — PENDIENTE |
| V5 | Zoom + / − | ídem | Captura — PENDIENTE |
| V6 | Panel «Notas y actividad» (añadir una nota escribe solo en la BD sintética) | `layout.notes` presente | Captura — PENDIENTE |
| V7 | «Vincular a expediente»: vista previa P3A; «Vincular y archivar copia» deshabilitado | `test_link_dialog_shows_the_p3a_preview_with_its_archive_disabled` — PENDIENTE DE EJECUCIÓN | Captura — PENDIENTE |
| V8 | «Archivar en Box»: solo revisión, confirmación y envío deshabilitados, motivo visible | `test_archive_review_stays_closed_and_writes_nothing` — PENDIENTE DE EJECUCIÓN | Captura — PENDIENTE |
| V9 | «Cerrar» | ídem V2 | Captura — PENDIENTE |
| V10 | Contadores «Otro DDL tras abrir Flet: 0 · Accesos bloqueados: 0» tras navegar; salida final `UNEXPECTED_DDL=0 SCHEMA_CHANGED=NO` | `tearDown` de `SandboxViewerTests` (DDL ⊆ `INBOX_SCHEMA_DDL`, esquema idéntico) | Captura + salida final — PENDIENTE |
| V11 | Ninguna BD fuera del sandbox; Box simulado y filas de Bandeja sin cambios al navegar | `tearDown` + huella de `quesada.db` | — |

Nota V7: el test elige el expediente 42 y comprueba la tabla de previsualización P3A (una fila por
documento marcado) y el aviso «sin reserva ni persistencia»; nunca confirma. Confirmar una vinculación en
`--launch` ejecuta `link_inbox_item` (escritura real, solo en la BD sintética).

Nota V10: abrir el visor carga la actividad de notas (`document_activity` → `get_inbox_events()`), que ejecuta
`ensure_document_inbox_schema()`: `CREATE TABLE/INDEX IF NOT EXISTS` sobre tablas ya existentes. El autorizador
de SQLite lo registra como intento de DDL aunque no cambie nada. Es comportamiento productivo previo a DV25 (el
lector `get_inbox_item` ya se corrigió en P3B3/H6; `get_inbox_events` no). Por eso el contador «DDL idempotente
de Bandeja» sube en cada apertura; cualquier otro DDL o un cambio de esquema es FAIL.

C3 no se declara PASS hasta que V0–V10 tengan captura o salida adjunta.

## 6. Riesgos residuales heredados (P3B3)

- **H1 — Permiso:** `APPROVED_CONTRACT = None`; sin contrato aprobado todos los usuarios quedan denegados
  para archivar desde el visor. Instalar un contrato es decisión de Dirección.
- **H2 — Idempotencia entre equipos:** `MULTI_HOST_GUARANTEE = False`. La reclamación solo coordina procesos
  que comparten **una** BD; dos equipos con BD propias pueden copiar los dos (posible `_2`).
- **H3 — Carrera tras validar la carpeta (TOCTOU):** si la carpeta se sustituye por un enlace entre la
  validación y la creación, la copia se detecta en VERIFY y no se registra, pero el archivo ya escrito
  queda fuera; en Windows Python no puede crear relativo a un descriptor de carpeta.

Ninguno se resuelve en esta orden. Ninguno se resuelve con la puerta OFF.

## 7. Normativa aplicada

DOC-003 (COPY → VERIFY → REGISTER, verificado por orden de llamadas en C2); UI-001 (el script no ejecuta SQL
desde controles Flet: la BD sintética se crea antes de abrir Flet y `schema_snapshot` solo se toma antes y
después de `ft.run`); DATA-008 (sin nuevas dependencias SQLite en negocio: solo scripts y tests); sin cambios
en `main`, sin push ni merge, sin Box real, sin cambios en el CRM habitual.

## 8. WO-DV25-C2-C3-FIX1 — diagnóstico de la primera ejecución y corrección

Primera ejecución (Runner): `8 failed, 30 passed, 2 skipped, 40 subtests passed`; `--check` = `CHECK=BLOCKED`.
Ninguno de los 8 fallos es un defecto productivo. Solo cambian las cuatro rutas de esta orden; ningún
código productivo, test certificado, `EXECUTION_ENABLED` ni `APPROVED_CONTRACT`.

| Fallo | Causa real | Corrección |
|---|---|---|
| `test_closure_is_fully_classified_and_redirected`, `test_check_reads_only_and_never_loads_flet_or_the_crm` (`BLOCKER=MODULE_NOT_FOUND:frontend.app_*` ×13) | Error del recorrido estático: en un `__init__.py`, `from .app_button import …` se resolvía contra el paquete padre (`frontend`) y no contra el propio paquete (`frontend.components`). Los módulos existen. | `_resolve_import` distingue paquete y módulo. Los 13 `app_*` se recorren de verdad (solo importan `flet`, sin constantes de ruta). Un módulo que falta de verdad sigue bloqueando (`test_a_missing_project_module_still_blocks`); un módulo resuelto con constante sin revisar también (`test_relative_imports_of_a_package_init_are_followed`). No se suaviza `CHECK=BLOCKED`. |
| `test_gate_is_only_read_never_assigned_or_patched` | El test prohibía cualquier llamada con el literal `"EXECUTION_ENABLED"`, incluida la lectura por AST que exige `--check`. | Solo `literal_assignments(ARCHIVE_SERVICE \| PERMISSION_SERVICE, …)` puede nombrar la puerta; se prohíben además asignaciones por subíndice y argumentos con nombre. La lectura no importa ni escribe. |
| 4 × `SandboxViewerTests` (`tearDown`: `ddl == []`) | Expectativa falsa: abrir el visor ejecuta `CREATE TABLE IF NOT EXISTS` vía `get_inbox_events()` (nota V10). Los cuerpos de los tests pasaban. | Se tolera solo `INBOX_SCHEMA_DDL`, atribuido con un espía de `ensure_document_inbox_schema` (que ejecuta el código real), y se exige un esquema idéntico (`schema_snapshot`). El test del enlace comprueba ahora la vista previa P3A real sin confirmar. |
| `test_pressing_twice_copies_once` | Expectativa falsa: en Windows `rglob("Pasaporte*")` no distingue mayúsculas y encontraba el `PASAPORTE SOLICITANTE.pdf` sembrado por P3B1. La segunda pulsación sí devolvía `already_copied`. | Se compara el árbol Box completo byte a byte y el número de escrituras. Residual entre procesos documentado (3.4.5, caso 11b). |

**Hallazgo para Dirección (no bloquea el cierre y no se corrige aquí):** `get_inbox_events()` es un lector
que todavía ejecuta `ensure_document_inbox_schema()` (DDL idempotente y `_ensure_dirs()`) en cada apertura del
visor, igual que `get_inbox_item` antes de P3B3/H6. Corregirlo exige un parche productivo mínimo separado.

Pendiente de evidencia: las cuatro órdenes de aceptación del Runner (sección 2) y las capturas V0–V10. La
sesión de corrección no tenía consola: no ejecutó pytest, `--check` ni `git diff --check`.
