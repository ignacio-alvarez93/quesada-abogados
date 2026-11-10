# WO-DV25-P3A · Destino y nomenclatura con previsualización (sin copia)

Rama `feature/document-viewer-dv25-seleccion-nomenclatura` (sobre P1 `e0b555c` y P2 `c62ad684`).
La copia física queda para P3B, después de la auditoría de seguridad.

## Diagnóstico de partida (solo lectura)

| Pieza | Contrato real |
|---|---|
| `document_viewer_link_dialog.py` | `ViewerLinking(actor, inbox_items, on_linked, db_path)`; `LinkForm`: cliente → expediente → `prepare_link` → doble confirmación (`confirm` + `transfer`) → `execute_link`. |
| `document_viewer_link_service.py` | `resolve_target(client, expedient)` (existe, activo, del cliente), `check_document`/`inspect_documents`, `decide`, `prepare_link`, `execute_link`. Solo `link_inbox_item` escribe. |
| `document_inbox_service.py` | `get_expedient(id)` devuelve `box_folder_path`. `copy_inbox_item_to_expedient_box(item, expedient, subfolder, target_filename)` hace `mkdir(parents=True)` de la subcarpeta, `shutil.copy2`, actualiza el ítem a `copied_to_box`; **no valida `..` ni rutas absolutas en `subfolder`** (solo `strip("/")`). No se modifica (P3B). |
| `document_classification_catalog_service.list_options_for_expedient(id, db_path)` | Devuelve `{"expediente", "specific", "procedural", "options"}`; cada opción: `documento_catalogo_id`, `codigo`, `nombre`, `label` (`nombre · rol`), `rol_documental`, `categoria`, `descripcion`, `origen` (`EXPEDIENTE`/`PROCEDIMIENTO`), `prioridad`. Específicas deduplicadas por documento + rol, filtradas por tipo y subtipo (o subtipo nulo), activas; después transversales. |
| `list_expediente_box_directory(path, relative_base)` | Explorador readonly de un nivel (`folders`, `files`). |
| `document_inbox_view.py` (selector existente) | Usa `list_options_for_expedient` y deriva `target_filename = "nombre rol"`; la subcarpeta es texto libre normalizado. |

### Bloqueo documentado: `list_options_for_expedient` migra

`list_options_for_expedient` llama a `ensure_schema()`, que ejecuta
`database/migrations/20260810_create_procedural_document_nomenclatures.sql` (`CREATE TABLE IF NOT
EXISTS`, índices e `INSERT OR IGNORE` en `config_documentos_catalogo` y
`config_nomenclaturas_procedimentales`). Llamarla desde P3A sería una escritura de esquema y datos.
Por eso P3A **no la llama**: reutiliza sus lectores (`_get_expedient`, `_specific_options`,
`_procedural_options`, mismo SQL, mismo orden y forma) sobre `connection.get_readonly_connection`
(`mode=ro` + `query_only`). Si falta una tabla del catálogo se muestra «esquema no migrado» y no se
crea nada. Un test compara el resultado con `list_options_for_expedient` sobre una copia temporal.
Decisión pendiente de Dirección: aplicar la migración por el cauce habitual o exponer un lector
público sin `ensure_schema` en el servicio de catálogo.

## Cambios

| Archivo | Cambio |
|---|---|
| `backend/services/document_viewer_filing_plan_service.py` (nuevo) | Servicio puro de solo lectura: `load_context` (expediente validado con `resolve_target`, raíz Box, carpetas, catálogo), `list_folders`, `verify_folder`, `clean_relative`, `catalog_options`, `safe_stem`, `blocker`, `build_preview`. |
| `frontend/components/document_viewer_link_dialog.py` | `LinkForm` añade la sección «Archivo en Box (previsualización)», la tabla de preview y el botón deshabilitado `Vincular y archivar copia`. Sin SQL ni filesystem. |
| `scripts/tests/test_document_viewer_dv25_filing_plan.py` (nuevo) | Suite P3A sobre las fixtures DV24. |

`test_document_viewer_dv24_linking.py` no se ha modificado.

### FIX1 · Integridad de esquema en navegación

`DialogTests.test_cancel_close_and_navigation_have_no_side_effects` fallaba en `tearDown`
(`schema() != schema_before`): tres objetos nuevos (`document_viewer_notes`, su autoíndice
`UNIQUE` e `idx_document_viewer_notes_document`). Origen: la migración DV24-P2 de notas, que
`document_viewer_notes_service._ensure_schema` → `document_viewer_notes_repository.ensure_schema`
aplica la primera vez que se usan notas: la propia fixture del test (`add_document_note`) y el
panel de notas del visor (`load_document_notes`). No interviene P3A: el `ensure_schema` del
catálogo sigue parcheado para fallar y el servicio de archivo solo usa
`get_readonly_connection`. Es el único test de diálogo con notas.

Corrección (solo en el test): `FilingBase.setUp` aplica la migración de notas a la BD
**temporal** con `notes_repository.ensure_schema` antes de tomar `schema_before`. La aserción de
invariancia de esquema se mantiene sin cambios para cancelar, cerrar y navegar; no hay snapshot
posterior ni tablas exentas. Las llamadas posteriores a `ensure_schema` son idempotentes
(`IF NOT EXISTS`). No se tocan el frontend, el servicio P3A ni las migraciones.

## Comportamiento

- **Carpeta**: solo carpetas existentes bajo `box_folder_path`, como ruta relativa POSIX
  (`02 LABORAL/Contratos`); la raíz aparece como `<raíz del expediente>` (etiqueta imposible como
  nombre de carpeta). Se excluyen ocultas (`.`/`~`), enlaces simbólicos y uniones, y todo lo que
  resuelva fuera de la raíz. Profundidad 4, máx. 500. La carpeta elegida se vuelve a verificar
  en disco al calcular la preview; no se confía en el valor devuelto por la UI.
- **Sin Box local** (sin ruta, inexistente, no carpeta, relativa, enlace o sin acceso): aviso de
  bloqueo de destino; la vinculación lógica sigue disponible.
- **Nomenclatura**: un selector por documento archivable (también en lote; nunca se asigna en
  bloque), con las opciones del expediente elegido, específicas primero y transversales después.
  Sin texto libre: una etiqueta que no es opción de ese contexto se descarta.
- **Invalidación**: cambiar cliente o expediente descarta contexto, carpeta, nomenclaturas,
  preview y confirmación; los eventos tardíos de selectores anteriores se ignoran.
- **Preview** por documento: origen, Bandeja, nomenclatura/rol, subcarpeta, nombre propuesto y
  estado (`propuesto`, `colision_proyectada`, `sin_nomenclatura`, `sin_bandeja`, `bloqueado`).
  Nombre = `nombre rol` saneado (`<>:"/\|?*` y controles → `_`, sin espacios/puntos finales,
  nombres de dispositivo Windows con `_`, máx. 120) + extensión real del origen tal cual. Las
  colisiones con la carpeta y dentro del lote se proyectan (`_2`, `_3`), sin reservar.
- Descartados, duplicados, ya copiados a Box (reglas `decide` de DV24) e ítems inexistentes no
  reciben propuesta. Documentos sin `inbox_item_id`: `sin_bandeja`, como en DV24.
- `Vincular` sigue siendo la única operación (`execute_link`, doble confirmación de traslado). Nada
  de la preview se escribe en la base de datos ni en Box.
- `Vincular y archivar copia`: deshabilitado, «Pendiente de verificación de copia segura P3B».

## Riesgos para P3B

- `copy_inbox_item_to_expedient_box` crea subcarpetas (`mkdir(parents=True)`) y no rechaza `..` ni
  rutas absolutas en `subfolder`; P3B debe pasar solo la ruta verificada por `verify_folder`.
- `_unique_destination` (`exists()` + `copy2`) tiene una carrera TOCTOU; la preview no reserva el
  nombre: puede cambiar entre la previsualización y la copia.
- El lote de copia no es atómico (`copy_document_inbox_batch_to_expedient_box` sigue por ítem).
- `_safe_filename` de Bandeja no trata nombres de dispositivo Windows; P3B debe enviar el nombre
  saneado por `safe_stem`.
- El listado de carpetas se hace de forma síncrona al elegir expediente; en Box Drive con muchas
  carpetas puede tardar.
- Esquema del catálogo: ver el bloqueo anterior.
