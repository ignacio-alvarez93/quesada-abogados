# WO-DV25-P1 · Comparador limitado a documentos marcados

Rama `feature/document-viewer-dv25-seleccion-nomenclatura` (sobre DV24).

## Diagnóstico de partida

DV24 decidió que «la cola es el listado visible, en su orden». Toda previsualización por tarjeta
pasaba el listado completo como `queue`:

- Expedientes: `files_queue` (explorador de carpeta Box), `listing_queue` («Documentos del
  expediente») y `rows_queue` (listado inline, cuya casilla «Ver» abría el visor al marcarla).
- Bandeja: `inbox_viewer_options(queue_items=state["items"], marked_ids=...)` usaba la página
  entera salvo que hubiera ≥2 marcados que incluyeran el ítem; ficha y grupo pasaban todo el
  listado o todo el lote.
- «Ver seleccionados» del explorador usaba el orden de clic y conservaba marcas de otras carpetas
  (`state["document_viewer_selected_docs"]` es global al expediente).
- En la Bandeja, volver a clicar la tarjeta activa llamaba a `clear_selection()` y borraba en
  silencio las marcas.

## Cambios

| Archivo | Cambio |
|---|---|
| `frontend/components/document_viewer_multidoc.py` | `marked_queue(visible, marked)`: instantánea de los marcados del listado visible, en su orden, sin duplicados ni entradas sin identidad. `path_key()`, `view_selected_action()` (acción de `bulk_action_bar` deshabilitada con motivo en el tooltip; anuncia los marcados ocultos sin añadirlos). |
| `frontend/views/expedients_view.py` | `Previsualizar` abre solo su documento. `Ver seleccionados` = `marked_queue` sobre los archivos visibles en: explorador de carpeta, diálogo «Documentos del expediente» (casillas de `document_file_card`, sin componente nuevo), listado inline (la casilla ya solo marca; botón `Previsualizar` por fila) y diagnóstico (orden visible, botón deshabilitado sin marcas). |
| `frontend/views/document_inbox_view.py` | `marked_inbox_items()`; `inbox_viewer_options(queue_items=)` recibe la instantánea (sin `marked_ids`). `show_preview`, ficha y `Previsualizar` del grupo abren solo el ítem. `Ver seleccionados` en la barra de la bandeja y en la del grupo. `refresh_items` recalcula la barra. Desactivar la tarjeta activa conserva las marcas (`clear_selection(keep_marked=True)`). |
| `scripts/tests/test_document_viewer_dv25_selection.py` (nuevo) | Suite DV25. |
| `..._dv24_multidoc.py`, `..._dv24_notes.py`, `..._dv24_linking.py`, `..._integrations.py`, `..._foundation.py` | Contratos DV24 que fijaban «cola = listado» pasan a «cola = marcados»; 4 llamadas canónicas en Bandeja. |

## Comportamiento

- 0 marcados visibles: `Ver seleccionados` deshabilitado con motivo; sin fallback a la carpeta.
- 1 marcado: visor individual DV23. 2–4: un grupo. >4: grupos de cuatro.
- Marcas ocultas (otra carpeta, página o filtro) no se borran ni entran en la cola; el tooltip las
  cuenta. Recuperarlas exige volver a ese listado.
- El activo de la vista no entra en la cola si no está marcado; en el visor, clicar un tile cambia
  el activo sin tocar la cola ni las casillas.
- La cola es una copia: cambiar modo, zoom, página o grupo no reconsulta ni amplía.
- Herramientas PDF: solo sobre el documento activo (sin cambios respecto a DV24).
- Sin cambios en Box ni en la persistencia documental.
