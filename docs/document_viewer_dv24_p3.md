# WO-DV24-P3 · Vinculación individual y múltiple a expedientes desde el visor

Rama `feature/document-viewer-dv24-multidoc-notas-20261109`, sobre P1 (multidocumento) y P2 (notas).
Referencia visual: `docs/design/visor_dv24_comparador_referencia.png`.

## Vincular no es copiar

Vincular es **lógico**: el ítem de Bandeja recibe `client_id`, `expedient_id` y estado `linked`, y la
Bandeja registra su evento `linked`, todo mediante `document_inbox_service.link_inbox_item`. **No** se copia a
Box, ni se mueve, renombra o modifica un archivo; tampoco se importa nada, no se crea ningún ítem de Bandeja ni
se lanzan watchers o sincronizaciones. La copia a Box sigue siendo el flujo propio de Bandeja.

## Diagnóstico del servicio canónico

`link_inbox_item(item_id, client_id, expedient_id)`:

- comprueba que el ítem, el cliente y el expediente existen, pero **no que el expediente pertenezca al cliente**
  (acepta cliente 8 + expediente del cliente 7; la suite lo demuestra sobre SQLite sintética);
- sobrescribe un vínculo previo con otro expediente sin preguntar y no consulta el estado
  (`discarded`, `duplicate`, `copied_to_box`);
- hace `commit` por ítem, sin escritura condicional.

No se modifica (fuera de alcance). Las reglas que faltan se aplican en la capa de aplicación DV24.

## Cambios

| Archivo | Cambio |
|---|---|
| `backend/services/document_viewer_link_service.py` (nuevo) | Servicio de aplicación: actor, expediente↔cliente, identidad del ítem y ruta, revisión por documento, ejecución única por plan. Única escritura: `link_inbox_item`. Sin `sqlite3`. |
| `frontend/components/document_viewer_link_dialog.py` (nuevo) | `ViewerLinking` (contexto que inyecta la vista), `LinkController` (estado en la fila de información, selección múltiple) y `LinkForm` (diálogo de confirmación). Sin SQL. |
| `frontend/components/document_viewer_modal.py` | Parámetro keyword-only `linking=None`: estado y `Vincular a expediente` en la fila de información; en `Comparador 4`, contador y `Vincular seleccionados`. Sin `linking`, visor idéntico a P2. |
| `frontend/components/document_viewer_multidoc.py` | `TileView`/`comparator_grid` aceptan `selection`: casilla por tile; el documento activo pasa a marcarse con un indicador radio. |
| `frontend/components/document_viewer_notes_panel.py` | `NotesController.refresh(documents)`: recarga la actividad de los documentos vinculados sin tocar borradores ni envíos en curso. |
| `frontend/views/document_inbox_view.py` | `state["viewer_linking"] = ViewerLinking(actor=current_user, on_linked=…refresh_items())`; `inbox_viewer_options` añade `linking` con (ruta, ítem) de la cola. Sin cambios Box. |
| `frontend/views/expedients_view.py` | `state["viewer_linking"] = ViewerLinking(actor=current_user)`; `show_document_preview` pasa `linking=`. Sin cambios Box. |
| `scripts/tests/test_document_viewer_dv24_linking.py` (nuevo) | Suite P3. |
| `scripts/tests/test_document_viewer_dv24_multidoc.py`, `..._integrations.py`, `..._foundation.py` | Contratos fijados: firma con `linking` (keyword-only, `None`) y llamadas exactas de Expedientes con `linking=None`. |

No se tocan `document_inbox_service.py`, `database/connection.py`, migraciones, Box, `data/`, `storage/`,
`runtime/` ni la identidad de usuarios.

## Reglas de la capa de aplicación

Revisión (`prepare_link`, solo lectura) y ejecución (`execute_link`) separadas:

1. **Actor**: el usuario de sesión se verifica en `users` como en las notas (existe, activo, mismo
   `username`); se vuelve a verificar al confirmar.
2. **Destino**: el expediente existe, tiene cliente, **pertenece al cliente elegido** y está activo. A
   `link_inbox_item` se le pasa siempre ese cliente propietario. Se revalida al confirmar: si entretanto se
   borró, archivó o cambió de cliente, no se escribe nada.
3. **Identidad**: el ítem existe y la ruta que muestra el visor (canonicalizada) es su `stored_path` o
   `linked_document_path`. Si no, se rechaza.
4. **Estado previo**:
   - ya vinculado a ese expediente y cliente → `sin cambios` (idempotente, sin escribir ni crear evento);
   - vinculado a otro expediente o asignado a otro cliente → **traslado**: se rechaza salvo la casilla de
     confirmación especial;
   - `discarded`, duplicado (`duplicate_of_id`) o ya `copied_to_box` → rechazado siempre.
5. **Sin ID de Bandeja** (carpeta de expediente/Box): `No vinculable directamente; requiere flujo de
   incorporación gobernado`. No se importa, no se crea un ítem y no se inventa una asignación.
6. **Datos obsoletos**: justo antes de escribir se relee cada ítem; si cambió algún campo de la revisión
   (`stored_path`, `linked_document_path`, cliente, expediente, estado, `updated_at`), se omite con aviso.
7. **Ejecución única**: un plan se ejecuta una vez bajo lock; repetirlo devuelve el mismo resultado. El
   diálogo además ignora clics mientras hay un envío y tras el resultado.
8. **Notas**: la vinculación no lee ni escribe `document_viewer_notes`.

## Lotes: política

`link_inbox_item` confirma cada ítem por separado, así que **el lote no es atómico** (`LinkResult.atomic =
False`). Cada documento se revisa y se ejecuta de forma independiente; un fallo no deshace los ya
vinculados. El resultado lista el estado y el mensaje de cada documento (`vinculado`, `sin cambios`, `no
vinculable`, `rechazado`, `fallido`) y, si es parcial, el diálogo lo dice explícitamente junto con la política.

## UX

- Fila de información: estado del documento activo (`Sin expediente`, `Expediente #N`, `Vinculado a …`,
  `No vinculable directamente`) y `Vincular a expediente`.
- `Comparador 4`: casilla por tile, contador (`N seleccionados`) y `Vincular seleccionados` (desactivado sin
  selección). La selección es independiente del documento activo: PDF, notas, página y zoom siguen al activo.
- Diálogo: aviso de vinculación lógica, documentos con su expediente/cliente actual, `Cliente` y `Expediente
  del cliente` con `AppAutocomplete` y las opciones de Bandeja (`client_autocomplete_options`,
  `expedient_autocomplete_options_for_client`), revisión por documento, casilla de traslado si procede y
  confirmación explícita con documento(s), expediente y cliente. Cambiar cualquier elección anula la
  confirmación. `Cancelar` no escribe.
- Tras vincular: se actualizan el estado y la actividad de Bandeja en el panel de notas; grupo, documento
  activo, página, zoom, notas y borradores se mantienen. Los vinculados salen de la selección; los
  rechazados siguen marcados. Bandeja refresca su listado.

## Evidencia de identidad y autorización

- Autor de la operación: `LinkResult.user` (`{"id", "username"}` leído de `users`), mostrado en el resultado.
- El CRM no tiene permisos por expediente/cliente (`users` solo `is_active`): autorizado = usuario activo +
  documento y expediente verificados. No se inventan permisos (mismo bloqueo elevado en P2).

## Pruebas

Runner: `python -m pytest -q scripts/tests/test_document_viewer_dv24_linking.py scripts/tests/test_document_viewer_dv24_notes.py scripts/tests/test_document_viewer_dv24_multidoc.py scripts/tests/test_document_viewer_dv23_pdf_tools.py scripts/tests/test_document_viewer_integrations.py`

La suite P3 crea un CRM SQLite sintético temporal (`users`, `clientes`, `expedientes`, Bandeja) y redirige
`database.connection.DB_PATH` a él: `link_inbox_item` y `get_inbox_item` reales. `_ensure_dirs` se neutraliza
(no se crea `data/document_inbox`), los selectores CRM son lecturas falsas sobre ese archivo y cualquier
otra mutación Bandeja/Box falla el test. Al terminar comprueba bytes y `mtime` de todos los PDF, que no hay
ítems nuevos ni archivos en la carpeta del expediente y que no se llamó a ninguna mutación prohibida.

Cobertura: vínculo simple y lote; cliente–expediente válido/inválido (y evidencia del hueco canónico);
expediente ausente, sin cliente o archivado; ítem inexistente, eliminado tras la revisión o con otra ruta;
traslado con/sin confirmación especial; descartado, duplicado, copiado a Box; idempotencia; plan único y
doble clic (también reentrante); cancelación; actor ausente/inactivo/suplantado; datos obsoletos; fallo
intermedio sin deshacer el resto; respuesta canónica inconsistente; documentos de carpeta sin escrituras;
notas intactas; selección activa vs lote; navegación posterior; errores visibles; cableado de vistas.
Regresión DV23 (siete operaciones PDF): `test_document_viewer_dv23_pdf_tools.py` dentro del comando Runner.

## Smoke en Flet real (pendiente de aceptación humana)

1. Bandeja → abrir un documento sin expediente → fila de información `Sin expediente`.
2. `Zoom +`, avanzar página → `Vincular a expediente` → cliente preseleccionado, elegir expediente, revisar,
   marcar la confirmación → `Vincular`. Comprobar `Vinculado a …`, misma página y zoom, notas intactas, y en
   Bandeja el ítem como `Vinculado` **sin** copia en la carpeta Box.
3. Repetir sobre el mismo documento → `Ya vinculado a este expediente: sin cambios`.
4. Elegir un expediente de otro cliente desde el selector no es posible; un ítem ya vinculado a otro
   expediente muestra el aviso de traslado y no se mueve sin la casilla especial.
5. Seleccionar ≥2 documentos en Bandeja → visor → `Comparador 4` → marcar 3 casillas (incluido uno
   descartado) → activar otro tile y cambiar su zoom → `Vincular seleccionados` → resultado parcial explícito;
   el tile activo conserva página y zoom; los rechazados siguen marcados.
6. Expedientes → abrir un documento de la carpeta → `Vincular a expediente` → `No vinculable directamente;
   requiere flujo de incorporación gobernado`, sin botón `Vincular`.
7. `Cancelar` y cerrar el visor con el diálogo abierto: sin cambios en Bandeja.

## Bloqueos elevados y riesgos

- **Permisos por expediente**: inexistentes en el CRM; ver P2. Requiere decisión de Dirección.
- **Escritura condicional**: `link_inbox_item` no admite «actualizar solo si no cambió». La relectura previa
  reduce la ventana, pero un cambio concurrente entre relectura y `UPDATE` es posible. Cerrarla exige cambiar
  el servicio canónico (fuera de alcance): elevado a Dirección.
- **Vinculación existente en Bandeja** (`link_selected`): sigue usando el servicio canónico sin la validación
  cliente↔expediente. No se modifica en P3 (solo cableado del visor); se recomienda migrarla a este servicio.
- `get_inbox_item` llama a `ensure_document_inbox_schema()` (comportamiento existente).
