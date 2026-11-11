# WO-DV25-P3B2 · Archivar copia en Box desde el visor (P3B2-FIX-ARQ-A)

Rama `feature/document-viewer-dv25-seleccion-nomenclatura`, base P3B1 `7d200f5`.
Desarrollo nuevo (opción A aprobada) tras el bloqueo CONTRACT_SCOPE: la copia física **no** se
invoca desde `document_viewer_link_dialog.py` ni desde `document_viewer_filing_plan_service.py`
(sus tests P3A, P3B1 y DV24 prohíben incluso nombrar la primitiva). Se añade una puerta nueva.

**Estado de la vía real: CERRADA** (`EXECUTION_ENABLED = False` en el código). La revisión
funciona; la copia desde el visor queda deshabilitada hasta una resolución dedicada del riesgo
entre procesos (ver «Riesgos residuales») y la aprobación de Dirección tras smoke visual.

## Diagnóstico de partida (código local)

| Pieza | Contrato real |
|---|---|
| P3B1 `copy_inbox_item_to_expedient_box(item_id, expedient_id=None, subfolder="", target_filename="", *, nomenclature_key="")` | COPY -> VERIFY -> REGISTER, `open("xb")`, nunca sobrescribe; crea subcarpetas que falten; bloqueo por ítem **solo dentro del proceso**. Al registrar escribe `expedient_id = destino`, `client_id = COALESCE(client_id, cliente del expediente)`, `status = 'copied_to_box'`, rutas y evento `copied_to_box`. |
| Consecuencia | Si el ítem no estuviera vinculado al mismo destino, la copia cambiaría su vinculación como efecto colateral. Por eso P3B2 solo archiva ítems **ya** `linked` al mismo cliente y expediente (IDs positivos, no NULL). Con esa precondición, el `UPDATE` de P3B1 no cambia cliente ni expediente. |
| P3A `document_viewer_filing_plan_service` | `load_context`, `verify_folder`, `build_preview` (nombres y colisiones proyectados), `nomenclature_filename`. Solo lectura; no se modifica. |
| `document_inbox_service.get_inbox_item` | Ejecuta `ensure_document_inbox_schema` (DDL + `mkdir`): **no** se usa en la revisión; se lee el ítem con `connection.get_readonly_connection`. |

## Cambios (solo las 5 rutas autorizadas)

| Archivo | Cambio |
|---|---|
| `backend/services/document_viewer_box_archive_service.py` | **Nuevo.** Única puerta de orquestación/autorización del archivado desde el visor. |
| `frontend/components/document_viewer_archive_dialog.py` | **Nuevo.** Diálogo Flet `ArchiveForm`; solo habla con el servicio nuevo. |
| `frontend/components/document_viewer_link_dialog.py` | Delta mínimo en `LinkController`: comando `Archivar en Box` / `Archivar seleccionados` en la fila de información e import tardío de `ArchiveForm`. `LinkForm` (DV24/P3A) intacto, incluido su `Vincular y archivar copia` deshabilitado. |
| `scripts/tests/test_document_viewer_dv25_box_from_viewer.py` | **Nuevo.** Suite P3B2. |
| `docs/document_viewer_dv25_p3b2.md` | Este documento. |

Sin cambios de esquema, migraciones, `document_inbox_service.py`, `document_viewer_filing_plan_service.py`,
`document_viewer_modal.py`, `database/connection.py`, `app/main.py` ni tests anteriores.

## API del servicio (`document_viewer_box_archive_service`)

```python
execution_blocker() -> str                       # "" si la vía real está abierta; si no, el motivo
read_document(document, *, db_path=None) -> ArchiveItem                      # solo lectura
inspect_archive(actor, documents, *, db_path=None) -> ArchiveInspection      # solo lectura
prepare_archive(actor, documents, *, client_id, expedient_id, folder=None,
                choices=None, db_path=None) -> ArchivePlan                   # solo lectura
execute_archive(plan, *, confirmed, fingerprint) -> ArchiveResult            # única escritura
```

- `documents`: peticiones del visor `{"key", "name", "path", "inbox_item_id"}` (`ViewerLinking.request`).
- `folder`: ruta relativa POSIX de una carpeta **existente y listada** del expediente (`""` = raíz).
- `choices`: `{clave de documento: clave de nomenclatura del catálogo de ESE expediente}`; cualquier
  otro tipo o valor se ignora (queda «sin nomenclatura»).
- `ArchiveItem.outcome`: `ready`, `pending` (falta carpeta o nomenclatura), `not_archivable` (sin
  ítem de Bandeja), `rejected`. `ArchiveOutcome.status`: además `archived`, `failed`,
  `incomplete` (copia sin registrar: `written_path`), `not_attempted`.
- `ArchivePlan`: destino, contexto P3A, carpeta verificada, documentos revisados, `fingerprint`
  (SHA-256 de usuario, cliente, expediente, raíz, carpeta y, por documento: clave, ID, estado,
  instantánea del ítem y del archivo —ruta, `updated_at`, vínculo, tamaño, `mtime_ns`, SHA-256—,
  nomenclatura y nombre proyectado) y `token` de un solo uso.
- `ArchiveError(ValueError)`: rechazo visible, siempre antes de escribir.

## Flujo

1. **Visor** (`LinkController`): `Archivar en Box` (documento activo) o, en `Comparador 4`,
   `Archivar seleccionados` (instantánea de la selección al abrir, ordenada por posición). Deshabilitado
   con motivo si no hay ítem de Bandeja. Un solo diálogo (vincular o archivar) a la vez.
2. **Inspección** (`inspect_archive`): usuario de sesión verificado (`users`, activo, mismo nombre);
   por documento: ítem existente, archivo vigente = `stored_path`, bajo `INBOX_ROOT`, no descartado
   ni duplicado, no copiado (`copied_to_box` o `copied_to_box_path`), estado `linked` con cliente y
   expediente; SHA-256 actual = registrado. Destino = el **único** (cliente, expediente) vinculado,
   verificado con `resolve_target` (existe, activo, del cliente). Destinos mezclados -> rechazo.
3. **Revisión** (`prepare_archive`, en cada cambio de carpeta o nomenclatura): contexto P3A fresco,
   carpeta verificada, nombres y colisiones de `build_preview` (serie `nombre_2…`, sin reservar),
   validación P3B1 del nombre (`nomenclature_filename`). Tabla origen -> subcarpeta -> nombre final.
4. **Consentimiento**: casilla propia, inicialmente vacía y deshabilitada; se habilita con ≥1
   documento listo y vía abierta. Marcarla fija la huella consentida. Cualquier cambio crea una
   revisión nueva y borra el consentimiento. `Archivar copia en Box` deshabilitado hasta entonces.
5. **Ejecución** (`execute_archive`): `confirmed is True`, vía abierta, huella = la consentida, plan no
   ejecutado (cerrojo no bloqueante: doble clic -> `IN_PROGRESS`; repetición -> mismo resultado;
   copia del objeto plan -> `REPLAYED`), BD de la revisión = BD del CRM, mismo usuario activo.
   **Revisión completa de nuevo** y comparación de huellas (cualquier cambio -> `STALE`, nada copiado).
   Se ejecutan los documentos recién revisados (nunca campos del objeto plan). Por documento, justo
   antes de copiar: relectura del ítem y del archivo (instantánea idéntica), carpeta verificada y
   reclamación en proceso del ítem (`IN_FLIGHT` si otra operación lo archiva). Llamada explícita a
   P3B1 con `expedient_id`, `subfolder` verificada y `nomenclature_key`. Se comprueba la respuesta real
   (`copied_to_box`, mismo cliente/expediente, destino dentro de la carpeta, `result` `copied` o
   `reused_identical`) antes de declarar `archived`; se informa el nombre efectivo.
6. **Lote**: no atómico, orden determinista (el del visor). Rechazo o desactualización de un documento
   -> se omite y sigue. `incomplete` o fallo inesperado -> se detiene; el resto queda `not_attempted`.
   Un resultado parcial nunca se muestra como éxito (color de aviso/error y «Resultado parcial»).
7. **Reintento**: es una revisión nueva; los ya copiados se rechazan (`ALREADY_COPIED`), sin duplicar.

Cancelar, cerrar, cerrar el visor, navegar, zoom, cambiar de modo/comparador, cambiar la selección o
ejecutar `Vincular` no escriben nada en Box ni pasan por el servicio de copia.

## Pruebas

`scripts/tests/test_document_viewer_dv25_box_from_viewer.py` (sobre `FilingBase` de P3A y
`ViewerBase` de DV24): TemporaryDirectory, SQLite temporal (`connection.DB_PATH` redirigido;
`get_connection`/`get_readonly_connection` envueltos: abrir otra BD falla y se registra; `quesada.db`
comparado por `mtime` en tearDown), `INBOX_ROOT` y Box sintéticos, árbol Box comparado byte a byte
en tearDown, `guard()` (cualquier `mkdir`, `rename`, `remove`, `shutil.copy*`, escritura `Path`)
durante la copia. La copia P3B1 se ejecuta **real** y espiada; solo se simulan su rechazo y un
registro concurrente. Sin `skip` ni `xfail`.

| Suite | Cobertura |
|---|---|
| `ScopeTests` | El diálogo de vinculación no nombra ni importa la copia (import tardío del diálogo nuevo); el diálogo nuevo solo llama a las 4 funciones del servicio, sin `os`/`pathlib`/`sqlite3`/`database`; el servicio solo usa de Bandeja la copia, `BoxCopyIncomplete` e `INBOX_ROOT`, una única llamada, SQL solo `SELECT`, apertura `rb`. |
| `GateTests` | `EXECUTION_ENABLED = False` en el AST; con la vía cerrada (False/None/1/"True") la ejecución se rechaza sin escrituras; el diálogo solo revisa (casilla y botón deshabilitados, motivo visible). |
| `ReviewTests` | Elegibilidad (no vinculado, ya copiado, descartado, duplicado, inexistente, sin Bandeja, repetido, archivo ajeno, destinos mezclados, expediente archivado); actor nulo/inexistente/inactivo/nombre falso; nombres y colisiones proyectados sin reservar; carpetas hostiles (`..`, absolutas, UNC, ocultas, inexistentes, no texto); nomenclaturas no confiables; vínculo a otro expediente, cliente o expediente NULL; destinos inválidos; enlace/unión dentro de la raíz nunca ofrecido. |
| `ExecutionTests` | Copia única verificada y registrada sin cambiar el vínculo, homónimo intacto (`_2`), repetición y copia del plan; lote de 4 con rechazo intermedio y nombre efectivo; copia sin registrar (registro concurrente) que detiene el lote; reutilización de idéntico; 7 cambios entre revisión y ejecución (contenido, re-vinculación, `updated_at`, origen sustituido, nombre ocupado, carpeta borrada, raíz cambiada) + expediente de otro cliente; revalidación por documento; confirmación y huella; campos del plan manipulados; doble clic y revisión paralela (hilos); plan de otra BD. |
| `ViewerDialogTests` | Comando habilitado/deshabilitado con motivo; `LinkForm` intacto; un diálogo a la vez; revisión, consentimiento, invalidación y ejecución única (doble clic) con estado del visor intacto; reintento sin duplicar; cancelar/cerrar/navegar/cerrar visor sin escrituras; `Vincular` no escribe en Box y después el archivado conserva el vínculo; comparador 4 con selección estable; destinos mezclados; fallo parcial no presentado como éxito y reintento; cambio tras consentir exige nueva revisión; sin usuario de sesión. |

### Evidencia de ejecución

Este trabajo se hizo **sin shell** (proveedor Claude sin ejecución): la suite y la batería de 13
archivos **no se han ejecutado** en esta sesión. Las aserciones se han contrastado a mano con el
código real (P3A, P3B1, DV24, visor), pero la evidencia de que pasan, `git diff --check`, el árbol
limpio y el checkpoint corresponden al Fabric Runner (`RUNNER_ACCEPTANCE`).

## Mitigaciones

- Sin primitiva de archivo en el servicio ni en la UI: solo la llamada explícita a P3B1.
- Revisión solo lectura (conexión `mode=ro`, sin `ensure_*`, sin `get_inbox_item`).
- Huella + token de un solo uso + cerrojo por plan + reclamación por ítem en proceso + bloqueo P3B1.
- Revalidación total al empezar y por documento justo antes de cada copia.
- Rechazo explícito de lo no vinculado o vinculado a otro destino: ninguna transición de vínculo.
- La BD de la revisión debe ser la BD del CRM (P3B1 escribe siempre en `DB_PATH`).
- Respuesta de P3B1 comprobada; copias sin registrar señaladas con su ruta, nunca borradas.

## Riesgos residuales y límites

- **Idempotencia entre procesos (motivo de la vía cerrada)**: dos instancias del CRM (otro equipo u
  otro proceso) pueden archivar el mismo ítem a la vez; P3B1 solo bloquea dentro del proceso y deja
  una copia extra verificada pero sin registrar (`stage="register"`). Se detecta, se informa
  (`incomplete`, ruta para revisión) y detiene el lote, pero no se puede impedir sin un cambio
  dedicado en P3B1 o un bloqueo compartido (fuera de las 5 rutas). Test:
  `test_unregistered_copy_stops_the_batch_for_review`. Habilitar requiere esa resolución y la
  aprobación de Dirección: cambiar `EXECUTION_ENABLED` en el código, nunca desde la UI.
- **Carpeta borrada entre la revalidación y la copia**: P3B1 la recrearía (`mkdir` de uno en uno,
  dentro de la raíz). Ventana muy corta; TOCTOU de carpetas de P3B1 sigue vigente.
- Nombres proyectados no reservados: si cambia la carpeta entre documentos del lote, el nombre
  efectivo puede diferir del previsto (se informa).
- **Box real no probado**; marcadores Cloud Files pendientes de comprobar en el equipo real (P3B1).
- **Visual pendiente**: la fila de información gana un comando; requiere smoke visual Flet supervisado
  (anchura en viewports compactos, diálogo de 760 px con tabla).
- La vista de Bandeja no se refresca tras archivar desde el visor (`on_linked` no se invoca para no
  mezclar contratos); el estado se ve al recargar.

## Siguientes pasos

1. Fabric Runner: suite P3B2 + batería (P3B1, P3A, toolbar, selection, DV24 multidoc/notes/linking,
   DV23 visual/close/pdf_tools, foundation, integrations), `git diff --check`, checkpoint.
2. Auditoría independiente read-only.
3. Resolución dedicada de la idempotencia entre procesos; smoke visual; aprobación de Dirección antes de
   abrir la vía sobre Box real o integrar.
